"""A small YAML subset, enough for routing.yaml and budget.yaml.

Supported: nested mappings, lists of scalars, lists of mappings, inline
`[a, b]` lists, quoted strings, comments, and the scalar forms true/false/null
and numbers. Anchors, multi-line strings, flow mappings and merge keys are
rejected with a clear error rather than guessed at.

This exists so the selector stays standard-library only. It is not a general
YAML parser and must not grow into one: the files it reads are the files this
package writes, plus a human's edits within the same shapes.
"""

from __future__ import annotations

import re
from typing import Any


class YamlError(ValueError):
    """The text is outside the supported subset."""


def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if (text[0] == text[-1]) and text[0] in "\"'" and len(text) >= 2:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        body = text[1:-1].strip()
        if not body:
            return []
        return [_scalar(part) for part in _split_flow(body)]
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    if re.fullmatch(r"[+-]?\d+\.\d+", text):
        return float(text)
    return text


def _split_flow(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if quote:
        raise YamlError("unterminated quote in inline list")
    if current:
        parts.append("".join(current).strip())
    return parts


def loads(text: str) -> Any:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise YamlError("indent with spaces, not tabs")
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if not lines:
        return {}
    value, index = _block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError(f"unexpected content on line {index + 1}")
    return value


def _block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if lines[index][1].startswith("- "):
        return _list(lines, index, indent)
    return _mapping(lines, index, indent)


def _mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent and not lines[index][1].startswith("- "):
        content = lines[index][1]
        key, sep, rest = content.partition(":")
        if not sep:
            raise YamlError(f"expected 'key: value', got {content!r}")
        name = _unquote(key.strip())
        rest = rest.strip()
        index += 1
        if rest:
            result[name] = _scalar(rest)
            continue
        if index < len(lines) and lines[index][0] > indent:
            result[name], index = _block(lines, index, lines[index][0])
        else:
            result[name] = None
    return result, index


def _list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
        rest = lines[index][1][2:].strip()
        index += 1
        if not rest:
            if index < len(lines) and lines[index][0] > indent:
                value, index = _block(lines, index, lines[index][0])
                result.append(value)
            else:
                result.append(None)
            continue
        if ":" in rest and not rest.startswith(("[", "\"", "'")):
            key, _, value = rest.partition(":")
            item: dict[str, Any] = {_unquote(key.strip()): _scalar(value.strip())}
            if index < len(lines) and lines[index][0] > indent:
                more, index = _mapping(lines, index, lines[index][0])
                item.update(more)
            result.append(item)
            continue
        result.append(_scalar(rest))
    return result, index


def dumps(value: Any) -> str:
    lines: list[str] = []
    _emit(value, lines, 0)
    return "\n".join(lines) + "\n"


def _emit(value: Any, lines: list[str], indent: int) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            name = _key(key)
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{name}:")
                _emit(item, lines, indent + 1)
            else:
                lines.append(f"{pad}{name}: {_scalar_out(item)}")
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item:
                first = True
                for key, sub in item.items():
                    marker = "- " if first else "  "
                    name = _key(key)
                    if isinstance(sub, (dict, list)) and sub:
                        lines.append(f"{pad}{marker}{name}:")
                        _emit(sub, lines, indent + 1 + (0 if first else 1))
                    else:
                        lines.append(f"{pad}{marker}{name}: {_scalar_out(sub)}")
                    first = False
            else:
                lines.append(f"{pad}- {_scalar_out(item)}")
        return
    lines.append(f"{pad}{_scalar_out(value)}")


def _key(key: Any) -> str:
    text = str(key)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", text) and not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def _scalar_out(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{},]|^\s|\s$", text):
        return '"' + text.replace('"', '\\"') + '"'
    return text