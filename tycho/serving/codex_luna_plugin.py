"""Tycho transport plugin for GPT-5.6 Luna through an authenticated Codex CLI session.

This plugin deliberately does not read or copy Codex credentials. ``codex exec`` owns
all authentication and reuses the user's existing ``codex login`` session.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


OVERRIDE_BACKENDS = {"codex"}
_REC = threading.local()


@dataclass
class LLMConfig:
    model: str
    backend: str = "codex"
    base_url: str = ""
    api_key: str = ""
    region: str = ""
    reasoning_effort: str = ""
    api_protocol: str = "codex_cli"
    public_model: str = ""
    codex_binary: str = "codex"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        model = os.environ.get("LLM_MODEL", "gpt-5.6-luna")
        backend = os.environ.get("LLM_BACKEND", "codex").lower()
        if backend != "codex":
            raise SystemExit(f"codex plugin handles only LLM_BACKEND=codex, got {backend!r}")
        return cls(
            model=model,
            backend=backend,
            reasoning_effort=os.environ.get("LLM_EFFORT", ""),
            public_model=os.environ.get("LLM_PUBLIC_MODEL", model),
            codex_binary=os.environ.get("CODEX_BINARY", "codex"),
        )


def handles_backend(backend: str) -> bool:
    return (backend or "").lower() == "codex"


def reasoning_kind_for(backend: str) -> str:
    return "summary" if handles_backend(backend) else "none"


def response_id_continuity_enabled(_cfg: LLMConfig) -> bool:
    # Each invocation is intentionally ephemeral/stateless. Tycho provides full retained history.
    return False


def start_recording() -> None:
    _REC.buf = []
    _REC.system = ""


def set_system_prompt(text: str) -> None:
    _REC.system = text or ""


def take_recording() -> list:
    out = list(getattr(_REC, "buf", None) or [])
    if hasattr(_REC, "buf") and _REC.buf is not None:
        _REC.buf.clear()
    return out


def stop_recording() -> None:
    _REC.buf = None


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, subprocess.TimeoutExpired):
        return True
    if isinstance(error, CodexExecError):
        text = str(error).lower()
        return any(marker in text for marker in (
            "429", "rate limit", "temporarily unavailable", "timeout", "timed out",
            "connection reset", "connection refused", "503", "502", "500",
        ))
    return False


class CodexExecError(RuntimeError):
    """Raised when the Codex CLI transport cannot produce a valid Tycho reply."""


def _schema() -> dict:
    # Keep tool arguments as JSON text: Tycho tools do not all share one object shape, while
    # Codex --output-schema requires one stable final-response schema.
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "reasoning_summary": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "input_json": {"type": "string"},
                    },
                    "required": ["name", "input_json"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["text", "reasoning_summary", "tool_calls"],
        "additionalProperties": False,
    }


def _tool_contract(tools: list[dict]) -> str:
    if not tools:
        return "No tools are available. Return tool_calls as an empty array."
    lines = [
        "Available Tycho tools (choose only from these names; input_json must be valid JSON that matches the shown schema):"
    ]
    for tool in tools:
        lines.append(
            f"- {tool['name']}: {tool.get('description', '')}\n"
            f"  schema={json.dumps(tool.get('schema') or {}, sort_keys=True, separators=(',', ':'))}"
        )
    return "\n".join(lines)


def _content_text_and_images(content, images: list[bytes]) -> str:
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if "text" in part:
            out.append(str(part.get("text", "")))
        elif part.get("image_png") is not None:
            images.append(part["image_png"])
            out.append(f"[attached image {len(images)}]")
    return "\n".join(out)


def _serialize_history(history: list[dict]) -> tuple[str, list[bytes]]:
    images: list[bytes] = []
    chunks: list[str] = []
    for index, message in enumerate(history):
        role = str(message.get("role", "user")).upper()
        if role == "TOOL":
            results = []
            for result in message.get("results", []):
                block = f"tool_result id={result.get('id', '')} name={result.get('name', '')}: {result.get('output', '')}"
                if result.get("image_png") is not None:
                    images.append(result["image_png"])
                    block += f"\n[attached image {len(images)}]"
                results.append(block)
            body = "\n".join(results)
        else:
            body = _content_text_and_images(message.get("content", ""), images)
            if message.get("tool_calls"):
                rendered = [
                    f"tool_call id={call.get('id', '')} name={call.get('name', '')} input={json.dumps(call.get('input', {}), sort_keys=True)}"
                    for call in message.get("tool_calls", [])
                ]
                body = "\n".join(filter(None, [body, *rendered]))
        chunks.append(f"[{index}:{role}]\n{body}")
    return "\n\n".join(chunks), images


def _prompt(history: list[dict], tools: list[dict], system: str, max_tokens: int) -> tuple[str, list[bytes]]:
    transcript, images = _serialize_history(history)
    prompt = f"""You are the model transport inside the Tycho ARC-AGI-3 harness.
Do not execute shell commands, edit files, browse the web, or call external tools. Your only job is to continue the supplied conversation and either respond with text or request Tycho tools using the final JSON schema.

SYSTEM INSTRUCTIONS FROM TYCHO:
{system or '(none)'}

TYCHO TOOL CONTRACT:
{_tool_contract(tools)}

CONVERSATION TRANSCRIPT:
{transcript or '(empty)'}

OUTPUT RULES:
- Return only the structured response requested by the output schema.
- reasoning_summary is a brief rationale/decision summary, not hidden chain-of-thought.
- tool_calls may contain zero or more calls.
- Every tool call name must exactly match an available Tycho tool.
- input_json must be a JSON object encoded as a string and must satisfy that tool's schema.
- Do not invent results for tools; request them and let Tycho return their outputs on the next turn.
- Keep text concise when tool_calls are present.
- The requested Tycho max output budget is {max_tokens} tokens; stay within it.
"""
    return prompt, images


def _parse_jsonl(stdout: str) -> tuple[dict, dict]:
    final_text = ""
    usage = {}
    errors = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                final_text = item.get("text", "") or final_text
        elif kind == "turn.completed":
            usage = event.get("usage") or usage
        elif kind in ("turn.failed", "error"):
            errors.append(event)
    if not final_text:
        detail = json.dumps(errors[-1], ensure_ascii=False) if errors else stdout[-2000:]
        raise CodexExecError(f"codex produced no final agent message: {detail}")
    try:
        payload = json.loads(final_text)
    except json.JSONDecodeError as exc:
        raise CodexExecError(f"codex final message was not valid JSON: {final_text[:1000]}") from exc
    return payload, usage


def _normalized_usage(usage: dict) -> dict:
    total_input = int(usage.get("input_tokens") or 0)
    cache_read = int(usage.get("cached_input_tokens") or 0)
    return {
        "in": max(0, total_input - cache_read),
        "out": int(usage.get("output_tokens") or 0),
        "cache_read": cache_read,
        "cache_write": 0,
    }


def _decode_tool_calls(payload: dict, tools: list[dict]) -> list[dict]:
    allowed = {tool["name"] for tool in tools}
    calls = []
    for raw in payload.get("tool_calls") or []:
        name = raw.get("name", "")
        if name not in allowed:
            raise CodexExecError(f"codex requested unknown Tycho tool {name!r}")
        try:
            arguments = json.loads(raw.get("input_json") or "{}")
        except json.JSONDecodeError as exc:
            raise CodexExecError(f"codex returned invalid input_json for {name!r}") from exc
        if not isinstance(arguments, dict):
            raise CodexExecError(f"codex tool input for {name!r} must decode to an object")
        calls.append({"id": f"codex-{uuid.uuid4().hex}", "name": name, "input": arguments})
    return calls


def _record(history, tools, cfg, system, effort, call_type, reply, latency_ms) -> None:
    buf = getattr(_REC, "buf", None)
    if buf is None:
        return
    usage = reply.get("usage") or {}
    entry = {
        "call_type": call_type,
        "model": cfg.public_model or cfg.model,
        "effort": effort or "",
        "prompt": "[Codex CLI transport]",
        "system_prompt": system or "",
        "reasoning_text": reply.get("reasoning", ""),
        "reasoning_kind": "summary",
        "reasoning_summary": reply.get("reasoning", ""),
        "response": reply.get("text", ""),
        "has_image": any(
            isinstance(m.get("content"), list) and any("image_png" in p for p in m.get("content", []))
            or (m.get("role") == "tool" and any(r.get("image_png") is not None for r in m.get("results", [])))
            for m in history
        ),
        "latency_ms": latency_ms,
        "tokens_in": usage.get("in", 0),
        "tokens_out": usage.get("out", 0),
        "cache_read": usage.get("cache_read", 0),
        "cache_write": usage.get("cache_write", 0),
    }
    if tools:
        entry["tools"] = [
            {"name": tool["name"], "description": tool.get("description", ""), "schema": tool.get("schema")}
            for tool in tools
        ]
    buf.append(entry)


def _note_status(call_type: str, cfg: LLMConfig, reply: dict | None = None, error: Exception | None = None) -> None:
    """Mirror Tycho core telemetry because override plugins bypass llm_client's wrapper."""
    try:
        from tycho.harness.run_status import process_status_store
        from tycho.serving.pricing import reply_usage, usage_cost_usd

        store = process_status_store()
        if store is None:
            return
        if error is not None:
            store.note_llm_failed(call_type=call_type or "llm", error=type(error).__name__)
            return
        if reply is None:
            store.note_llm_started(call_type=call_type or "llm")
            return
        usage = reply_usage(reply)
        store.note_llm_finished(
            call_type=call_type or "llm",
            response=(reply.get("text", "") or "") + _tool_calls_digest(reply.get("tool_calls", [])),
            usage=usage,
            model=cfg.public_model or cfg.model,
            cost_usd=usage_cost_usd(usage, cfg.public_model or cfg.model),
        )
    except Exception:  # telemetry must never affect inference
        return


def _tool_calls_digest(calls: list[dict]) -> str:
    if not calls:
        return ""
    return "\n" + "\n".join(
        f"[tool] {call.get('name', '')}({json.dumps(call.get('input', {}), sort_keys=True)})"
        for call in calls
    )


def _run_with_retry(command: list[str], *, prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    budget = float(os.environ.get("LLM_RETRY_BUDGET_S", "1200"))
    started = time.monotonic()
    attempt = 0
    while True:
        try:
            process = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            error: Exception = CodexExecError(f"codex exec timed out after {timeout}s")
            error.__cause__ = exc
        else:
            if process.returncode == 0:
                return process
            detail = (process.stderr or process.stdout or "").strip()[-4000:]
            error = CodexExecError(f"codex exec exited {process.returncode}: {detail}")

        elapsed = time.monotonic() - started
        if not _is_retryable(error) or elapsed >= budget:
            raise error
        delay = min(30.0, 2.0 * (2 ** min(attempt, 4))) * random.uniform(0.75, 1.25)
        if elapsed + delay > budget:
            raise error
        time.sleep(delay)
        attempt += 1


def chat_tools(history: list[dict], tools: list[dict], cfg: LLMConfig | None = None, *,
               system: str = "", max_tokens: int = 4096, timeout: int = 600,
               effort: str | None = None, call_type: str = "", prev_response_id: str | None = None,
               since: int = 0, cache_anchor_index: int | None = None) -> dict:
    del prev_response_id, since, cache_anchor_index
    cfg = cfg or LLMConfig.from_env()
    effort = effort or cfg.reasoning_effort
    binary = shutil.which(cfg.codex_binary) if not os.path.isabs(cfg.codex_binary) else cfg.codex_binary
    if not binary or not os.path.exists(binary):
        raise CodexExecError(
            f"Codex CLI executable {cfg.codex_binary!r} was not found. Install Codex and run 'codex login'."
        )

    prompt, images = _prompt(history, tools, system, max_tokens)
    started = time.monotonic()
    _note_status(call_type, cfg)
    try:
        with tempfile.TemporaryDirectory(prefix="tycho-codex-") as temp_dir:
            root = Path(temp_dir)
            schema_path = root / "reply.schema.json"
            schema_path.write_text(json.dumps(_schema()), encoding="utf-8")
            image_paths = []
            for index, image in enumerate(images, 1):
                path = root / f"frame-{index:03d}.png"
                path.write_bytes(image)
                image_paths.append(path)

            command = [
                binary, "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--cd", str(root),
                "--sandbox", "read-only",
                "-c", 'approval_policy="never"',
                "-c", "features.shell_tool=false",
                "-c", "tools.web_search=false",
                "-c", "agents.enabled=false",
                "-c", "features.skill_mcp_dependency_install=false",
                "-c", 'forced_login_method="chatgpt"',
                "--json",
                "--model", cfg.model,
                "--output-schema", str(schema_path),
            ]
            resolved_effort = (effort or "").lower()
            if resolved_effort == "max":
                resolved_effort = "xhigh"  # current Codex config accepts through xhigh
            elif resolved_effort in ("", "off", "none", "0", "false"):
                resolved_effort = "minimal"
            if resolved_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
                raise CodexExecError(f"unsupported Codex reasoning effort {effort!r}")
            command.extend(["-c", f'model_reasoning_effort="{resolved_effort}"'])
            for path in image_paths:
                command.extend(["--image", str(path)])
            command.append("-")

            process = _run_with_retry(command, prompt=prompt, timeout=timeout)

        payload, raw_usage = _parse_jsonl(process.stdout)
        reply = {
            "text": str(payload.get("text", "")),
            "tool_calls": _decode_tool_calls(payload, tools),
            "stop": "tool_use" if payload.get("tool_calls") else "end_turn",
            "reasoning": str(payload.get("reasoning_summary", "")),
            "raw_reasoning": None,
            "usage": _normalized_usage(raw_usage),
        }
        latency_ms = int((time.monotonic() - started) * 1000)
        reply["latency_ms"] = latency_ms
        _record(history, tools, cfg, system, effort, call_type, reply, latency_ms)
        _note_status(call_type, cfg, reply=reply)
        return reply
    except Exception as error:
        _note_status(call_type, cfg, error=error)
        raise
