"""Deterministic metadata cleanup proposal generation."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig, allowed_domains
from .frontmatter import parse_note
from .legacy import apply_legacy_mappings
from .safety import atomic_write_text
from .scanner import discover_markdown
from .schema import (
    COMMON_PROPERTIES,
    allowed_controlled_values_from_schema,
    known_properties_for,
    load_schema,
)


METADATA_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<key>[A-Za-z][A-Za-z0-9 _-]{0,40})\s*:\s*(?P<value>.*?)\s*$"
)
BODY_METADATA_ALIASES = {
    "aliases",
    "area",
    "areas",
    "created",
    "date",
    "domains",
    "privacy",
    "sensitive",
    "source",
    "source title",
    "source role",
    "source_title",
    "source_role",
    "source type",
    "source_type",
    "tags",
    "title",
    "topic",
    "topics",
    "updated",
}


@dataclass(frozen=True)
class MetadataIssueReport:
    property_counts: dict[str, int]
    body_counts: dict[str, int]
    body_files: int
    body_lines: int
    body_samples: dict[str, list[str]]


def run_propose_metadata_normalization(
    config: AgentConfig,
    *,
    max_items: int = 200,
    include_all: bool = False,
    remove_unknown: bool = True,
    clean_body_metadata: bool = True,
    overwrite_proposal: bool = False,
) -> tuple[int, str]:
    if max_items <= 0:
        return 1, "vault-agent propose-metadata-normalization failed\nError: --max-items must be positive"
    proposals, report, total_operations = build_metadata_normalization_proposals(
        config,
        max_items=max_items,
        include_all=include_all,
        remove_unknown=remove_unknown,
        clean_body_metadata=clean_body_metadata,
    )
    if not proposals:
        if getattr(config, "json_output", False):
            return 0, json.dumps({"status": "empty", "operations": 0, "proposals": 0})
        return (
            0,
            "vault-agent propose-metadata-normalization\n"
            "No metadata normalization proposals needed.",
        )
    if config.dry_run:
        if getattr(config, "json_output", False):
            return (
                0,
                json.dumps(
                    _json_payload(
                        "dry-run",
                        proposals=proposals,
                        operations=total_operations,
                        report=report,
                    )
                ),
            )
        return (
            0,
            "vault-agent propose-metadata-normalization dry run\n"
            f"Would write proposals: {len(proposals)}\n"
            f"Operations: {total_operations}\n"
            + _render_report(report),
        )
    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for proposal in proposals:
        target = proposal_dir / f"{proposal['id']}.json"
        if target.exists() and not overwrite_proposal:
            if getattr(config, "json_output", False):
                return (
                    1,
                    json.dumps(
                        _json_payload(
                            "error",
                            proposals=proposals,
                            operations=total_operations,
                            report=report,
                            error=f"proposal already exists: {target.relative_to(config.vault_root).as_posix()}",
                        )
                    ),
                )
            return (
                1,
                "vault-agent propose-metadata-normalization failed\n"
                f"Error: proposal already exists: {target.relative_to(config.vault_root).as_posix()}\n"
                "Pass --overwrite-proposal to replace it.",
            )
        atomic_write_text(target, json.dumps(proposal, indent=2) + "\n")
        written.append(target.relative_to(config.vault_root).as_posix())
    if getattr(config, "json_output", False):
        return (
            0,
            json.dumps(
                _json_payload(
                    "ok",
                    proposals=proposals,
                    operations=total_operations,
                    report=report,
                    paths=written,
                )
            ),
        )
    return (
        0,
        "vault-agent propose-metadata-normalization complete\n"
        f"Proposals written: {len(written)}\n"
        f"Operations: {total_operations}\n"
        + "\n".join(f"- {path}" for path in written)
        + "\n"
        + _render_report(report),
    )


def _json_payload(
    status: str,
    *,
    proposals: list[dict[str, Any]],
    operations: int,
    report: MetadataIssueReport,
    paths: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "proposals": len(proposals),
        "operations": operations,
        "ids": [proposal.get("id") for proposal in proposals],
        "unknown_properties": report.property_counts,
        "body_metadata": report.body_counts,
        "body_metadata_files": report.body_files,
        "body_metadata_lines": report.body_lines,
    }
    if paths is not None:
        payload["paths"] = paths
    if error is not None:
        payload["error"] = error
    return payload


def build_metadata_normalization_proposals(
    config: AgentConfig,
    *,
    max_items: int,
    include_all: bool,
    remove_unknown: bool,
    clean_body_metadata: bool,
) -> tuple[list[dict[str, Any]], MetadataIssueReport, int]:
    schema = load_schema(config.vault_root)
    known = known_properties_for(config.vault_root)
    property_counts: Counter[str] = Counter()
    body_counts: Counter[str] = Counter()
    body_samples: dict[str, list[str]] = defaultdict(list)
    operations: list[dict[str, Any]] = []
    body_files = 0
    body_lines = 0
    for path in discover_markdown(config.vault_root):
        relative = path.relative_to(config.vault_root)
        if relative.is_relative_to(config.paths.system_dir):
            continue
        text = path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        if parsed.error:
            continue
        operation = _normalization_operation(
            config,
            relative=relative,
            frontmatter=dict(parsed.frontmatter),
            body=parsed.body,
            schema=schema,
            known=known,
            remove_unknown=remove_unknown,
            clean_body_metadata=clean_body_metadata,
        )
        for key in _unknown_properties(dict(parsed.frontmatter), known):
            property_counts[key] += 1
        body_result = scan_body_metadata(
            parsed.body,
            known=known,
            alias_keys=set(config.legacy_property_aliases),
        )
        if body_result:
            body_files += 1
            body_lines += len(body_result)
            for key, _line in body_result:
                body_counts[key] += 1
                samples = body_samples[key]
                if len(samples) < 5:
                    samples.append(relative.as_posix())
        if operation:
            operations.append(operation)
            if not include_all and len(operations) >= max_items:
                break
    report = MetadataIssueReport(
        property_counts=dict(sorted(property_counts.items())),
        body_counts=dict(sorted(body_counts.items())),
        body_files=body_files,
        body_lines=body_lines,
        body_samples={key: value for key, value in sorted(body_samples.items())},
    )
    chunks = [operations[index : index + max_items] for index in range(0, len(operations), max_items)]
    proposals: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).isoformat()
    for index, chunk in enumerate(chunks, start=1):
        proposal_id = f"metadata-normalization-{index:03d}"
        proposals.append(
            {
                "id": proposal_id,
                "title": f"Metadata normalization {index:03d}",
                "kind": "metadata-normalization",
                "status": "pending",
                "created_at": stamp,
                "summary": (
                    "Normalize frontmatter aliases, controlled values, scalar/list "
                    "shapes, unknown properties, and imported metadata lines."
                ),
                "counts": {
                    "operations": len(chunk),
                    "unknown_properties": report.property_counts,
                    "body_metadata": report.body_counts,
                    "body_metadata_files": report.body_files,
                    "body_metadata_lines": report.body_lines,
                },
                "samples": {"body_metadata": report.body_samples},
                "operations": chunk,
            }
        )
    return proposals, report, len(operations)


def metadata_issue_report(config: AgentConfig) -> MetadataIssueReport:
    known = known_properties_for(config.vault_root)
    property_counts: Counter[str] = Counter()
    body_counts: Counter[str] = Counter()
    body_samples: dict[str, list[str]] = defaultdict(list)
    body_files = 0
    body_lines = 0
    for path in discover_markdown(config.vault_root):
        relative = path.relative_to(config.vault_root)
        if relative.is_relative_to(config.paths.system_dir):
            continue
        parsed = parse_note(path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        normalized = apply_legacy_mappings(dict(parsed.frontmatter), config)
        for key in _unknown_properties(normalized, known):
            property_counts[key] += 1
        body_result = scan_body_metadata(
            parsed.body,
            known=known,
            alias_keys=set(config.legacy_property_aliases),
        )
        if body_result:
            body_files += 1
            body_lines += len(body_result)
            for key, _line in body_result:
                body_counts[key] += 1
                samples = body_samples[key]
                if len(samples) < 5:
                    samples.append(relative.as_posix())
    return MetadataIssueReport(
        property_counts=dict(sorted(property_counts.items())),
        body_counts=dict(sorted(body_counts.items())),
        body_files=body_files,
        body_lines=body_lines,
        body_samples={key: value for key, value in sorted(body_samples.items())},
    )


def scan_body_metadata(
    body: str,
    *,
    known: set[str],
    alias_keys: set[str],
    max_lines: int = 80,
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    in_fence = False
    for index, line in enumerate(body.splitlines(), start=1):
        if index > max_lines:
            break
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = METADATA_LINE_PATTERN.match(line)
        if match is None:
            continue
        key = _canonical_body_key(match.group("key"))
        if _is_body_metadata_key(key, known=known, alias_keys=alias_keys):
            found.append((key, line.strip()))
    return found


def _normalization_operation(
    config: AgentConfig,
    *,
    relative: Path,
    frontmatter: dict[str, Any],
    body: str,
    schema: dict[str, Any],
    known: set[str],
    remove_unknown: bool,
    clean_body_metadata: bool,
) -> dict[str, Any] | None:
    original_body = body
    normalized = apply_legacy_mappings(dict(frontmatter), config)
    set_values: dict[str, Any] = {}
    remove_keys: set[str] = set()
    for key in list(frontmatter):
        if key not in normalized:
            remove_keys.add(key)
    for key, value in list(normalized.items()):
        if key not in known:
            if remove_unknown:
                remove_keys.add(key)
            continue
        coerced = _coerce_property(config, schema, key, value)
        if coerced != frontmatter.get(key):
            set_values[key] = coerced
            normalized[key] = coerced
    if "summary" in frontmatter and "summary" not in known:
        summary = _clean_summary(frontmatter.get("summary"))
        if summary:
            body = _apply_summary(body, summary)
    if clean_body_metadata:
        body = _remove_body_metadata(body, known=known, alias_keys=set(config.legacy_property_aliases))
    unknown = _unknown_properties(normalized, known)
    if remove_unknown:
        remove_keys.update(unknown)
    operation: dict[str, Any] = {
        "op": "normalize_metadata",
        "path": relative.as_posix(),
        "set": set_values,
        "remove": sorted(remove_keys),
    }
    if body != original_body:
        operation["body"] = body
    changed = bool(set_values or remove_keys or body != original_body)
    return operation if changed else None


def _unknown_properties(frontmatter: dict[str, Any], known: set[str]) -> list[str]:
    return sorted(key for key in frontmatter if isinstance(key, str) and key not in known)


def _coerce_property(
    config: AgentConfig,
    schema: dict[str, Any],
    key: str,
    value: Any,
) -> Any:
    spec = _property_spec(schema, key)
    property_type = spec.get("type") if isinstance(spec, dict) else COMMON_PROPERTIES.get(key, {}).get("type")
    allowed = _allowed_values(config, schema, key)
    if key == "related":
        return _list_value(value)
    if property_type == "list":
        return _list_value(value)
    if isinstance(value, list):
        value = _first_scalar(value)
    if isinstance(value, str):
        text = value.strip()
        alias = _value_alias(config, key, text)
        if alias is not None:
            text = alias
        if allowed:
            lower = text.lower()
            if lower in allowed:
                text = lower
            elif text not in allowed:
                return value
        return text
    return value


def _allowed_values(config: AgentConfig, schema: dict[str, Any], key: str) -> list[str]:
    if key == "domain":
        return allowed_domains(config)
    return allowed_controlled_values_from_schema(schema, key)


def _property_spec(schema: dict[str, Any], key: str) -> dict[str, Any]:
    core = schema.get("core_properties")
    if isinstance(core, dict):
        spec = core.get(key)
        if isinstance(spec, dict):
            return spec
    spec = COMMON_PROPERTIES.get(key)
    return spec if isinstance(spec, dict) else {}


def _value_alias(config: AgentConfig, key: str, text: str) -> str | None:
    lowered = text.lower()
    if key == "type":
        return config.legacy_type_aliases.get(lowered)
    if key == "status":
        return config.legacy_status_aliases.get(lowered)
    if key == "source_kind":
        return config.legacy_source_kind_aliases.get(lowered)
    return None


def _list_value(value: Any) -> list[str]:
    if value in (None, "", "None"):
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_list_value(item))
        return result
    text = str(value).strip()
    if not text or text.lower() == "none":
        return []
    if "," in text and not text.startswith("[["):
        return [item for part in text.split(",") for item in _list_value(part)]
    return [text.removeprefix("#").strip()]


def _first_scalar(value: list[Any]) -> Any:
    for item in value:
        if item not in (None, ""):
            return str(item).strip()
    return ""


def _clean_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    metadata_prefix = re.compile(
        r"^(type|status|privacy|sensitive|domains?|tags?|topics?|source_type|source_kind):\s+\S+\s*",
        re.IGNORECASE,
    )
    while True:
        cleaned = metadata_prefix.sub("", text).strip()
        if cleaned == text:
            return cleaned
        text = cleaned


def _apply_summary(body: str, summary: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Summary":
            next_heading = len(lines)
            for cursor in range(index + 1, len(lines)):
                if lines[cursor].startswith("## "):
                    next_heading = cursor
                    break
            replacement = lines[: index + 1] + ["", summary, ""] + lines[next_heading:]
            return "\n".join(replacement).rstrip() + "\n"
    return body.rstrip() + "\n\n## Summary\n\n" + summary + "\n"


def _remove_body_metadata(body: str, *, known: set[str], alias_keys: set[str]) -> str:
    lines = body.splitlines()
    kept: list[str] = []
    in_fence = False
    for index, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            kept.append(line)
            continue
        match = METADATA_LINE_PATTERN.match(line)
        if (
            index <= 80
            and not in_fence
            and match is not None
            and _is_body_metadata_key(
                _canonical_body_key(match.group("key")),
                known=known,
                alias_keys=alias_keys,
            )
        ):
            continue
        kept.append(line)
    return "\n".join(kept).rstrip() + ("\n" if body.endswith("\n") else "")


def _canonical_body_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _is_body_metadata_key(key: str, *, known: set[str], alias_keys: set[str]) -> bool:
    normalized_aliases = {_canonical_body_key(item) for item in alias_keys}
    normalized_body_keys = {_canonical_body_key(item) for item in BODY_METADATA_ALIASES}
    return key in normalized_body_keys or key in normalized_aliases


def _render_report(report: MetadataIssueReport) -> str:
    lines = [
        f"Unknown frontmatter groups: {sum(report.property_counts.values())}",
        f"Body metadata files: {report.body_files}",
        f"Body metadata lines: {report.body_lines}",
    ]
    if report.property_counts:
        lines.append("Frontmatter groups:")
        lines.extend(f"- {key}: {count}" for key, count in report.property_counts.items())
    if report.body_counts:
        lines.append("Body metadata groups:")
        lines.extend(f"- {key}: {count}" for key, count in report.body_counts.items())
    return "\n".join(lines)
