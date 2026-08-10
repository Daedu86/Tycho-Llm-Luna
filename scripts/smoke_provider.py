#!/usr/bin/env python3
"""One-call, opt-in smoke test for a Tycho model transport."""

from __future__ import annotations

import argparse
import io
import os

from PIL import Image, ImageDraw

from tycho.serving.llm_client import LLMConfig, chat_tools


def _image() -> bytes:
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((64, 64, 191, 191), fill=(30, 90, 220))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-external-call",
        action="store_true",
        help="required acknowledgement that this sends one external model request",
    )
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="backward-compatible alias for --confirm-external-call",
    )
    parser.add_argument(
        "--effort",
        default="off",
        help="reasoning effort for this one call (default: off)",
    )
    args = parser.parse_args()
    if not (args.confirm_external_call or args.confirm_paid_call):
        raise SystemExit("refusing external request without --confirm-external-call")

    cfg = LLMConfig.from_env()
    if cfg.backend not in {"anthropic", "openai_responses", "codex"}:
        raise SystemExit(
            "provider smoke supports LLM_BACKEND=anthropic|openai_responses|codex"
        )

    os.environ["ANTHROPIC_THINKING"] = "off"
    os.environ["TYCHO_PROMPT_CACHING"] = "0"
    os.environ["OPENAI_REASONING_CONTINUITY"] = "0"
    os.environ["OPENAI_STATELESS_REASONING"] = "0"
    os.environ.setdefault("LLM_RETRY_BUDGET_S", "30")

    tool = {
        "name": "report_transport_ok",
        "description": "Report that text, image, and tool calling were received.",
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
        },
    }
    reply = chat_tools(
        [{
            "role": "user",
            "content": [
                {"text": "Inspect the attached blue-square test image, then call report_transport_ok."},
                {"image_png": _image()},
            ],
        }],
        [tool],
        cfg,
        system="This is a transport test. Call the provided tool exactly once.",
        max_tokens=256,
        timeout=int(os.environ.get("LLM_HTTP_TIMEOUT", "180")),
        effort=args.effort,
        call_type="provider_smoke",
    )
    calls = reply.get("tool_calls") or []
    ok = any(
        call.get("name") == "report_transport_ok"
        and call.get("input", {}).get("status") == "ok"
        for call in calls
    )
    if not ok:
        print(f"transport response did not contain the expected tool call: {reply}")
        return 1
    print(
        f"PROVIDER SMOKE PASSED: backend={cfg.backend} "
        f"model={cfg.model} usage={reply.get('usage')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
