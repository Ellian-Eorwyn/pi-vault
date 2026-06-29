"""Structured LLM proposal boundary.

The agent does not let model text edit notes directly. Providers return JSON-like
proposals, this module validates them, and deterministic code applies the
approved fields.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .schema import (
    COMMON_PROPERTIES,
    NOTE_TYPES,
    allowed_controlled_values_from_schema,
    allowed_note_types_from_schema,
<<<<<<< Updated upstream
=======
    custom_property_specs,
    definitions_for,
    extra_domains_for,
>>>>>>> Stashed changes
    load_schema,
)


ALLOWED_PROPOSAL_KEYS = {
    "note_type",
    "status",
    "domain",
    "source_kind",
    "parent",
    "related",
    "cover",
    "summary",
    "capture_type",
    "confidence",
    "warnings",
}


@dataclass(frozen=True)
class ProposalValidation:
    valid: bool
    proposal: dict[str, Any]
    errors: list[str]


@dataclass(frozen=True)
class StageValidation:
    valid: bool
    proposal: dict[str, Any]
    errors: list[str]


class ProposalProvider(Protocol):
    def propose(self, *, note_path: Path, note_text: str) -> dict[str, Any]:
        """Return a structured proposal for one note."""

    def propose_stage(
        self,
        *,
        note_path: Path,
        note_text: str,
        stage: str,
        allowed_hubs: list[str] | None = None,
        allowed_folders: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Return a structured proposal for one narrow processing stage."""

    def propose_base_hierarchy(self, *, prompt: str) -> dict[str, Any]:
        """Return optional structured wording for generated Bases dashboards."""

    def propose_property_remap(self, *, prompt: str) -> dict[str, Any]:
        """Return proposed mappings from unapproved property keys to approved ones."""


class JsonFileProposalProvider:
    """Proposal provider backed by a local JSON file."""

    def __init__(self, proposal_file: Path) -> None:
        self.proposal_file = proposal_file

    def propose(self, *, note_path: Path, note_text: str) -> dict[str, Any]:
        del note_path, note_text
        with self.proposal_file.open(encoding="utf-8") as file:
            proposal = json.load(file)
        if not isinstance(proposal, dict):
            raise ValueError("proposal JSON must be an object")
        return proposal

    def propose_stage(
        self,
        *,
        note_path: Path,
        note_text: str,
        stage: str,
        allowed_hubs: list[str] | None = None,
        allowed_folders: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        del stage, allowed_hubs, allowed_folders
        return self.propose(note_path=note_path, note_text=note_text)

    def propose_base_hierarchy(self, *, prompt: str) -> dict[str, Any]:
        del prompt
        with self.proposal_file.open(encoding="utf-8") as file:
            proposal = json.load(file)
        if not isinstance(proposal, dict):
            raise ValueError("proposal JSON must be an object")
        return proposal

    def propose_property_remap(self, *, prompt: str) -> dict[str, Any]:
        del prompt
        with self.proposal_file.open(encoding="utf-8") as file:
            proposal = json.load(file)
        if not isinstance(proposal, dict):
            raise ValueError("proposal JSON must be an object")
        return proposal


class OpenAICompatibleProposalProvider:
    """Proposal provider for OpenAI-compatible chat completion backends."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: int = 120,
        max_input_tokens: int = 64000,
        chars_per_token: int = 4,
        max_input_chars: int | None = None,
        extra_domains: list[str] | None = None,
        extra_note_types: list[str] | None = None,
        extra_source_kinds: list[str] | None = None,
        extra_capture_types: list[str] | None = None,
<<<<<<< Updated upstream
=======
        custom_properties: list[tuple[str, str, str]] | None = None,
        domain_definitions: dict[str, str] | None = None,
        note_type_definitions: dict[str, str] | None = None,
        status_definitions: dict[str, str] | None = None,
        source_kind_definitions: dict[str, str] | None = None,
        capture_type_definitions: dict[str, str] | None = None,
>>>>>>> Stashed changes
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_input_tokens = max_input_tokens
        self.chars_per_token = chars_per_token
        self.max_input_chars = (
            max_input_chars
            if max_input_chars is not None
            else max_input_tokens * chars_per_token
        )
        self.extra_domains = list(extra_domains or [])
        self.extra_note_types = list(extra_note_types or [])
        self.extra_source_kinds = list(extra_source_kinds or [])
        self.extra_capture_types = list(extra_capture_types or [])
<<<<<<< Updated upstream
=======
        self.custom_properties = list(custom_properties or [])
        # Definitions are injected into every classification prompt so the model
        # is aligned on what each controlled value means. They default to the
        # built-in definitions (on by default); provider_from_config overlays the
        # vault's confirmed schema definitions on top.
        self.domain_definitions = (
            dict(DOMAIN_DEFINITIONS) if domain_definitions is None else dict(domain_definitions)
        )
        self.note_type_definitions = (
            {name: spec.get("description", "") for name, spec in NOTE_TYPES.items()}
            if note_type_definitions is None
            else dict(note_type_definitions)
        )
        self.status_definitions = (
            dict(STATUS_DEFINITIONS) if status_definitions is None else dict(status_definitions)
        )
        self.source_kind_definitions = (
            dict(SOURCE_KIND_DEFINITIONS)
            if source_kind_definitions is None
            else dict(source_kind_definitions)
        )
        self.capture_type_definitions = (
            dict(CAPTURE_TYPE_DEFINITIONS)
            if capture_type_definitions is None
            else dict(capture_type_definitions)
        )

    def _definitions(self) -> dict[str, dict[str, str]]:
        """Bundle the per-property definition maps for the prompt builders."""
        return {
            "note_type": self.note_type_definitions,
            "status": self.status_definitions,
            "domain": self.domain_definitions,
            "source_kind": self.source_kind_definitions,
            "capture_type": self.capture_type_definitions,
        }
>>>>>>> Stashed changes

    def propose(self, *, note_path: Path, note_text: str) -> dict[str, Any]:
        prompt = _proposal_prompt(
            note_path=note_path,
            note_text=note_text,
            max_chars=self.max_input_chars,
            extra_domains=self.extra_domains,
            extra_note_types=self.extra_note_types,
            extra_source_kinds=self.extra_source_kinds,
            extra_capture_types=self.extra_capture_types,
        )
        system = (
            "You classify Obsidian notes for vault-agent. "
            "Return exactly one valid JSON object and no prose. "
            "Do not include analysis, reasoning, markdown, or code fences."
        )
        return self._json_completion_with_repair(
            system=system,
            prompt=prompt,
            expected="full vault-agent note classification JSON",
        )

    def propose_stage(
        self,
        *,
        note_path: Path,
        note_text: str,
        stage: str,
        allowed_hubs: list[str] | None = None,
        allowed_folders: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        prompt = _stage_prompt(
            note_path=note_path,
            note_text=note_text,
            stage=stage,
            max_chars=self.max_input_chars,
            allowed_hubs=allowed_hubs,
            allowed_folders=allowed_folders,
            extra_domains=self.extra_domains,
            extra_note_types=self.extra_note_types,
            extra_source_kinds=self.extra_source_kinds,
            extra_capture_types=self.extra_capture_types,
<<<<<<< Updated upstream
=======
            custom_properties=self.custom_properties,
            definitions=self._definitions(),
>>>>>>> Stashed changes
        )
        system = (
            "You perform one narrow Obsidian vault-agent stage. "
            "Return exactly one valid JSON object and no prose. "
            "Do not include analysis, reasoning, markdown, or code fences."
        )
        return self._json_completion_with_repair(
            system=system,
            prompt=prompt,
            expected=f"`{stage}` stage JSON",
        )

    def propose_base_hierarchy(self, *, prompt: str) -> dict[str, Any]:
        system = (
            "You write concise Obsidian dashboard labels and coverage summaries. "
            "Return exactly one valid JSON object and no prose. "
            "Do not include analysis, reasoning, markdown, or code fences."
        )
        return self._json_completion_with_repair(
            system=system,
            prompt=prompt[: self.max_input_chars],
            expected="base hierarchy coverage JSON",
        )

    def propose_property_remap(self, *, prompt: str) -> dict[str, Any]:
        system = (
            "You align Obsidian frontmatter to an approved schema. "
            "Return exactly one valid JSON object and no prose. "
            "Do not include analysis, reasoning, markdown, or code fences."
        )
        return self._json_completion_with_repair(
            system=system,
            prompt=prompt[: self.max_input_chars],
            expected="property remap JSON",
        )

    def _json_completion_with_repair(
        self, *, system: str, prompt: str, expected: str
    ) -> dict[str, Any]:
        attempts: list[dict[str, str]] = []
        content = self._chat_completion(system=system, prompt=prompt)
        try:
            return _parse_json_object(content)
        except ValueError as first_error:
            attempts.append(
                {
                    "phase": "initial",
                    "error": str(first_error),
                    "excerpt": _response_excerpt(content),
                }
            )

        repair_prompt = _repair_prompt(
            original_prompt=prompt,
            invalid_response=content,
            expected=expected,
        )
        repair_content = self._chat_completion(system=system, prompt=repair_prompt)
        try:
            return _parse_json_object(repair_content)
        except ValueError as repair_error:
            attempts.append(
                {
                    "phase": "repair",
                    "error": str(repair_error),
                    "excerpt": _response_excerpt(repair_content),
                }
            )
            failure = {"expected": expected, "attempts": attempts}
            raise ValueError(
                "LLM JSON repair failed: " + json.dumps(failure, sort_keys=True)
            ) from repair_error

    def _chat_completion(self, *, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"LLM request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"LLM request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ValueError("LLM request timed out") from exc

        content = _chat_completion_content(response_payload)
        return content

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class ConfiguredProposalProvider(OpenAICompatibleProposalProvider):
    """Backward-compatible name for configured OpenAI-compatible providers."""


def provider_from_config(config: Any) -> "OpenAICompatibleProposalProvider | None":
    """Build the configured LLM proposal provider, or None when LLM is disabled."""
    if not config.llm_enabled or config.llm_provider in {"", "none"}:
        return None
    if config.llm_provider not in {"openai-compatible", "llama.cpp", "local-openai"}:
        raise ValueError(f"Unsupported LLM provider `{config.llm_provider}`")
    schema = load_schema(config.vault_root)
    builtin_source = set(COMMON_PROPERTIES["source_kind"]["allowed"])
    builtin_capture = set(COMMON_PROPERTIES["capture_type"]["allowed"])
    return OpenAICompatibleProposalProvider(
        base_url=config.llm_base_url,
        model=config.llm_model,
        api_key=config.llm_api_key,
        timeout_seconds=config.llm_timeout_seconds,
        max_input_tokens=config.llm_max_input_tokens,
        chars_per_token=config.llm_chars_per_token,
        max_input_chars=config.llm_max_input_chars,
        extra_domains=list(config.paths.domain_folders),
        extra_note_types=sorted(allowed_note_types_from_schema(schema) - set(NOTE_TYPES)),
        extra_source_kinds=[
            v
            for v in allowed_controlled_values_from_schema(schema, "source_kind")
            if v not in builtin_source
        ],
        extra_capture_types=[
            v
            for v in allowed_controlled_values_from_schema(schema, "capture_type")
            if v not in builtin_capture
        ],
<<<<<<< Updated upstream
=======
        custom_properties=custom_property_specs(schema),
        domain_definitions=definitions_for(schema, "domain"),
        status_definitions=definitions_for(schema, "status"),
        source_kind_definitions=definitions_for(schema, "source_kind"),
        capture_type_definitions=definitions_for(schema, "capture_type"),
        note_type_definitions=note_type_definitions_from_schema(schema),
>>>>>>> Stashed changes
    )


def schema_stage_extras(vault_root: Path) -> dict[str, Any]:
    """Custom note types / controlled values / properties declared in schema.json.

    Returned as keyword args for `validate_stage_proposal` / `validate_proposal` so the
    validators accept schema-defined additions on top of the built-in vocabulary.
    """
    schema = load_schema(vault_root)
    builtin_source = set(COMMON_PROPERTIES["source_kind"]["allowed"])
    builtin_capture = set(COMMON_PROPERTIES["capture_type"]["allowed"])
    return {
        "extra_note_types": sorted(allowed_note_types_from_schema(schema) - set(NOTE_TYPES)),
        "extra_source_kinds": [
            v
            for v in allowed_controlled_values_from_schema(schema, "source_kind")
            if v not in builtin_source
        ],
        "extra_capture_types": [
            v
            for v in allowed_controlled_values_from_schema(schema, "capture_type")
            if v not in builtin_capture
        ],
        "custom_properties": custom_property_specs(schema),
    }


def _allowed_domain_values(extra_domains: list[str] | None) -> list[str]:
    builtin = list(COMMON_PROPERTIES["domain"]["allowed"])
    return builtin + [d for d in (extra_domains or []) if d not in builtin]


def _allowed_note_type_values(extra_note_types: list[str] | None) -> list[str]:
    builtin = sorted(NOTE_TYPES)
    return builtin + sorted(t for t in set(extra_note_types or []) if t and t not in NOTE_TYPES)


def _allowed_controlled_values(property_name: str, extra: list[str] | None) -> list[str]:
    builtin = list(COMMON_PROPERTIES[property_name]["allowed"])
    return builtin + [v for v in (extra or []) if v and v not in builtin]


def _proposal_prompt(
    *,
    note_path: Path,
    note_text: str,
    max_chars: int,
    extra_domains: list[str] | None = None,
    extra_note_types: list[str] | None = None,
    extra_source_kinds: list[str] | None = None,
    extra_capture_types: list[str] | None = None,
) -> str:
    excerpt = note_text[:max_chars]
    truncated = len(note_text) > max_chars
    allowed_types = ", ".join(_allowed_note_type_values(extra_note_types))
    allowed_statuses = ", ".join(COMMON_PROPERTIES["status"]["allowed"])
    allowed_domains = ", ".join(_allowed_domain_values(extra_domains))
    allowed_source_kinds = ", ".join(_allowed_controlled_values("source_kind", extra_source_kinds))
    allowed_capture_types = ", ".join(_allowed_controlled_values("capture_type", extra_capture_types))
    return f"""Classify this Obsidian note and propose only schema-approved metadata.

Allowed note_type values: {allowed_types}
Allowed status values: {allowed_statuses}
Allowed domain values: {allowed_domains}
Allowed source_kind values: {allowed_source_kinds}
Allowed capture_type values: {allowed_capture_types}

Return JSON with exactly these keys:
- note_type: one allowed note type
- status: one allowed status value; use active for currently relevant notes, someday for potential future work, completed for finished retained work, archived for historical or inactive material
- domain: broad stable domain string, or empty string
- source_kind: one allowed source_kind value for source notes, or empty string
- parent: one Obsidian wikilink string if a clear parent exists, or empty string
- related: list of Obsidian wikilink strings for obvious related concepts/entities, or []
- cover: image path/string if clearly present, or empty string
- summary: concise 1-3 sentence note summary, 1000 characters max
- capture_type: one allowed capture_type value if clear, or empty string
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity, sensitive content, or cleanup concerns

Never invent new type or status values. Prefer existing domain values, and create topic notes rather than new domain values. Do not invent specific links. Prefer empty parent/related over guesses.
Do not include markdown fences or explanatory text.

Path: {note_path.as_posix()}
Truncated: {str(truncated).lower()}

Note:
{excerpt}
"""


def _repair_prompt(*, original_prompt: str, invalid_response: str, expected: str) -> str:
    excerpt = invalid_response.replace("\n", " ")[:1000]
    task = original_prompt[:12000]
    return f"""Your previous response was invalid because it was not exactly one JSON object.

Return only the {expected}. Start with `{{` and end with `}}`.
Do not include thinking, analysis, apologies, markdown fences, labels, or prose.

Invalid response excerpt:
{excerpt}

Original task:
{task}
"""


def _stage_prompt(
    *,
    note_path: Path,
    note_text: str,
    stage: str,
    max_chars: int,
    allowed_hubs: list[str] | None = None,
    allowed_folders: list[tuple[str, str]] | None = None,
    extra_domains: list[str] | None = None,
    extra_note_types: list[str] | None = None,
    extra_source_kinds: list[str] | None = None,
    extra_capture_types: list[str] | None = None,
<<<<<<< Updated upstream
=======
    custom_properties: list[tuple[str, str, str]] | None = None,
    definitions: dict[str, dict[str, str]] | None = None,
>>>>>>> Stashed changes
) -> str:
    excerpt = note_text[:max_chars]
    truncated = len(note_text) > max_chars
    allowed_types = ", ".join(_allowed_note_type_values(extra_note_types))
    allowed_statuses = ", ".join(COMMON_PROPERTIES["status"]["allowed"])
    allowed_domains = ", ".join(_allowed_domain_values(extra_domains))
    allowed_source_kinds = ", ".join(_allowed_controlled_values("source_kind", extra_source_kinds))
    allowed_capture_types = ", ".join(_allowed_controlled_values("capture_type", extra_capture_types))
    common = f"""Path: {note_path.as_posix()}
Truncated: {str(truncated).lower()}

Note:
{excerpt}
"""
    if stage == "classify-type":
        return f"""Choose only the note type for this note.

Allowed note_type values: {allowed_types}

Return JSON with exactly these keys:
- note_type: one allowed note type
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity

Do not propose status, domain, parent, related, cover, source_kind, capture_type, summary, headings, or body edits.

{common}"""
    if stage == "property-values":
        custom_lines = ""
        for name, ptype, definition in custom_properties or []:
            hint = (definition or "").strip()
            if ptype == "list":
                custom_lines += f"\n- {name}: list of strings — {hint} (use [] if none apply)"
            else:
                suffix = f" — {hint}" if hint else ""
                custom_lines += f'\n- {name}: free text{suffix} (use "" if not applicable)'
        return f"""Fill only accepted frontmatter property values for this note.

Allowed status values: {allowed_statuses}
Allowed domain values: {allowed_domains}
Allowed source_kind values: {allowed_source_kinds}
Allowed capture_type values: {allowed_capture_types}

Return JSON with exactly these keys:
- status: one allowed status value
- domain: broad stable domain string, or empty string
- source_kind: one allowed source_kind value for source notes, or empty string
- parent: one Obsidian wikilink string if a clear parent exists, or empty string
- related: list of Obsidian wikilink strings for obvious related concepts/entities, or []
- cover: image path/string if clearly present, or empty string
- capture_type: one allowed capture_type value if clear, or empty string{custom_lines}
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity

Do not propose note_type, summary, headings, or body edits.
Prefer existing domain values. For project, source, meeting, and task notes, provide a clear parent wikilink when one exists. For person notes, use `[[Contacts]]` for a direct contact or conversation participant and `[[Authors]]` for an author or cited thinker. If both apply, use `[[Contacts]]` as parent and include `[[Authors]]` in related. Prefer empty related over other invented links.

{common}"""
    if stage == "summary":
        return f"""Write only a concise summary for this note.

Return JSON with exactly these keys:
- summary: concise 1-3 sentence note summary, 1000 characters max
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity

Do not propose frontmatter, type, property values, headings, or other body edits.

{common}"""
    if stage == "assign-hub":
        hub_list = ", ".join(allowed_hubs or []) or "(none defined for this domain)"
        return f"""Assign this note to exactly one approved topic hub for its domain, or none.

Approved hubs: {hub_list}

Return JSON with exactly these keys:
- parent: one hub name from the approved list (no brackets), or empty string if none fits
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity

Choose only from the approved hubs. Never invent a hub. Use the note's title, content, and
folder location as signals. Do not propose type, status, domain, summary, headings, or body edits.

{common}"""
    if stage == "refine-body":
        return f"""Improve only the structure and Obsidian Markdown formatting of this note body.

Return JSON with exactly these keys:
- body: the full reformatted note body as a single Markdown string, with no YAML frontmatter
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity or content you could not safely keep intact

You may add or adjust headings, lists, bold/italic emphasis, callouts, blockquotes, tables,
code fences, and whitespace so the note is easier to skim and better structured. You may add
short structural heading labels.

Hard rules, never break them:
- Do not add, remove, reword, paraphrase, translate, correct, summarize, or reorder the meaning
  of any sentence. Reuse the author's exact words.
- Do not invent new claims, facts, links, or content. Do not fix spelling or grammar.
- Markdown structural tokens and short heading labels are the only text you may add.
- Preserve all existing wikilinks, URLs, and inline references verbatim.
- Return the body only; do not include frontmatter, type, status, or other property edits.

{common}"""
    if stage == "classify-person":
        return f"""Classify a person mentioned in this vault and draft only grounded details.

The Path below is the person's name; the Note below lists how they are mentioned.

Return JSON with exactly these keys:
- kind: "contact" if this is someone the author interacts with directly (met, spoke, emailed, a meeting or conversation participant); "author" if this is a writer, researcher, or cited thinker referenced through their work
- details: 1-4 short Markdown lines stating only facts present in the mentions (role, organization, relationship). Use an empty string if nothing concrete is stated.
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity or thin evidence

Never invent biography, contact information, affiliations, or links that are not present in the mentions below.

{common}"""
    if stage == "assign-folder":
        if allowed_folders:
            folder_lines = "\n".join(
                f"- {path}: {description}" if description else f"- {path}"
                for path, description in allowed_folders
            )
        else:
            folder_lines = "(no custom folders defined)"
        return f"""Assign this note to exactly one of the folders below, or none.

Available folders (path: description):
{folder_lines}

Return JSON with exactly these keys:
- folder: one folder path exactly as listed above, or empty string if none fits
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity

Choose only from the listed folder paths. Never invent a folder. Use the note's title, content,
and each folder's description as signals. Do not propose type, status, domain, summary, or body edits.

{common}"""
    raise ValueError(f"unsupported LLM stage `{stage}`")


def _chat_completion_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response did not include choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("LLM response did not include a message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response message content was empty")
    return content


def _response_excerpt(content: str) -> str:
    return content.replace("\n", " ")[:300]


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    json_text = _first_balanced_json_object(cleaned)
    if json_text is None:
        excerpt = cleaned.replace("\n", " ")[:160]
        raise ValueError(f"LLM response did not contain a JSON object: {excerpt}")
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def _first_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def validate_proposal(
    proposal: dict[str, Any],
    *,
    extra_domains: list[str] | None = None,
    extra_note_types: list[str] | None = None,
    extra_source_kinds: list[str] | None = None,
    extra_capture_types: list[str] | None = None,
    custom_properties: list[tuple[str, str, str]] | None = None,
) -> ProposalValidation:
    # custom_properties is accepted so schema_stage_extras can be spread uniformly;
    # the monolithic classification path does not surface custom properties.
    del custom_properties
    errors: list[str] = []
    unknown = sorted(set(proposal) - ALLOWED_PROPOSAL_KEYS)
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))

    note_type = proposal.get("note_type")
    allowed_types = set(_allowed_note_type_values(extra_note_types))
    if not isinstance(note_type, str) or not note_type:
        errors.append("note_type is required")
    elif note_type not in allowed_types:
        errors.append(f"unknown note_type `{note_type}`")

    status = proposal.get("status", "active")
    allowed_statuses = COMMON_PROPERTIES["status"]["allowed"]
    if not isinstance(status, str) or status not in allowed_statuses:
        errors.append(f"status must be one of: {', '.join(allowed_statuses)}")

    summary = proposal.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("summary is required")
    elif len(summary) > 1000:
        errors.append("summary must be 1000 characters or fewer")

    _validate_optional_string(proposal, "domain", errors)
    _validate_allowed_domain(proposal, errors, extra_domains)
    _validate_optional_string(proposal, "source_kind", errors)
    _validate_allowed_source_kind(proposal, errors, extra_source_kinds)
    _validate_optional_string(proposal, "capture_type", errors)
    _validate_allowed_capture_type(proposal, errors, extra_capture_types)
    _validate_optional_string(proposal, "parent", errors)
    _validate_string_list(proposal, "related", errors)
    _validate_optional_string(proposal, "cover", errors)
    _validate_string_list(proposal, "warnings", errors)

    confidence = proposal.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1
    ):
        errors.append("confidence must be a number between 0 and 1")

    normalized = {
        "note_type": note_type,
        "status": status,
        "domain": proposal.get("domain", ""),
        "source_kind": proposal.get("source_kind", ""),
        "capture_type": proposal.get("capture_type", ""),
        "parent": proposal.get("parent", ""),
        "related": proposal.get("related", []),
        "cover": proposal.get("cover", ""),
        "summary": summary.strip() if isinstance(summary, str) else summary,
        "confidence": confidence,
        "warnings": proposal.get("warnings", []),
    }
    return ProposalValidation(not errors, normalized, errors)


def validate_stage_proposal(
    stage: str,
    proposal: dict[str, Any],
    *,
    allowed_hubs: list[str] | None = None,
    allowed_folders: list[str] | None = None,
    extra_domains: list[str] | None = None,
    extra_note_types: list[str] | None = None,
    extra_source_kinds: list[str] | None = None,
    extra_capture_types: list[str] | None = None,
    custom_properties: list[tuple[str, str, str]] | None = None,
) -> StageValidation:
    if stage == "classify-type":
        return _validate_type_stage(proposal, extra_note_types)
    if stage == "property-values":
        return _validate_property_values_stage(
            proposal, extra_domains, extra_source_kinds, extra_capture_types, custom_properties
        )
    if stage == "summary":
        return _validate_summary_stage(proposal)
    if stage == "refine-body":
        return _validate_refine_body_stage(proposal)
    if stage == "classify-person":
        return _validate_classify_person_stage(proposal)
    if stage == "assign-hub":
        return _validate_assign_hub_stage(proposal, allowed_hubs or [])
    if stage == "assign-folder":
        return _validate_assign_folder_stage(proposal, allowed_folders or [])
    return StageValidation(False, {}, [f"unknown stage `{stage}`"])


def _validate_assign_folder_stage(
    proposal: dict[str, Any], allowed_folders: list[str]
) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"folder", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    raw = proposal.get("folder", "")
    folder = raw.strip() if isinstance(raw, str) else ""
    if folder and folder not in allowed_folders:
        errors.append(f"folder `{folder}` is not one of the declared custom folders")
    _validate_string_list(proposal, "warnings", errors)
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "folder": folder,
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_assign_hub_stage(
    proposal: dict[str, Any], allowed_hubs: list[str]
) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"parent", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    raw = proposal.get("parent", "")
    parent = raw.strip() if isinstance(raw, str) else ""
    # Accept "[[Hub]]" or bare "Hub"; resolve to the canonical approved hub name.
    bare = parent[2:-2].strip() if parent.startswith("[[") and parent.endswith("]]") else parent
    resolved = ""
    if bare:
        lookup = {hub.lower(): hub for hub in allowed_hubs}
        if bare.lower() in lookup:
            resolved = lookup[bare.lower()]
        else:
            errors.append(f"parent `{bare}` is not an approved hub for this domain")
    _validate_string_list(proposal, "warnings", errors)
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "parent": f"[[{resolved}]]" if resolved else "",
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_type_stage(
    proposal: dict[str, Any], extra_note_types: list[str] | None = None
) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"note_type", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    allowed_types = _allowed_note_type_values(extra_note_types)
    note_type = proposal.get("note_type")
    if not isinstance(note_type, str) or note_type not in set(allowed_types):
        errors.append(f"note_type must be one of: {', '.join(allowed_types)}")
    confidence = _validate_confidence(proposal, errors)
    _validate_string_list(proposal, "warnings", errors)
    return StageValidation(
        not errors,
        {
            "note_type": note_type,
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_property_values_stage(
    proposal: dict[str, Any],
    extra_domains: list[str] | None = None,
    extra_source_kinds: list[str] | None = None,
    extra_capture_types: list[str] | None = None,
    custom_properties: list[tuple[str, str, str]] | None = None,
) -> StageValidation:
    errors: list[str] = []
    custom = custom_properties or []
    custom_names = {name for name, _type, _def in custom}
    allowed_keys = {
        "status", "domain", "parent", "related", "cover", "source_kind",
        "capture_type", "confidence", "warnings",
    } | custom_names
    unknown = sorted(set(proposal) - allowed_keys)
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    status = proposal.get("status", "active")
    allowed_statuses = COMMON_PROPERTIES["status"]["allowed"]
    if not isinstance(status, str) or status not in allowed_statuses:
        errors.append(f"status must be one of: {', '.join(allowed_statuses)}")
    _validate_optional_string(proposal, "domain", errors)
    _validate_allowed_domain(proposal, errors, extra_domains)
    _validate_optional_string(proposal, "source_kind", errors)
    _validate_allowed_source_kind(proposal, errors, extra_source_kinds)
    _validate_optional_string(proposal, "capture_type", errors)
    _validate_allowed_capture_type(proposal, errors, extra_capture_types)
    _validate_optional_string(proposal, "parent", errors)
    _validate_string_list(proposal, "related", errors)
    _validate_optional_string(proposal, "cover", errors)
    _validate_string_list(proposal, "warnings", errors)
    custom_values: dict[str, Any] = {}
    for name, ptype, _definition in custom:
        if ptype == "list":
            _validate_string_list(proposal, name, errors)
            custom_values[name] = proposal.get(name, [])
        else:
            _validate_optional_string(proposal, name, errors)
            custom_values[name] = proposal.get(name, "")
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "status": status,
            "domain": proposal.get("domain", ""),
            "source_kind": proposal.get("source_kind", ""),
            "capture_type": proposal.get("capture_type", ""),
            "parent": proposal.get("parent", ""),
            "related": proposal.get("related", []),
            "cover": proposal.get("cover", ""),
            **custom_values,
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_summary_stage(proposal: dict[str, Any]) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"summary", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    summary = proposal.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("summary is required")
    elif len(summary) > 1000:
        errors.append("summary must be 1000 characters or fewer")
    _validate_string_list(proposal, "warnings", errors)
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "summary": summary.strip() if isinstance(summary, str) else summary,
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_classify_person_stage(proposal: dict[str, Any]) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"kind", "details", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    kind = proposal.get("kind")
    if kind not in ("contact", "author"):
        errors.append("kind must be `contact` or `author`")
    details = proposal.get("details", "")
    if not isinstance(details, str):
        errors.append("details must be a string")
    _validate_string_list(proposal, "warnings", errors)
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "kind": kind if kind in ("contact", "author") else "",
            "details": details if isinstance(details, str) else "",
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_refine_body_stage(proposal: dict[str, Any]) -> StageValidation:
    errors: list[str] = []
    unknown = sorted(set(proposal) - {"body", "confidence", "warnings"})
    if unknown:
        errors.append("unknown proposal keys: " + ", ".join(unknown))
    body = proposal.get("body")
    if not isinstance(body, str) or not body.strip():
        errors.append("body is required")
    _validate_string_list(proposal, "warnings", errors)
    confidence = _validate_confidence(proposal, errors)
    return StageValidation(
        not errors,
        {
            "body": body if isinstance(body, str) else "",
            "confidence": confidence,
            "warnings": proposal.get("warnings", []),
        },
        errors,
    )


def _validate_string_list(
    proposal: dict[str, Any], key: str, errors: list[str]
) -> None:
    value = proposal.get(key, [])
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{key} must contain only non-empty strings")


def _validate_optional_string(
    proposal: dict[str, Any], key: str, errors: list[str]
) -> None:
    value = proposal.get(key, "")
    if not isinstance(value, str):
        errors.append(f"{key} must be a string")


def _validate_allowed_domain(
    proposal: dict[str, Any], errors: list[str], extra_domains: list[str] | None = None
) -> None:
    value = proposal.get("domain", "")
    allowed_domains = _allowed_domain_values(extra_domains)
    if isinstance(value, str) and value not in allowed_domains:
        errors.append(f"domain must be one of: {', '.join(allowed_domains)}")


def _validate_allowed_source_kind(
    proposal: dict[str, Any], errors: list[str], extra_source_kinds: list[str] | None = None
) -> None:
    value = proposal.get("source_kind", "")
    allowed_source_kinds = _allowed_controlled_values("source_kind", extra_source_kinds)
    if isinstance(value, str) and value not in allowed_source_kinds:
        errors.append(f"source_kind must be one of: {', '.join(allowed_source_kinds)}")


def _validate_allowed_capture_type(
    proposal: dict[str, Any], errors: list[str], extra_capture_types: list[str] | None = None
) -> None:
    value = proposal.get("capture_type", "")
    allowed_capture_types = _allowed_controlled_values("capture_type", extra_capture_types)
    if isinstance(value, str) and value not in allowed_capture_types:
        errors.append(f"capture_type must be one of: {', '.join(allowed_capture_types)}")


def _validate_confidence(proposal: dict[str, Any], errors: list[str]) -> float | None:
    confidence = proposal.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1
    ):
        errors.append("confidence must be a number between 0 and 1")
    return confidence
