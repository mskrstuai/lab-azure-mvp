"""Helpers for parsing ``variables.tf`` and emitting ``terraform.tfvars.json``.

Light-weight HCL parser — handles the common ``variable "..." { ... }``
shape used by the v2 generator.  Supports scalar defaults (string/number/
bool), map/object defaults, and list defaults.  Falls back to raw text
when the default doesn't match a known shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _find_matching_brace(s: str, start: int) -> int:
    """Return the index *after* the closing brace that matches the open brace at ``start-1``."""
    depth = 1
    i = start
    in_str = False
    while i < len(s) and depth > 0:
        ch = s[i]
        if ch == '"' and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        i += 1
    return i  # index after the matching '}'


def _find_matching_bracket(s: str, start: int) -> int:
    depth = 1
    i = start
    in_str = False
    while i < len(s) and depth > 0:
        ch = s[i]
        if ch == '"' and (i == 0 or s[i - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
        i += 1
    return i


def _extract_default(block: str) -> Optional[Dict[str, Any]]:
    """Pull the ``default = ...`` value from a variable block.

    Returns:
        { 'kind': 'string'|'number'|'bool'|'map'|'list'|'unknown', 'value': ..., 'raw': str }
        or None if no default.
    """
    m = re.search(r"\bdefault\s*=\s*", block)
    if not m:
        return None
    rest = block[m.end():].lstrip()
    if not rest:
        return None
    first = rest[0]

    # Map / object  →  {...}
    if first == "{":
        end = _find_matching_brace(rest, 1)
        raw = rest[:end]
        # Best-effort: convert simple key-value pairs into a JSON dict
        inner = raw[1:-1].strip()
        d: Dict[str, str] = {}
        for pair in re.finditer(r"(\w+)\s*=\s*\"([^\"]*)\"", inner):
            d[pair.group(1)] = pair.group(2)
        return {"kind": "map", "value": d, "raw": raw}

    # List  →  [...]
    if first == "[":
        end = _find_matching_bracket(rest, 1)
        raw = rest[:end]
        items = re.findall(r"\"([^\"]*)\"", raw)
        return {"kind": "list", "value": items, "raw": raw}

    # String  →  "..."
    if first == '"':
        m2 = re.match(r'"((?:\\.|[^"\\])*)"', rest)
        if m2:
            return {"kind": "string", "value": m2.group(1), "raw": m2.group(0)}

    # Boolean / number / null
    m3 = re.match(r"(true|false|null|-?\d+(?:\.\d+)?)\b", rest)
    if m3:
        token = m3.group(1)
        if token in ("true", "false"):
            return {"kind": "bool", "value": token == "true", "raw": token}
        if token == "null":
            return {"kind": "unknown", "value": None, "raw": token}
        return {"kind": "number", "value": float(token) if "." in token else int(token), "raw": token}

    # Fallback
    end = rest.find("\n")
    raw = rest[:end].rstrip() if end > 0 else rest.strip()
    return {"kind": "unknown", "value": raw, "raw": raw}


def parse_variables_tf(content: str) -> List[Dict[str, Any]]:
    """Extract ``variable "<name>" { ... }`` blocks.

    Each entry has::
        { name, description, type, sensitive, default, default_kind }
    """
    out: List[Dict[str, Any]] = []
    for match in re.finditer(r'variable\s+"([^"]+)"\s*\{', content):
        name = match.group(1)
        body_start = match.end()
        body_end = _find_matching_brace(content, body_start)
        block = content[body_start:body_end - 1]   # strip the closing brace

        var: Dict[str, Any] = {"name": name}
        desc_m = re.search(r'description\s*=\s*"((?:\\.|[^"\\])*)"', block)
        if desc_m:
            var["description"] = desc_m.group(1)

        type_m = re.search(r'type\s*=\s*([^\n]+)', block)
        if type_m:
            var["type"] = type_m.group(1).strip()

        sens_m = re.search(r'sensitive\s*=\s*(true|false)', block)
        if sens_m:
            var["sensitive"] = sens_m.group(1) == "true"

        default = _extract_default(block)
        if default:
            var["default"]      = default["value"]
            var["default_kind"] = default["kind"]
            var["default_raw"]  = default["raw"]
        else:
            var["default"] = None
            var["default_kind"] = "none"

        out.append(var)
    return out


def write_tfvars_json(work_dir: Path, tfvars: Dict[str, Any]) -> Optional[Path]:
    """Write ``terraform.tfvars.json`` (Terraform auto-loads it).

    Returns the file path or None if no tfvars supplied.
    """
    if not tfvars:
        return None
    path = work_dir / "terraform.tfvars.json"
    path.write_text(json.dumps(tfvars, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
