"""Template application helpers."""

from __future__ import annotations

from .schema import NOTE_TYPES, template_for


def template_headings(note_type: str) -> list[str]:
    """Return second-level headings from the starter template for a note type."""
    spec = NOTE_TYPES[note_type]
    template = template_for(note_type, spec["description"])
    headings: list[str] = []
    for line in template.splitlines():
        if line.startswith("## "):
            headings.append(line.strip())
    return headings


def append_missing_headings(body: str, note_type: str) -> tuple[str, list[str]]:
    """Append full template sections for missing second-level headings.

    Existing note text and sections are preserved exactly. Only sections whose
    `##` heading is absent are appended from the starter template body.
    """
    existing = {line.strip() for line in body.splitlines() if line.startswith("## ")}
    missing_sections = [
        section
        for section in template_sections(note_type)
        if section["heading"] not in existing
    ]
    if not missing_sections:
        return body, []
    section_text = "\n\n".join(section["body"].rstrip() for section in missing_sections)
    new_body = body.rstrip() + "\n\n" + section_text + "\n"
    return new_body, [section["heading"] for section in missing_sections]


def template_sections(note_type: str) -> list[dict[str, str]]:
    """Return full second-level sections from the starter template."""
    spec = NOTE_TYPES[note_type]
    template = template_for(note_type, spec["description"])
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
