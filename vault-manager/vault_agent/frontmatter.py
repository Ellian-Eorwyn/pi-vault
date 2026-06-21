"""YAML frontmatter parsing and canonical rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from .schema import CORE_PROPERTY_ORDER


@dataclass(frozen=True)
class ParsedNote:
    frontmatter: dict[str, Any]
    body: str
    has_frontmatter: bool
    error: str | None = None


def parse_note(text: str) -> ParsedNote:
    if not text.startswith("---\n"):
        return ParsedNote({}, text, False)
    end = text.find("\n---\n", 4)
    if end == -1:
        return ParsedNote({}, text, True, "frontmatter block is not closed")
    raw = text[4:end]
    body = text[end + 5 :]
    try:
        loaded = yaml.safe_load(raw) if raw.strip() else {}
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            return ParsedNote({}, body, True, "frontmatter must be a mapping")
        return ParsedNote(dict(loaded), body, True)
    except (yaml.YAMLError, ValueError) as exc:
        # PyYAML raises ValueError (not YAMLError) when constructing out-of-range
        # timestamps such as `0000-01-01`; treat any such note as malformed
        # frontmatter so one bad note cannot break a whole-vault scan.
        return ParsedNote({}, body, True, str(exc))


def render_note(
    frontmatter: dict[str, Any],
    body: str,
    *,
    property_order: tuple[str, ...] = CORE_PROPERTY_ORDER,
) -> str:
    lines = ["---"]
    for key in _ordered_keys(frontmatter, property_order):
        lines.append(f"{key}: {_format_value(frontmatter[key])}")
    lines.extend(["---", ""])
    return "\n".join(lines) + body.lstrip("\n")


def _ordered_keys(frontmatter: dict[str, Any], property_order: tuple[str, ...]) -> list[str]:
    ordered = [key for key in property_order if key in frontmatter]
    ordered.extend(sorted(key for key in frontmatter if key not in property_order))
    return ordered


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    return _format_scalar(value)


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "":
        return ""
    if (
        any(char in text for char in "[]{}:,#\\")
        or text.strip() != text
        or text[0] in "*&!|>@`'\"%-?"
    ):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text
