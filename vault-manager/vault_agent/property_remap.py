"""Model-driven remapping of unapproved frontmatter properties.

Scans the vault for frontmatter keys outside the approved schema (and not already
covered by a legacy alias), asks the model to map each to the closest approved
property — or drop it — then builds a reviewable proposal that (a) records the
approved mappings as reusable aliases in config and (b) realigns existing notes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import AgentConfig
from .legacy import _normalize_property_value
from .llm import ProposalProvider
from .scanner import scan_vault
from .schema import (
    COMMON_PROPERTIES,
    load_schema,
    property_definitions_for,
    property_order_from_schema,
)

_MAX_SAMPLES = 5


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "remap"


def scan_unknown_properties(
    config: AgentConfig, schema: dict[str, Any]
) -> dict[str, list[tuple[str, Any]]]:
    """Map each unapproved (and un-aliased) frontmatter key to ``(path, value)`` samples."""
    approved = set(property_order_from_schema(schema))
    aliased = set(config.legacy_property_aliases)
    unknown: dict[str, list[tuple[str, Any]]] = {}
    for entry in scan_vault(config.vault_root).entries:
        frontmatter = entry.get("frontmatter") or {}
        path = entry.get("path", "")
        for key, value in frontmatter.items():
            if key in approved or key in aliased:
                continue
            if key == "cssclasses":  # Obsidian rendering hint, not vault metadata
                continue
            unknown.setdefault(key, []).append((path, value))
    return unknown


def remap_prompt(
    unknown: dict[str, list[tuple[str, Any]]], schema: dict[str, Any]
) -> str:
    """Build the model prompt: unknown keys + samples, and the approved targets."""
    defs = property_definitions_for(schema)
    approved_lines = []
    for name in property_order_from_schema(schema):
        definition = (defs.get(name) or "").strip()
        approved_lines.append(f"- {name}: {definition}" if definition else f"- {name}")
    unknown_lines = []
    for key, samples in sorted(unknown.items()):
        values = ", ".join(
            repr(value) for _path, value in samples[:_MAX_SAMPLES] if value not in (None, "")
        )
        unknown_lines.append(f"- {key}: example values: {values or '(empty)'}")
    return f"""Map each unapproved frontmatter property to the approved property whose meaning best fits, or to "" to drop it.
Only choose from the approved properties listed; never invent a property name.

Approved properties (name: definition):
{chr(10).join(approved_lines)}

Unapproved properties to map (name: example values):
{chr(10).join(unknown_lines)}

Return JSON with exactly these keys:
- mappings: object mapping each unapproved property name to an approved property name, or "" to drop it
- confidence: number from 0 to 1
- warnings: list of short strings for ambiguity
"""


def normalize_remap_response(
    raw: dict[str, Any], unknown_keys: set[str], schema: dict[str, Any]
) -> tuple[dict[str, str], float | None, list[str]]:
    """Validate the model response into ``{old: target_or_""}`` plus confidence/warnings.

    Targets that are not approved properties (and not "") are dropped with a warning
    rather than failing the whole proposal.
    """
    approved = set(property_order_from_schema(schema))
    warnings = list(raw.get("warnings", []) if isinstance(raw.get("warnings"), list) else [])
    confidence = raw.get("confidence")
    confidence = confidence if isinstance(confidence, (int, float)) else None
    mappings: dict[str, str] = {}
    raw_mappings = raw.get("mappings")
    if not isinstance(raw_mappings, dict):
        return {}, confidence, warnings + ["mappings missing or not an object"]
    for old, target in raw_mappings.items():
        if old not in unknown_keys:
            continue
        if not isinstance(target, str):
            warnings.append(f"ignored non-string target for `{old}`")
            continue
        target = target.strip()
        if target and target not in approved:
            warnings.append(f"ignored unapproved target `{target}` for `{old}`")
            continue
        mappings[old] = target
    return mappings, confidence, warnings


def _remap_value(target: str, value: Any, config: AgentConfig) -> Any:
    if target in COMMON_PROPERTIES:
        return _normalize_property_value(target, value, config)
    return value


def build_remap_proposal(
    config: AgentConfig,
    schema: dict[str, Any],
    mappings: dict[str, str],
    unknown: dict[str, list[tuple[str, Any]]],
    *,
    max_notes: int = 200,
) -> dict[str, Any]:
    """Assemble the reviewable proposal: an alias-recording op plus per-note edits."""
    aliases = {old: target for old, target in mappings.items() if target}
    operations: list[dict[str, Any]] = []
    if aliases:
        operations.append({"op": "add_property_aliases", "aliases": aliases})

    note_ops: dict[str, dict[str, Any]] = {}
    for old, target in mappings.items():
        for path, value in unknown.get(old, []):
            op = note_ops.setdefault(path, {"op": "update_frontmatter", "path": path, "set": {}, "remove": []})
            if old not in op["remove"]:
                op["remove"].append(old)
            if target:
                resolved = _remap_value(target, value, config)
                # Mirror alias semantics: only fill an empty target, never overwrite.
                if resolved not in (None, "") and target not in op["set"]:
                    op["set"][target] = resolved
    for path in sorted(note_ops)[:max_notes]:
        operations.append(note_ops[path])

    mapped = ", ".join(f"{old}→{target or 'drop'}" for old, target in sorted(mappings.items()))
    return {
        "id": "property-remap",
        "title": f"Remap {len(mappings)} unapproved propert" + ("y" if len(mappings) == 1 else "ies"),
        "kind": "property-remap",
        "status": "pending",
        "summary": f"Align frontmatter to the approved schema: {mapped}.",
        "operations": operations,
    }


def generate_property_remap_proposal(
    config: AgentConfig,
    *,
    proposal_provider: ProposalProvider | None = None,
    max_notes: int = 200,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Scan, ask the model, and build a property-remap proposal (or report why not)."""
    schema = load_schema(config.vault_root)
    unknown = scan_unknown_properties(config, schema)
    if not unknown:
        return None, ["no unapproved frontmatter properties found"]
    if proposal_provider is None:
        return None, ["property remapping requires an LLM proposal provider"]
    prompt = remap_prompt(unknown, schema)
    raw = proposal_provider.propose_property_remap(prompt=prompt)
    if not isinstance(raw, dict):
        return None, ["model did not return a JSON object"]
    mappings, confidence, warnings = normalize_remap_response(raw, set(unknown), schema)
    if not mappings:
        return None, ["model proposed no usable mappings"] + warnings
    if confidence is not None and confidence < config.llm_confidence_threshold:
        return None, [f"confidence {confidence} below threshold {config.llm_confidence_threshold}"]
    proposal = build_remap_proposal(config, schema, mappings, unknown, max_notes=max_notes)
    if config.review_on_warnings and warnings:
        proposal["summary"] += " (model warnings: " + "; ".join(warnings) + ")"
    return proposal, []
