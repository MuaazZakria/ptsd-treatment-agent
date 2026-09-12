"""
JSON repair / extraction — verbatim port of the two helpers in
iaso-ptsd-agent/iaso/llm.py. Used only as the fallback path when Manus's
structured-output extraction is missing and we have to salvage a JSON object
from the final assistant message.
"""

from __future__ import annotations

import json
import re
from typing import Any


def repair_json(text: str) -> str:
    """Close unterminated strings and brackets so truncated output still parses."""
    stack: list[str] = []
    in_str = esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    out = text
    if in_str:
        out += '"'
    out = re.sub(r"[,\s]+$", "", out)
    out = re.sub(r',\s*"[^"]*"\s*:\s*$', "", out)
    out = re.sub(r'\{\s*"[^"]*"\s*:\s*$', "{", out)
    for ch in reversed(stack):
        out += "}" if ch == "{" else "]"
    out = re.sub(r",\s*([}\]])", r"\1", out)
    return out


def extract_json(text: str, *, allow_repair: bool = True) -> dict[str, Any]:
    if not text or not str(text).strip():
        raise ValueError("empty content")
    text = re.sub(r"^```(?:json)?\s*", "", str(text).strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(text[a : b + 1])
        except json.JSONDecodeError:
            pass

    if allow_repair and a >= 0:
        try:
            return json.loads(repair_json(text[a:]))
        except json.JSONDecodeError:
            pass

    raise ValueError("could not parse JSON:\n" + text[:1200])
