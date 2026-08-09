from __future__ import annotations

import json
import subprocess

import pytest

from tycho.serving import codex_luna_plugin as plugin
from tycho.serving import llm_client


TOOLS = [
    {
        "name": "take_action",
        "description": "Commit one action.",
        "schema": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
    }
]


def test_codex_config_projects_through_tycho_plugin(monkeypatch) -> None:
    monkeypatch.setenv("TYCHO_LLM_PLUGIN", "tycho.serving.codex_luna_plugin")
    monkeypatch.setenv("LLM_BACKEND", "codex")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("LLM_EFFORT", "high")

    cfg = llm_client.LLMConfig.from_env()

    assert cfg.backend == "codex"
    assert cfg.model == "gpt-5.6-luna"
    assert cfg.reasoning_effort == "high"
    assert cfg.api_protocol == "codex_cli"
    assert cfg.public_model == "gpt-5.6-luna"
    assert cfg.provider_options["codex_binary"] == "codex"


def test_codex_jsonl_parsing_and_usage_normalization() -> None:
    payload = {
        "text": "",
        "reasoning_summary": "move right",
        "tool_calls": [{"name": "take_action", "input_json": '{"action":"ACTION2"}'}],
    }
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(payload)},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 20,
                        "output_tokens": 15,
                    },
                }
            ),
        ]
    )

    parsed, raw_usage = plugin._parse_jsonl(stdout)
    calls = plugin._decode_tool_calls(parsed, TOOLS)

    assert parsed == payload
    assert calls[0]["name"] == "take_action"
    assert calls[0]["input"] == {"action": "ACTION2"}
    assert calls[0]["id"].startswith("codex-")
    assert plugin._normalized_usage(raw_usage) == {
        "in": 100,
        "out": 15,
        "cache_read": 20,
        "cache_write": 0,
    }


def test_codex_transport_passes_image_schema_and_isolates_tools(monkeypatch) -> None:
    captured = {}
    payload = {
        "text": "",
        "reasoning_summary": "test image received",
        "tool_calls": [{"name": "take_action", "input_json": '{"action":"ACTION1"}'}],
    }
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(payload)},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
                }
            ),
        ]
    )

    def fake_run(command, *, prompt, timeout):
        captured.update(command=command, prompt=prompt, timeout=timeout)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(plugin.shutil, "which", lambda _binary: "/usr/bin/codex")
    monkeypatch.setattr(plugin.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(plugin, "_run_with_retry", fake_run)
    monkeypatch.setattr(plugin, "_note_status", lambda *_args, **_kwargs: None)
    cfg = plugin.LLMConfig(model="gpt-5.6-luna", reasoning_effort="max", public_model="gpt-5.6-luna")

    reply = plugin.chat_tools(
        [{"role": "user", "content": [{"text": "frame"}, {"image_png": b"not-a-real-png"}]}],
        TOOLS,
        cfg,
        system="Choose one action.",
        max_tokens=256,
        timeout=12,
        effort="max",
        call_type="test",
    )

    command = captured["command"]
    assert command[:2] == ["/usr/bin/codex", "exec"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--sandbox" in command and "read-only" in command
    assert "features.shell_tool=false" in command
    assert "tools.web_search=false" in command
    assert "agents.enabled=false" in command
    assert 'forced_login_method="chatgpt"' in command
    assert 'model_reasoning_effort="xhigh"' in command
    assert "--image" in command
    assert "--output-schema" in command
    assert command[-1] == "-"
    assert "take_action" in captured["prompt"]
    assert "attached image 1" in captured["prompt"]
    assert reply["tool_calls"][0]["input"] == {"action": "ACTION1"}
    assert reply["usage"] == {"in": 8, "out": 3, "cache_read": 2, "cache_write": 0}


def test_codex_transport_rejects_unknown_tycho_tool() -> None:
    with pytest.raises(plugin.CodexExecError, match="unknown Tycho tool"):
        plugin._decode_tool_calls(
            {"tool_calls": [{"name": "shell", "input_json": "{}"}]},
            TOOLS,
        )
