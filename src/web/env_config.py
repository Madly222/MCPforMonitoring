"""Safe read/write of the project's .env file for the superadmin console.

The .env values are read by various modules at import time, so editing them from
the web takes effect after a service restart. Writing preserves the file exactly:
comments, blank lines, spacing and inline comments are untouched — only the value
token of a changed key is replaced. Secret-looking keys are masked on read and
only overwritten when a non-empty value is supplied.
"""

import re
from pathlib import Path
from typing import Optional

from loguru import logger

from src.core.config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"

# KEY=VALUE line (allows leading spaces, spaces around '='); ignores comments.
_LINE_RE = re.compile(r'^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$')

# Keys whose values must never be shown in the UI (masked on read).
_SECRET_SUBSTR = ("PASSWORD", "PASS", "TOKEN", "SECRET", "APIKEY", "API_KEY")


def is_secret_key(key: str) -> bool:
    up = key.upper()
    return any(s in up for s in _SECRET_SUBSTR) or up.endswith("_KEY")


def _split_value_comment(rest: str):
    """Split the part after '=' into (value, inline_comment).

    An inline comment starts at the first ' #' (whitespace then '#') that is not
    inside quotes. The value keeps no trailing whitespace; the comment (including
    its leading whitespace) is preserved verbatim for round-tripping.
    """
    in_single = in_double = False
    for i, ch in enumerate(rest):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and i > 0 and rest[i - 1] in " \t":
            # comment starts here; back up over the whitespace that precedes it
            j = i
            while j > 0 and rest[j - 1] in " \t":
                j -= 1
            return rest[:j], rest[j:]
    return rest.rstrip(), ""


def read_env() -> list[dict]:
    """Return the active KEY=VALUE entries in file order.

    Each item: {key, value, secret}. Secret values are returned empty (masked);
    the UI shows them as 'set but hidden'.
    """
    if not ENV_PATH.exists():
        return []
    entries = []
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        key = m.group(2)
        value, _ = _split_value_comment(m.group(4))
        secret = is_secret_key(key)
        entries.append({
            "key": key,
            "value": "" if secret else value.strip('"').strip("'"),
            "secret": secret,
            "has_value": bool(value),
        })
    return entries


def write_env(updates: dict) -> int:
    """Apply {key: value} updates to .env, preserving everything else verbatim.

    Only lines whose key is in `updates` are rewritten (value token swapped,
    indent/'='-spacing/inline-comment kept). Keys not present in the file are
    appended. Returns the number of keys written.
    """
    updates = {k: v for k, v in (updates or {}).items() if v is not None}
    if not updates:
        return 0
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env not found at {ENV_PATH}")

    original = ENV_PATH.read_text(encoding="utf-8")
    had_trailing_nl = original.endswith("\n")
    lines = original.splitlines()
    seen = set()
    out = []
    for line in lines:
        m = _LINE_RE.match(line)
        if m and m.group(2) in updates:
            key = m.group(2)
            _, comment = _split_value_comment(m.group(4))
            new_value = str(updates[key])
            sep = "  " if comment else ""
            out.append(f"{m.group(1)}{key}{m.group(3)}{new_value}{sep}{comment}".rstrip())
            seen.add(key)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    text = "\n".join(out) + ("\n" if had_trailing_nl else "")
    tmp = ENV_PATH.with_suffix(ENV_PATH.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ENV_PATH)
    logger.info(f".env updated: {', '.join(sorted(seen | (set(updates) - seen)))}")
    return len(updates)
