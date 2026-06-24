#!/usr/bin/env python3
"""
Claude API diagnostic.

Checks whether the configured Claude API key and model actually work, and prints
the exact error if they don't. Run from the project root:

    python scripts/check_claude.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import get_config


def main():
    print("=" * 60)
    print("Claude API diagnostic")
    print("=" * 60)

    secrets = get_config().load_secrets()
    api_key = secrets.claude.api_key or ""
    model = secrets.claude.model

    if not api_key:
        print("RESULT: FAIL — no api_key set in secrets.yaml > claude.api_key")
        sys.exit(1)

    masked = api_key[:10] + "..." + api_key[-4:] if len(api_key) > 16 else "(short)"
    print(f"API key : {masked}")
    print(f"Model   : {model}")
    print("-" * 60)
    print("Sending a minimal test request...")

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        print(f"RESULT: SUCCESS — Claude replied: {text.strip()!r}")
        print(f"Tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
    except Exception as e:
        print(f"RESULT: FAIL — {type(e).__name__}: {e}")
        print("-" * 60)
        msg = str(e).lower()
        if "authentication" in msg or "401" in msg or "invalid x-api-key" in msg:
            print("Diagnosis: the API key is invalid, revoked, or mistyped.")
            print("Fix: generate a new key at https://console.anthropic.com/ "
                  "and update secrets.yaml > claude.api_key")
        elif "model" in msg or "404" in msg or "not_found" in msg:
            print(f"Diagnosis: the model '{model}' may be wrong or deprecated.")
            print("Fix: set a current model in secrets.yaml > claude.model")
        elif "credit" in msg or "billing" in msg or "quota" in msg or "429" in msg:
            print("Diagnosis: out of credits / rate limited / billing issue.")
            print("Fix: check usage and billing at https://console.anthropic.com/")
        else:
            print("Diagnosis: see the error above (network, library version, etc.).")
        sys.exit(1)


if __name__ == "__main__":
    main()
