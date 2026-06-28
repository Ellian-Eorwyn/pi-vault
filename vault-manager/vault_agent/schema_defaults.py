"""Editable Markdown export/import for the default vault schema contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .config import AgentConfig
from .dashboard_layout import dashboard_directories, dashboard_shell_contents
from .paths import (
    BOOTSTRAP_FILE,
    DEFAULT_PATHS,
    VaultPaths,
    build_paths,
    render_bootstrap,
)
from .safety import atomic_write_text
from .schema import (
    AGENT_RULES,
    CAPTURE_TYPE_DEFINITIONS,
    COMMON_PROPERTIES,
    CORE_PROPERTY_ORDER,
    DEFINITION_SCHEMA_KEYS,
    DOMAIN_DEFINITIONS,
    NOTE_TYPES,
    SOURCE_KIND_DEFINITIONS,
    STATUS_DEFINITIONS,
    default_schema,
    definitions_for,
    folder_norms_markdown,
    load_schema,
    note_type_definitions_from_schema,
    property_values_markdown,
    schema_markdown,
)

# Editable description blocks: contract key -> note_type uses note_types[].description,
# the rest map to schema.json <property>_definitions via DEFINITION_SCHEMA_KEYS.
DESCRIPTION_BLOCK_KEYS = (
    "note_type_descriptions",
    "status_descriptions",
    "domain_descriptions",
    "source_kind_descriptions",
    "capture_type_descriptions",
)


CONTROLLED_PROPERTIES = ("type", "status", "domain", "source_kind", "capture_type")
SUPPORTED_EDITABLE_CONTROLLED_PROPERTIES = {"domain"}
DEFAULTS_PROPOSAL_ID = "vault-schema-defaults"


def _description_maps(schema: dict[str, Any] | None, extra_domains: list[str] | None) -> dict[str, dict[str, str]]:
    """Per-property ``{value: definition}`` maps, sourced from the live schema when
    given, otherwise from built-in defaults."""
    if schema:
        domain = definitions_for(schema, "domain")
        note_type = note_type_definitions_from_schema(schema)
        status = definitions_for(schema, "status")
        source_kind = definitions_for(schema, "source_kind")
        capture_type = definitions_for(schema, "capture_type")
    else:
        domain = {
            **DOMAIN_DEFINITIONS,
            **{d: "User-defined domain." for d in _new_domain_values(extra_domains)},
        }
        note_type = {name: spec.get("description", "") for name, spec in NOTE_TYPES.items()}
        status = dict(STATUS_DEFINITIONS)
        source_kind = dict(SOURCE_KIND_DEFINITIONS)
        capture_type = dict(CAPTURE_TYPE_DEFINITIONS)
    return {
        "note_type_descriptions": note_type,
        "status_descriptions": status,
        "domain_descriptions": domain,
        "source_kind_descriptions": source_kind,
        "capture_type_descriptions": capture_type,
    }


def vault_defaults_markdown(
    *,
    paths: VaultPaths = DEFAULT_PATHS,
    extra_domains: list[str] | None = None,
    schema: dict[str, Any] | None = None,
) -> str:
    """Render the editable, deterministic Markdown defaults contract."""
    domain_values = [
        value for value in COMMON_PROPERTIES["domain"]["allowed"] if value
    ] + _new_domain_values(extra_domains)
    descriptions = _description_maps(schema, extra_domains)
    controlled_values: dict[str, list[str]] = {}
    for property_name in CONTROLLED_PROPERTIES:
        allowed = COMMON_PROPERTIES[property_name].get("allowed", [])
        controlled_values[property_name] = [
            value for value in allowed if isinstance(value, str) and value
        ]
    controlled_values["domain"] = domain_values
    folder_structure = {
        "system_dir": paths.system_dir.as_posix(),
        "inbox_dir": paths.inbox_dir.as_posix(),
        "dashboards_dir": paths.dashboards_dir.as_posix(),
        "content_dirs": {
            key: value.as_posix() for key, value in paths.content_dirs.items()
        },
        "domain_folders": {
            key: value.as_posix() for key, value in paths.domain_folders.items()
        },
        "custom_folders": [
            {"path": folder.path.as_posix(), "description": folder.description}
            for folder in paths.custom_folders
        ],
    }
    dashboards = dashboard_shell_contents(paths)
    dashboard_structure = {
        "root": paths.dashboards_dir.as_posix(),
        "entries": [
            {"path": path, "title": Path(path).stem}
            for path in sorted(dashboards)
        ],
    }
    sections = [
        "---",
        "type: system",
        "status: active",
        "domain: meta",
        "parent:",
        "related: []",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "",
        "# Editable Vault Defaults",
        "",
        "This file is a portable pi-vault schema contract. Export it, edit it, then import it to generate pending review proposals. It is not runtime authority until the proposals are approved, applied, and captured in a fresh norms lock.",
        "",
        "## Core Properties",
        "",
        "The sparse frontmatter property set and canonical order. Keep this exact list unless the engine is updated with matching validator support.",
        "",
        _yaml_block({"core_property_order": list(CORE_PROPERTY_ORDER)}),
        "",
        "## Controlled Values",
        "",
        "Blank values are always allowed. In this version, imports may add domain values; edits to type, status, source_kind, or capture_type fail until the corresponding validators are upgraded.",
        "",
        _yaml_block({"controlled_values": controlled_values}),
        "",
        "## Value Definitions",
        "",
        "A definition for every controlled value. These are injected into the model's "
        "classification prompts and required before the norms lock can be written, so "
        "edit them carefully — they are how the model and you stay aligned on meaning.",
        "",
        _yaml_block({"note_type_descriptions": descriptions["note_type_descriptions"]}),
        "",
        _yaml_block({"status_descriptions": descriptions["status_descriptions"]}),
        "",
        _yaml_block({"domain_descriptions": descriptions["domain_descriptions"]}),
        "",
        _yaml_block({"source_kind_descriptions": descriptions["source_kind_descriptions"]}),
        "",
        _yaml_block({"capture_type_descriptions": descriptions["capture_type_descriptions"]}),
        "",
        "## Folder Structure",
        "",
        "These paths become `.pi-vault/config.yaml` when the import proposal is approved. Paths are vault-relative.",
        "",
        _yaml_block({"folders": folder_structure}),
        "",
        "## Dashboard Structure",
        "",
        "Dashboards are regenerated from the folder structure. Import validates these entries against the generated dashboard shells so edits do not silently drift.",
        "",
        _yaml_block({"dashboard_structure": dashboard_structure}),
        "",
        "## Dashboard Regeneration Rules",
        "",
        _yaml_block(
            {
                "dashboard_rules": [
                    "Dashboards are the primary navigation layer; folders are secondary storage.",
                    "Preserve curated Markdown outside pi-vault generated sections.",
                    "Use embedded Bases for live filtering and sorting.",
                    "Allow notes to appear in multiple dashboards without moving or duplicating notes.",
                    "Use pending proposals for existing-vault layout migration.",
                ]
            }
        ),
        "",
        "## Agent Rules",
        "",
        _yaml_block({"agent_rules": list(AGENT_RULES)}),
        "",
        "## Schema Change Policy",
        "",
        _yaml_block(
            {
                "schema_change_policy": [
                    "Markdown import writes pending proposals only.",
                    "Review with vault-agent review-proposals --dry-run before approval.",
                    "Apply only approved proposals through review-proposals --apply-approved.",
                    "Run vault-agent norms-lock --write after applying accepted schema defaults.",
                ]
            }
        ),
        "",
    ]
    return "\n".join(sections)


def run_export_schema_defaults(
    config: AgentConfig,
    *,
    output: str,
) -> tuple[int, str]:
    target = _resolve_export_path(config, output)
    content = vault_defaults_markdown(
        paths=config.paths,
        extra_domains=_schema_extra_domains(config),
        schema=load_schema(config.vault_root),
    )
    if config.dry_run:
        return (
            0,
            "vault-agent export-schema-defaults dry run\n"
            f"Would write: {target}\n"
            "No files were changed.",
        )
    atomic_write_text(target, content)
    return (
        0,
        "vault-agent export-schema-defaults complete\n"
        f"Wrote: {target}\n"
        "Edit the Markdown, then run `vault-agent import-schema-defaults --schema-file <path>`.",
    )


def run_import_schema_defaults(
    config: AgentConfig,
    *,
    schema_file: str,
    overwrite_proposal: bool = False,
) -> tuple[int, str]:
    source = _resolve_input_path(config, schema_file)
    if not source.exists():
        return 1, f"vault-agent import-schema-defaults failed\nError: schema file not found: {source}"
    try:
        parsed = parse_vault_defaults_markdown(source.read_text(encoding="utf-8"))
        proposal = proposal_from_vault_defaults(config, parsed)
    except ValueError as exc:
        return 1, f"vault-agent import-schema-defaults failed\nError: {exc}"
    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    proposal_path = proposal_dir / f"{proposal['id']}.json"
    if config.dry_run:
        return (
            0,
            "vault-agent import-schema-defaults dry run\n"
            f"Schema file: {source}\n"
            f"Would write proposal: {proposal_path}\n"
            f"Operations: {len(proposal['operations'])}\n"
            "No files were changed.",
        )
    if proposal_path.exists() and not overwrite_proposal:
        return (
            1,
            "vault-agent import-schema-defaults failed\n"
            f"Error: proposal already exists: {proposal_path}",
        )
    proposal_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(proposal_path, json.dumps(proposal, indent=2) + "\n")
    return (
        0,
        "vault-agent import-schema-defaults complete\n"
        f"Wrote proposal: {proposal_path}\n"
        "Review with `vault-agent review-proposals --dry-run`.",
    )


def parse_vault_defaults_markdown(text: str) -> dict[str, Any]:
    blocks = _yaml_blocks(text)
    if not blocks:
        raise ValueError("no YAML sections found")
    parsed: dict[str, Any] = {}
    allowed_keys = {
        "core_property_order",
        "controlled_values",
        "domain_descriptions",
        "note_type_descriptions",
        "status_descriptions",
        "source_kind_descriptions",
        "capture_type_descriptions",
        "folders",
        "dashboard_structure",
        "dashboard_rules",
        "agent_rules",
        "schema_change_policy",
    }
    for index, block in enumerate(blocks, start=1):
        try:
            loaded = yaml.safe_load(block) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML section {index} is malformed: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"YAML section {index} must be a mapping")
        unknown = sorted(key for key in loaded if key not in allowed_keys)
        if unknown:
            raise ValueError(f"unknown YAML section key(s): {', '.join(unknown)}")
        for key, value in loaded.items():
            if key in parsed:
                raise ValueError(f"duplicate YAML section key: {key}")
            parsed[key] = value
    _validate_parsed_defaults(parsed)
    return parsed


def proposal_from_vault_defaults(config: AgentConfig, parsed: dict[str, Any]) -> dict[str, Any]:
    del config
    paths = _paths_from_parsed(parsed)
    domain_values = _controlled_values(parsed, "domain")
    extra_domains = _extra_domains_from_values(domain_values)
    schema = default_schema(extra_domains)
    _apply_descriptions(schema, parsed)
    operations: list[dict[str, Any]] = [
        {
            "op": "write_file",
            "path": BOOTSTRAP_FILE.as_posix(),
            "if_exists": "overwrite",
            "content": render_bootstrap(paths),
        },
        {
            "op": "write_file",
            "path": (paths.agent_dir / "schema.json").as_posix(),
            "if_exists": "overwrite",
            "content": json.dumps(schema, indent=2) + "\n",
        },
        {
            "op": "write_file",
            "path": (paths.template_dir / "0.020 vault schema.md").as_posix(),
            "if_exists": "overwrite",
            "content": schema_markdown(extra_domains),
        },
        {
            "op": "write_file",
            "path": (paths.template_dir / "0.021 property values.md").as_posix(),
            "if_exists": "overwrite",
            "content": property_values_markdown(extra_domains),
        },
        {
            "op": "write_file",
            "path": (paths.template_dir / "0.022 folder norms.md").as_posix(),
            "if_exists": "overwrite",
            "content": folder_norms_markdown(),
        },
        {
            "op": "write_file",
            "path": (paths.template_dir / "0.024 vault defaults.md").as_posix(),
            "if_exists": "overwrite",
            "content": vault_defaults_markdown(paths=paths, extra_domains=extra_domains, schema=schema),
        },
    ]
    for directory in (paths.inbox_dir, *dashboard_directories(paths)):
        if not directory.is_relative_to(paths.system_dir):
            operations.append(
                {
                    "op": "create_directory",
                    "path": directory.as_posix(),
                    "if_exists": "preserve",
                }
            )
    for path, content in dashboard_shell_contents(paths).items():
        operations.append(
            {
                "op": "write_file",
                "path": path,
                "if_exists": "overwrite",
                "merge_generated": True,
                "content": content,
            }
        )
    return {
        "id": DEFAULTS_PROPOSAL_ID,
        "title": "Import editable vault schema defaults",
        "kind": "schema-change",
        "status": "pending",
        "automation_safe": False,
        "summary": (
            "Update vault-local schema defaults, bootstrap layout, human-readable docs, "
            "and dashboard shells from an editable Markdown contract."
        ),
        "operations": operations,
    }


def _apply_descriptions(schema: dict[str, Any], parsed: dict[str, Any]) -> None:
    """Overlay edited value definitions from the contract onto the schema dict.

    Controlled-value definitions go into the ``<property>_definitions`` maps;
    note-type definitions update ``note_types[name]["description"]``.
    """
    for prop in ("status", "domain", "source_kind", "capture_type"):
        edits = parsed.get(f"{prop}_descriptions")
        if not isinstance(edits, dict):
            continue
        target = dict(schema.get(DEFINITION_SCHEMA_KEYS[prop]) or {})
        for value, text in edits.items():
            if isinstance(value, str) and isinstance(text, str) and text.strip():
                target[value] = text.strip()
        schema[DEFINITION_SCHEMA_KEYS[prop]] = target
    note_edits = parsed.get("note_type_descriptions")
    if isinstance(note_edits, dict):
        note_types = schema.setdefault("note_types", {})
        for name, text in note_edits.items():
            if (
                isinstance(name, str)
                and isinstance(text, str)
                and text.strip()
                and isinstance(note_types.get(name), dict)
            ):
                note_types[name]["description"] = text.strip()


def _validate_parsed_defaults(parsed: dict[str, Any]) -> None:
    required = {"core_property_order", "controlled_values", "folders", "dashboard_structure"}
    missing = sorted(required - set(parsed))
    if missing:
        raise ValueError(f"missing required section(s): {', '.join(missing)}")
    order = parsed.get("core_property_order")
    if order != list(CORE_PROPERTY_ORDER):
        raise ValueError(
            "core_property_order must exactly match "
            + ", ".join(CORE_PROPERTY_ORDER)
        )
    controlled = parsed.get("controlled_values")
    if not isinstance(controlled, dict):
        raise ValueError("controlled_values must be a mapping")
    for property_name in CONTROLLED_PROPERTIES:
        if property_name not in controlled:
            raise ValueError(f"controlled_values missing {property_name}")
        values = _controlled_values(parsed, property_name)
        if property_name not in SUPPORTED_EDITABLE_CONTROLLED_PROPERTIES:
            expected = [
                value
                for value in COMMON_PROPERTIES[property_name].get("allowed", [])
                if isinstance(value, str) and value
            ]
            if values != expected:
                raise ValueError(
                    f"controlled_values.{property_name} edits are not supported yet"
                )
        else:
            _validate_domain_values(values)
    paths = _paths_from_parsed(parsed)
    expected_entries = [
        {"path": path, "title": Path(path).stem}
        for path in sorted(dashboard_shell_contents(paths))
    ]
    dashboard_structure = parsed.get("dashboard_structure")
    if not isinstance(dashboard_structure, dict):
        raise ValueError("dashboard_structure must be a mapping")
    if dashboard_structure.get("root") != paths.dashboards_dir.as_posix():
        raise ValueError("dashboard_structure.root must match folders.dashboards_dir")
    if dashboard_structure.get("entries") != expected_entries:
        raise ValueError("dashboard_structure.entries must match the generated folder layout")


def _paths_from_parsed(parsed: dict[str, Any]) -> VaultPaths:
    folders = parsed.get("folders")
    if not isinstance(folders, dict):
        raise ValueError("folders must be a mapping")
    try:
        return build_paths(
            folders.get("system_dir", DEFAULT_PATHS.system_dir.as_posix()),
            folders.get("inbox_dir", DEFAULT_PATHS.inbox_dir.as_posix()),
            folders.get("dashboards_dir", DEFAULT_PATHS.dashboards_dir.as_posix()),
            folders.get("content_dirs"),
            folders.get("domain_folders"),
            folders.get("custom_folders"),
        )
    except ValueError as exc:
        raise ValueError(f"invalid folders section: {exc}") from exc


def _validate_domain_values(values: list[str]) -> None:
    builtin = [value for value in COMMON_PROPERTIES["domain"]["allowed"] if value]
    missing = [value for value in builtin if value not in values]
    if missing:
        raise ValueError(f"controlled_values.domain must include built-in value(s): {', '.join(missing)}")
    for value in values:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
            raise ValueError(f"domain value must be a lowercase slug: {value}")


def _controlled_values(parsed: dict[str, Any], property_name: str) -> list[str]:
    controlled = parsed.get("controlled_values")
    if not isinstance(controlled, dict):
        raise ValueError("controlled_values must be a mapping")
    raw_values = controlled.get(property_name)
    if not isinstance(raw_values, list):
        raise ValueError(f"controlled_values.{property_name} must be a list")
    values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"controlled_values.{property_name} entries must be non-empty strings")
        value = item.strip()
        if value not in values:
            values.append(value)
    return values


def _extra_domains_from_values(values: list[str]) -> list[str]:
    builtin = set(COMMON_PROPERTIES["domain"]["allowed"])
    return [value for value in values if value not in builtin]


def _new_domain_values(extra_domains: list[str] | None) -> list[str]:
    builtin = set(COMMON_PROPERTIES["domain"]["allowed"])
    result: list[str] = []
    for domain in extra_domains or []:
        if domain and domain not in builtin and domain not in result:
            result.append(domain)
    return result


def _schema_extra_domains(config: AgentConfig) -> list[str]:
    schema_path = config.vault_root / config.paths.agent_dir / "schema.json"
    try:
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(config.paths.domain_folders)
    core = loaded.get("core_properties", {}) if isinstance(loaded, dict) else {}
    domain = core.get("domain", {}) if isinstance(core, dict) else {}
    allowed = domain.get("allowed", []) if isinstance(domain, dict) else []
    builtin = set(COMMON_PROPERTIES["domain"]["allowed"])
    return [
        value
        for value in allowed
        if isinstance(value, str) and value and value not in builtin
    ]


def _yaml_blocks(text: str) -> list[str]:
    return re.findall(r"```ya?ml\n(.*?)\n```", text, flags=re.DOTALL)


def _yaml_block(value: dict[str, Any]) -> str:
    return "```yaml\n" + yaml.safe_dump(value, sort_keys=False).rstrip() + "\n```"


def _resolve_export_path(config: AgentConfig, output: str) -> Path:
    target = Path(output).expanduser()
    if not target.is_absolute():
        target = config.vault_root / target
    if target.suffix.lower() != ".md":
        raise ValueError("export output must be a Markdown file")
    return target


def _resolve_input_path(config: AgentConfig, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config.vault_root / path
    if path.suffix.lower() != ".md":
        raise ValueError("schema file must be a Markdown file")
    return path


def schema_allowed_values(config: AgentConfig, property_name: str) -> list[str]:
    """Return active controlled values from vault schema.json, with built-ins as fallback."""
    builtin = list(COMMON_PROPERTIES[property_name].get("allowed", []))
    schema_path = config.vault_root / config.paths.agent_dir / "schema.json"
    try:
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return builtin
    if not isinstance(loaded, dict):
        return builtin
    core = loaded.get("core_properties")
    if not isinstance(core, dict):
        return builtin
    spec = core.get(property_name)
    if not isinstance(spec, dict):
        return builtin
    allowed = spec.get("allowed")
    if not isinstance(allowed, list):
        return builtin
    values = [value for value in allowed if isinstance(value, str)]
    if "" in builtin and "" not in values:
        values.insert(0, "")
    return values or builtin
