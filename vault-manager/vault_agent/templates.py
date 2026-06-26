"""Template application helpers."""

from __future__ import annotations

from pathlib import Path

from .paths import paths_for
from .schema import NOTE_TYPES, template_for


def _template_text(note_type: str, vault_root: Path | None) -> str | None:
    """Return the full template text for a note type.

    Built-in types use the bundled `TEMPLATE_BODIES`; custom (schema-defined) types
    fall back to their on-disk template `<template_dir>/note-types/<type>.md`.
    """
    if note_type in NOTE_TYPES:
        return template_for(note_type, NOTE_TYPES[note_type]["description"])
    if vault_root is not None and note_type:
        path = vault_root / paths_for(vault_root).template_dir / "note-types" / f"{note_type}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return None


def template_headings(note_type: str, *, vault_root: Path | None = None) -> list[str]:
    """Return second-level headings from the starter template for a note type."""
    return [section["heading"] for section in template_sections(note_type, vault_root=vault_root)]


def append_missing_headings(
    body: str, note_type: str, *, vault_root: Path | None = None
) -> tuple[str, list[str]]:
    """Append full template sections for missing second-level headings.

    Existing note text and sections are preserved exactly. Only sections whose
    `##` heading is absent are appended from the template body. Returns the body
    unchanged when no template is available (e.g. an unknown custom type).
    """
    existing = {line.strip() for line in body.splitlines() if line.startswith("## ")}
    missing_sections = [
        section
        for section in template_sections(note_type, vault_root=vault_root)
        if section["heading"] not in existing
    ]
    if not missing_sections:
        return body, []
    section_text = "\n\n".join(section["body"].rstrip() for section in missing_sections)
    new_body = body.rstrip() + "\n\n" + section_text + "\n"
    return new_body, [section["heading"] for section in missing_sections]


def template_sections(
    note_type: str, *, vault_root: Path | None = None
) -> list[dict[str, str]]:
    """Return full second-level sections from the template, or [] when none exists."""
    template = _template_text(note_type, vault_root)
    if template is None:
        return []
    lines = template.splitlines()
    sections: list[dict[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_heading is not None:
                sections.append(
                    {
                        "heading": current_heading,
                        "body": "\n".join(current_lines).rstrip(),
                    }
                )
            current_heading = line.strip()
            current_lines = [line]
        elif current_heading is not None:
            if line.startswith("<!-- "):
                continue
            current_lines.append(line)
    if current_heading is not None:
        sections.append(
            {
                "heading": current_heading,
                "body": "\n".join(current_lines).rstrip(),
            }
        )
    return sections
