"""Proposal generators for common agent requests."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .base_hierarchy import (
    _base_block,
    _dashboard_frontmatter,
    generate_base_hierarchy_proposal,
    hierarchy_llm_prompt,
    normalize_hierarchy_llm_response,
)
from .config import AgentConfig
from .dashboard_layout import dashboard_directories, dashboard_shell_contents
from .frontmatter import parse_note
from .legacy import apply_legacy_mappings
from .llm import (
    ProposalProvider,
    provider_from_config,
    schema_stage_extras,
    validate_stage_proposal,
)
from .layout_routing import build_inbox_sort_proposal, route_note
from .paths import BOOTSTRAP_FILE, render_bootstrap
from .reconcile import infer_type_from_content
from .safety import atomic_write_text
from .scanner import scan_vault
from .schema import (
    COMMON_PROPERTIES,
    CORE_PROPERTY_ORDER,
    NOTE_TYPES,
    accepted_properties_for,
    default_schema,
    property_values_markdown,
    template_for,
)
from .validation import validate_entries


PROPOSAL_DIR = Path("99 System") / "0.01 agent" / "review" / "proposals"


def run_propose_index(
    config: AgentConfig,
    *,
    index_type: str,
    title: str | None = None,
    filter_value: str | None = None,
    output_path: str | None = None,
    overwrite: bool = False,
) -> tuple[int, str]:
    proposal = generate_index_proposal(
        index_type=index_type,
        title=title,
        filter_value=filter_value,
        output_path=output_path,
        overwrite=overwrite,
    )
    return _write_proposal(config, proposal, dry_run=config.dry_run)


def run_propose_property(
    config: AgentConfig,
    *,
    property_name: str,
    allowed_value: str,
    description: str | None = None,
    overwrite: bool = True,
) -> tuple[int, str]:
    proposal, errors = generate_property_proposal(
        config=config,
        property_name=property_name,
        allowed_value=allowed_value,
        description=description,
        overwrite=overwrite,
    )
    if errors:
        return 1, "vault-agent propose-property failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    return _write_proposal(config, proposal, dry_run=config.dry_run)


def run_propose_topic_hubs(
    config: AgentConfig,
    *,
    domain: str | None = None,
    min_cluster: int = 3,
    overwrite_proposal: bool = False,
) -> tuple[int, str]:
    from .topic_hubs import build_topic_hubs_proposal

    result = scan_vault(config.vault_root)
    schema = _load_current_schema(config)
    proposal, _registry, added = build_topic_hubs_proposal(
        entries=result.entries,
        schema=schema,
        domains=[domain] if domain else None,
        min_cluster=min_cluster,
        system_dir=config.paths.system_dir,
    )
    if not added:
        return (
            0,
            "vault-agent propose-topic-hubs\n"
            "No new hubs surfaced (clusters below the minimum or already registered).",
        )
    exit_code, output = _write_proposal(
        config, proposal, dry_run=config.dry_run, overwrite_existing=overwrite_proposal
    )
    return exit_code, output + "\n" + f"Hubs surfaced: {len(added)}\n" + "\n".join(
        f"- {label}" for label in added
    )


def run_propose_template(
    config: AgentConfig,
    *,
    note_type: str,
    overwrite: bool = True,
) -> tuple[int, str]:
    proposal, errors = generate_template_proposal(
        config=config,
        note_type=note_type,
        overwrite=overwrite,
    )
    if errors:
        return 1, "vault-agent propose-template failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    return _write_proposal(config, proposal, dry_run=config.dry_run)


def run_propose_cleanup(
    config: AgentConfig,
    *,
    note: str,
    remove_unknown: bool = False,
) -> tuple[int, str]:
    proposal, errors = generate_cleanup_proposal(
        config=config,
        note=note,
        remove_unknown=remove_unknown,
    )
    if errors:
        return 1, "vault-agent propose-cleanup failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    return _write_proposal(config, proposal, dry_run=config.dry_run)


def run_propose_cleanup_queue(
    config: AgentConfig,
    *,
    folder: str | None = None,
    max_items: int = 25,
    remove_unknown: bool = False,
    overwrite_proposal: bool = False,
) -> tuple[int, str]:
    proposal, errors, stats = generate_cleanup_queue_proposal(
        config=config,
        folder=folder,
        max_items=max_items,
        remove_unknown=remove_unknown,
    )
    if errors:
        return 1, "vault-agent propose-cleanup-queue failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    exit_code, output = _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal,
    )
    return (
        exit_code,
        output
        + "\n"
        + f"Cleanup operations: {stats['operations']}\n"
        + f"Validation issues considered: {stats['issues']}",
    )


def run_propose_inbox_sort(
    config: AgentConfig,
    *,
    max_notes: int = 5,
    safe_only: bool = False,
    overwrite_proposal: bool = False,
    proposal_provider: ProposalProvider | None = None,
) -> tuple[int, str]:
    if max_notes < 1:
        return 1, "vault-agent propose-inbox-sort failed\nError: max-notes must be positive"
    if proposal_provider is None and config.routing_mode == "custom":
        proposal_provider = provider_from_config(config)
    proposal, warnings = build_inbox_sort_proposal(
        config, max_notes=max_notes, safe_only=safe_only, proposal_provider=proposal_provider
    )
    if not proposal["operations"]:
        detail = "\n".join(f"Warning: {warning}" for warning in warnings)
        return 0, "vault-agent propose-inbox-sort\nNo routable inbox notes found." + (
            "\n" + detail if detail else ""
        )
    code, output = _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal,
    )
    if warnings:
        output += "\n" + "\n".join(f"Warning: {warning}" for warning in warnings)
    return code, output


def run_propose_vault_layout(
    config: AgentConfig, *, overwrite_proposal: bool = False
) -> tuple[int, str]:
    operations: list[dict[str, Any]] = []
    planned_directories = set(dashboard_directories(config.paths))
    for directory in dashboard_directories(config.paths):
        operations.append(
            {"op": "create_directory", "path": directory.as_posix(), "if_exists": "preserve"}
        )
    for path, content in dashboard_shell_contents(config.paths).items():
        if (config.vault_root / path).exists():
            continue
        operations.append(
            {"op": "write_file", "path": path, "if_exists": "fail", "content": content}
        )
    operations.append(
        {
            "op": "write_file",
            "path": BOOTSTRAP_FILE.as_posix(),
            "if_exists": "overwrite",
            "content": render_bootstrap(config.paths),
        }
    )
    dashboard_paths = set(dashboard_shell_contents(config.paths))
    planned_destinations: set[Path] = set()
    for note_path in sorted(config.vault_root.rglob("*.md")):
        relative = note_path.relative_to(config.vault_root)
        if (
            relative.is_relative_to(config.paths.system_dir)
            or relative.is_relative_to(config.paths.inbox_dir)
            or relative.is_relative_to(config.paths.dashboards_dir)
            or relative.as_posix() in dashboard_paths
        ):
            continue
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        decision = route_note(config, note_path, parsed.frontmatter)
        if decision.destination_dir is None or relative.parent == decision.destination_dir:
            continue
        destination = decision.destination_dir / note_path.name
        if destination in planned_destinations or (config.vault_root / destination).exists():
            continue
        planned_destinations.add(destination)
        if decision.destination_dir not in planned_directories:
            planned_directories.add(decision.destination_dir)
            operations.append(
                {
                    "op": "create_directory",
                    "path": decision.destination_dir.as_posix(),
                    "if_exists": "preserve",
                }
            )
        operations.append(
            {
                "op": "move_note",
                "path": relative.as_posix(),
                "destination": destination.as_posix(),
                "update_links": True,
            }
        )
    proposal = {
        "id": "vault-layout",
        "title": "Adopt dashboard-first vault layout",
        "kind": "vault-layout",
        "status": "pending",
        "automation_safe": False,
        "summary": "Create dashboard-first navigation and record deterministic content destinations without moving existing notes automatically.",
        "operations": operations,
    }
    return _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal,
    )
def run_propose_base_hierarchy(
    config: AgentConfig,
    *,
    output_root: str | None = None,
    min_child_notes: int = 2,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
    overwrite_proposal: bool = False,
) -> tuple[int, str]:
    proposal, errors, stats = generate_base_hierarchy(
        config=config,
        output_root=output_root or config.paths.dashboards_dir.as_posix(),
        min_child_notes=min_child_notes,
        proposal_provider=proposal_provider,
        llm_limit=llm_limit,
    )
    if errors:
        return 1, "vault-agent propose-base-hierarchy failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    exit_code, output = _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal,
    )
    return (
        exit_code,
        output
        + "\n"
        + f"Domains: {stats['domains']}\n"
        + f"Parent/project dashboards: {stats['parent_dashboards']}\n"
        + f"Needs metadata: {stats['needs_metadata']}\n"
        + f"LLM coverage used: {stats['llm_used']}",
    )


def run_propose_folder_organization(
    config: AgentConfig,
    *,
    folder: str,
    project: str,
    domain: str,
    dashboard_title: str | None = None,
    dashboard_path: str | None = None,
    overwrite_dashboard: bool = True,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
    overwrite_proposal: bool = False,
    remove_legacy: bool = False,
    checkpoint: bool = False,
    resume: bool = False,
) -> tuple[int, str]:
    proposal, errors, stats = generate_folder_organization_proposal(
        config=config,
        folder=folder,
        project=project,
        domain=domain,
        dashboard_title=dashboard_title,
        dashboard_path=dashboard_path,
        overwrite_dashboard=overwrite_dashboard,
        proposal_provider=proposal_provider,
        llm_limit=llm_limit,
        remove_legacy=remove_legacy,
        checkpoint=checkpoint,
        resume=resume,
    )
    if errors:
        return 1, "vault-agent propose-folder-organization failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    exit_code, output = _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal or checkpoint,
    )
    return (
        exit_code,
        output
        + "\n"
        + f"Notes organized: {stats['notes']}\n"
        + f"LLM notes consulted: {stats['llm_notes']}\n"
        + f"Dashboard: {proposal['operations'][-1]['path']}",
    )


def generate_index_proposal(
    *,
    index_type: str,
    title: str | None = None,
    filter_value: str | None = None,
    output_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    normalized_type = index_type.strip().lower()
    if normalized_type not in {"type", "project", "parent", "domain"}:
        raise ValueError("index type must be type, project, parent, or domain")
    label = (filter_value or title or normalized_type).strip()
    if not label:
        raise ValueError("title or filter value is required")
    index_title = title.strip() if title else _title_for_index(normalized_type, label)
    target = output_path or f"Indexes/{_safe_filename(index_title)}.md"
    return {
        "id": f"index-{_slug(index_title)}",
        "title": index_title,
        "kind": "index-note",
        "status": "pending",
        "summary": f"Create or update an index note for {normalized_type} `{label}`.",
        "operations": [
            {
                "op": "write_file",
                "path": target,
                "if_exists": "overwrite" if overwrite else "fail",
                "content": _index_content(
                    index_type=normalized_type,
                    title=index_title,
                    filter_value=label,
                ),
            }
        ],
    }


def generate_property_proposal(
    *,
    config: AgentConfig | None = None,
    property_name: str,
    allowed_value: str,
    description: str | None = None,
    overwrite: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    property_name = property_name.strip()
    allowed_value = allowed_value.strip()
    errors: list[str] = []
    if property_name not in COMMON_PROPERTIES:
        errors.append(f"unknown core property `{property_name}`")
    elif "allowed" not in COMMON_PROPERTIES[property_name]:
        errors.append(f"property `{property_name}` does not have controlled values")
    elif allowed_value in COMMON_PROPERTIES[property_name].get("allowed", []):
        errors.append(f"value `{allowed_value}` already exists for `{property_name}`")
    if not allowed_value:
        errors.append("allowed value is required")
    if errors:
        return {}, errors

    schema = _load_current_schema(config)
    current_allowed = schema.get("core_properties", {}).get(property_name, {}).get("allowed", [])
    if allowed_value in current_allowed:
        return {}, [f"value `{allowed_value}` already exists for `{property_name}`"]
    core_properties = deepcopy(schema["core_properties"])
    core_properties.setdefault(property_name, deepcopy(COMMON_PROPERTIES[property_name]))
    core_properties[property_name]["allowed"].append(allowed_value)
    common_properties = deepcopy(schema["common_properties"])
    common_properties.setdefault(property_name, deepcopy(COMMON_PROPERTIES[property_name]))
    common_properties[property_name]["allowed"].append(allowed_value)
    schema["core_properties"] = core_properties
    schema["common_properties"] = common_properties
    definition_text = _property_definition_markdown(
        config=config,
        property_name=property_name,
        allowed_value=allowed_value,
        description=description,
    )
    proposal = {
        "id": f"property-{property_name}-{_slug(allowed_value)}",
        "title": f"Add `{allowed_value}` to `{property_name}`",
        "kind": "schema-change",
        "status": "pending",
        "summary": f"Add controlled value `{allowed_value}` to `{property_name}`.",
        "operations": [
            {
                "op": "write_file",
                "path": (
                    config.paths.agent_dir / "schema.json"
                    if config
                    else Path("99 System/0.01 agent/schema.json")
                ).as_posix(),
                "if_exists": "overwrite" if overwrite else "fail",
                "content": json.dumps(schema, indent=2) + "\n",
            },
            {
                "op": "write_file",
                "path": (
                    config.paths.template_dir / "0.021 property values.md"
                    if config
                    else Path("99 System/0.02 templates/0.021 property values.md")
                ).as_posix(),
                "if_exists": "overwrite" if overwrite else "fail",
                "content": definition_text,
            },
        ],
    }
    return proposal, []


def generate_template_proposal(
    *,
    config: AgentConfig | None = None,
    note_type: str,
    overwrite: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    note_type = note_type.strip()
    if note_type not in NOTE_TYPES:
        return {}, [f"unknown note type `{note_type}`"]
    spec = NOTE_TYPES[note_type]
    content = template_for(note_type, spec["description"])
    proposal = {
        "id": f"template-{note_type}",
        "title": f"Refresh `{note_type}` template",
        "kind": "template-change",
        "status": "pending",
        "summary": f"Update the vault-local `{note_type}` note template from the current repo default.",
        "operations": [
            {
                "op": "write_file",
                "path": (
                    (config.paths.template_dir if config else Path("99 System/0.02 templates"))
                    / "note-types"
                    / f"{note_type}.md"
                ).as_posix(),
                "if_exists": "overwrite" if overwrite else "fail",
                "content": content,
            }
        ],
    }
    return proposal, []


def run_propose_note_type(
    config: AgentConfig,
    *,
    name: str,
    description: str,
    folder: str,
    title: str | None = None,
    template_body: str | None = None,
    overwrite: bool = False,
) -> tuple[int, str]:
    proposal, errors = generate_note_type_proposal(
        config=config,
        name=name,
        description=description,
        folder=folder,
        title=title,
        template_body=template_body,
        overwrite=overwrite,
    )
    if errors:
        return 1, "vault-agent propose-note-type failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    return _write_proposal(config, proposal, dry_run=config.dry_run)


def generate_note_type_proposal(
    *,
    config: AgentConfig,
    name: str,
    description: str,
    folder: str,
    title: str | None = None,
    template_body: str | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    name = name.strip()
    description = (description or "").strip()
    folder = folder.strip().strip("/")
    errors: list[str] = []
    if re.fullmatch(r"[a-z][a-z0-9_-]*", name) is None:
        errors.append("note type name must be a lowercase slug (letters, digits, - or _)")
    if name in NOTE_TYPES:
        errors.append(f"`{name}` is a built-in note type")
    if not description:
        errors.append("a description is required")
    folder_error = _validate_note_type_folder(config, folder)
    if folder_error:
        errors.append(folder_error)
    schema = _load_current_schema(config)
    if name in schema.get("note_types", {}):
        errors.append(f"note type `{name}` already exists in the schema")
    if errors:
        return {}, errors

    schema = deepcopy(schema)
    note_types = schema.setdefault("note_types", {})
    note_types[name] = {"folder": folder, "description": description}
    core_properties = schema.setdefault("core_properties", deepcopy(default_schema()["core_properties"]))
    type_allowed = core_properties.setdefault("type", deepcopy(COMMON_PROPERTIES["type"]))["allowed"]
    if name not in type_allowed:
        type_allowed.append(name)
    schema["common_properties"] = core_properties
    folder_norms = schema.setdefault("folder_norms", {})
    folder_norms[name] = {"preferred_folder": folder}

    template_content = _note_type_template_content(
        name=name, title=title or name.replace("-", " ").title(), description=description, body=template_body
    )
    operations = [
        {
            "op": "write_file",
            "path": (config.paths.agent_dir / "schema.json").as_posix(),
            "if_exists": "overwrite",
            "content": json.dumps(schema, indent=2) + "\n",
        },
        {
            "op": "write_file",
            "path": (config.paths.template_dir / "note-types" / f"{name}.md").as_posix(),
            "if_exists": "overwrite" if overwrite else "fail",
            "content": template_content,
        },
        {
            "op": "create_directory",
            "path": folder,
            "if_exists": "preserve",
        },
    ]
    proposal = {
        "id": f"note-type-{name}",
        "title": f"Add note type `{name}`",
        "kind": "schema-change",
        "status": "pending",
        "automation_safe": False,
        "summary": f"Define a new `{name}` note type, its template, and preferred folder `{folder}`.",
        "operations": operations,
    }
    return proposal, []


def _validate_note_type_folder(config: AgentConfig, folder: str) -> str | None:
    if not folder:
        return "a preferred folder is required"
    target = Path(folder)
    if target.is_absolute() or ".." in target.parts:
        return "folder must be a relative path inside the vault"
    if target.is_relative_to(config.paths.system_dir):
        return f"folder cannot be inside {config.paths.system_dir}"
    return None


def _note_type_template_content(
    *, name: str, title: str, description: str, body: str | None
) -> str:
    section_body = (body or "").strip() or f"# {title}\n\n## Summary\n\n## Notes\n"
    return (
        f"---\ntype: {name}\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\n"
        f"source_kind:\ncapture_type:\n---\n\n{section_body.rstrip()}\n\n<!-- {description} -->\n"
    )


def generate_cleanup_proposal(
    *,
    config: AgentConfig,
    note: str,
    remove_unknown: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    try:
        note_path = _resolve_note(config.vault_root, note)
    except ValueError as exc:
        return {}, [str(exc)]
    relative = note_path.relative_to(config.vault_root)
    if relative.is_relative_to(config.paths.system_dir):
        return {}, [f"cleanup proposals cannot target {config.paths.system_dir}"]
    text = note_path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error:
        return {}, [parsed.error]

    original = dict(parsed.frontmatter)
    mapped = apply_legacy_mappings(original, config)
    set_values: dict[str, Any] = {}
    for key in CORE_PROPERTY_ORDER:
        if key in mapped and mapped.get(key) != original.get(key):
            set_values[key] = mapped[key]
        elif key not in original:
            set_values[key] = [] if key == "related" else ""

    note_type = mapped.get("type") if mapped.get("type") in NOTE_TYPES else None
    accepted = accepted_properties_for(note_type)
    remove = sorted(key for key in mapped if key not in accepted) if remove_unknown else []
    if not set_values and not remove:
        return {}, [f"no cleanup changes found for `{relative.as_posix()}`"]

    proposal = {
        "id": f"cleanup-{_slug(relative.with_suffix('').as_posix())}",
        "title": f"Clean up `{relative.as_posix()}` frontmatter",
        "kind": "cleanup",
        "status": "pending",
        "summary": "Apply schema-approved frontmatter cleanup to one note.",
        "operations": [
            {
                "op": "update_frontmatter",
                "path": relative.as_posix(),
                "set": set_values,
                "remove": remove,
            }
        ],
    }
    return proposal, []


def generate_cleanup_queue_proposal(
    *,
    config: AgentConfig,
    folder: str | None = None,
    max_items: int = 25,
    remove_unknown: bool = False,
) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    if max_items < 1:
        return {}, ["max-items must be at least 1"], {"operations": 0, "issues": 0}
    result = scan_vault(config.vault_root)
    issues = validate_entries(result.entries, config)
    scoped_entries = _scoped_cleanup_entries(config, result.entries, folder)
    operations: list[dict[str, Any]] = []
    for entry in scoped_entries:
        operation = _cleanup_operation_for_entry(
            config=config,
            path=entry["path"],
            remove_unknown=remove_unknown,
        )
        if operation:
            operations.append(operation)
        if len(operations) >= max_items:
            break
    if not operations:
        return {}, ["no cleanup queue changes found"], {"operations": 0, "issues": len(issues)}
    scope_slug = _slug(folder or "vault")
    proposal = {
        "id": f"cleanup-queue-{scope_slug}",
        "title": f"Clean up `{folder or 'vault'}` validation queue",
        "kind": "cleanup",
        "status": "pending",
        "summary": "Apply bounded schema-approved cleanup operations from grouped validation issues.",
        "operations": operations,
    }
    return proposal, [], {"operations": len(operations), "issues": len(issues)}


def generate_base_hierarchy(
    *,
    config: AgentConfig,
    output_root: str | None = None,
    min_child_notes: int = 2,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
) -> tuple[dict[str, Any], list[str], dict[str, int | bool]]:
    resolved_output = output_root or config.paths.dashboards_dir.as_posix()
    output_path = Path(resolved_output.strip().strip("/"))
    if output_path.is_relative_to(config.paths.agent_dir):
        return (
            {},
            ["output root cannot be inside generated agent state"],
            {"domains": 0, "parent_dashboards": 0, "needs_metadata": 0, "llm_used": False},
        )
    if min_child_notes < 1:
        return (
            {},
            ["min-child-notes must be at least 1"],
            {"domains": 0, "parent_dashboards": 0, "needs_metadata": 0, "llm_used": False},
        )
    result = scan_vault(config.vault_root)
    llm_overrides: dict[str, Any] | None = None
    llm_used = False
    try:
        if proposal_provider and llm_limit > 0:
            deterministic_proposal, deterministic_plan = generate_base_hierarchy_proposal(
                entries=result.entries,
                output_root=resolved_output,
                min_child_notes=min_child_notes,
                system_dir=config.paths.system_dir,
            )
            del deterministic_proposal
            llm_overrides = _base_hierarchy_llm_overrides(
                proposal_provider=proposal_provider,
                plan=deterministic_plan,
                llm_limit=llm_limit,
            )
            llm_used = bool(
                llm_overrides
                and (llm_overrides.get("domains") or llm_overrides.get("parents"))
            )
        proposal, plan = generate_base_hierarchy_proposal(
            entries=result.entries,
            output_root=resolved_output,
            min_child_notes=min_child_notes,
            llm_overrides=llm_overrides,
            system_dir=config.paths.system_dir,
        )
    except ValueError as exc:
        return (
            {},
            [str(exc)],
            {"domains": 0, "parent_dashboards": 0, "needs_metadata": 0, "llm_used": False},
        )
    return (
        proposal,
        [],
        {
            "domains": len(plan.domains),
            "parent_dashboards": plan.parent_dashboard_count,
            "needs_metadata": len(plan.needs_metadata),
            "llm_used": llm_used,
        },
    )


def _base_hierarchy_llm_overrides(
    *,
    proposal_provider: ProposalProvider,
    plan: Any,
    llm_limit: int,
) -> dict[str, Any]:
    prompt = hierarchy_llm_prompt(plan, max_domains=llm_limit)
    propose_hierarchy = getattr(proposal_provider, "propose_base_hierarchy", None)
    if not callable(propose_hierarchy):
        return {}
    try:
        response = propose_hierarchy(prompt=prompt)
    except Exception:
        return {}
    if not isinstance(response, dict):
        return {}
    return normalize_hierarchy_llm_response(response)


def generate_folder_organization_proposal(
    *,
    config: AgentConfig,
    folder: str,
    project: str,
    domain: str,
    dashboard_title: str | None = None,
    dashboard_path: str | None = None,
    overwrite_dashboard: bool = True,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
    remove_legacy: bool = False,
    checkpoint: bool = False,
    resume: bool = False,
) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    errors: list[str] = []
    if domain not in COMMON_PROPERTIES["domain"]["allowed"]:
        errors.append(f"domain `{domain}` is not an approved value")
    if not project.strip():
        errors.append("project is required")
    try:
        folder_path = _resolve_folder(config.vault_root, folder)
    except ValueError as exc:
        errors.append(str(exc))
        folder_path = config.vault_root
    if errors:
        return {}, errors, {"notes": 0, "llm_notes": 0}

    proposal_id = f"folder-organization-{_slug(project)}"
    title = dashboard_title or f"{project} Dashboard"
    dashboard = dashboard_path or f"{folder.rstrip('/')}/{_safe_filename(title)}.md"
    dashboard_abs = (config.vault_root / dashboard).resolve()
    note_paths = sorted(
        path for path in folder_path.rglob("*.md") if path.resolve() != dashboard_abs
    )
    if not note_paths:
        return {}, [f"folder contains no Markdown notes: {folder}"], {"notes": 0, "llm_notes": 0}

    project_link = _wikilink(project)
    operations = (
        _load_checkpoint_operations(config, proposal_id)
        if resume
        else []
    )
    processed_paths = {
        operation.get("path")
        for operation in operations
        if isinstance(operation, dict) and operation.get("op") == "organize_note"
    }
    llm_attempts = 0
    llm_notes = 0
    for index, note_path in enumerate(note_paths, start=1):
        relative = note_path.relative_to(config.vault_root)
        if relative.as_posix() in processed_paths:
            if checkpoint:
                print(f"[{index}/{len(note_paths)}] skipped {relative.as_posix()}", flush=True)
            continue
        if checkpoint:
            print(f"[{index}/{len(note_paths)}] {relative.as_posix()}", flush=True)
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        if parsed.error:
            errors.append(f"{relative.as_posix()}: {parsed.error}")
            continue
        mapped = apply_legacy_mappings(parsed.frontmatter, config)
        note_type = _approved_type(mapped.get("type"))
        llm_property_values: dict[str, Any] = {}
        if proposal_provider and llm_attempts < llm_limit:
            llm_attempts += 1
            llm_errors, llm_type = _llm_type_for_note(
                provider=proposal_provider,
                config=config,
                note_path=note_path,
                note_text=note_path.read_text(encoding="utf-8"),
            )
            if llm_errors:
                errors.extend(f"{relative.as_posix()}: {error}" for error in llm_errors)
                continue
            if llm_type:
                note_type = llm_type
            llm_notes += 1

        if note_type is None:
            note_type = infer_type_from_content(
                relative, parsed.body, inbox_dir=config.paths.inbox_dir
            ) or "note"
        status = _approved_status(mapped.get("status")) or "active"
        source_kind = _approved_source_kind(mapped.get("source_kind")) or ""
        capture_type = _approved_capture_type(mapped.get("capture_type")) or ""
        related = _merged_related(
            mapped.get("related"),
            llm_property_values.get("related"),
            parsed.frontmatter.get("project"),
            project_link,
        )
        set_values = {
            "type": note_type,
            "status": llm_property_values.get("status") or status,
            "domain": domain,
            "parent": _existing_parent(mapped.get("parent")) or project_link,
            "related": related,
                "cover": llm_property_values.get("cover") or mapped.get("cover") or "",
                "source_kind": llm_property_values.get("source_kind") or source_kind,
                "capture_type": llm_property_values.get("capture_type") or capture_type,
        }
        remove = (
            sorted(key for key in parsed.frontmatter if key not in CORE_PROPERTY_ORDER)
            if remove_legacy
            else []
        )
        operations.append(
            {
                "op": "organize_note",
                "path": relative.as_posix(),
                "set": set_values,
                "remove": remove,
                "summary": llm_property_values.get("summary", ""),
                "apply_template": True,
            }
        )
        if checkpoint and not config.dry_run:
            _write_checkpoint_proposal(
                config=config,
                proposal_id=proposal_id,
                title=f"Organize `{project}` folder",
                folder=folder,
                operations=operations,
            )

    if errors:
        return {}, errors, {"notes": len(note_paths), "llm_notes": llm_notes}

    operations.append(
        {
            "op": "write_file",
            "path": dashboard,
            "if_exists": "overwrite" if overwrite_dashboard else "fail",
            "content": _folder_dashboard_content(
                title=title,
                project=project,
                project_link=project_link,
                domain=domain,
                folder=folder,
            ),
        }
    )
    proposal = {
        "id": proposal_id,
        "title": f"Organize `{project}` folder",
        "kind": "folder-organization",
        "status": "pending",
        "summary": (
            f"Apply sparse metadata, template sections, and a dashboard for notes under `{folder}`."
        ),
        "operations": operations,
    }
    return proposal, [], {"notes": len(note_paths), "llm_notes": llm_notes}


def _write_proposal(
    config: AgentConfig,
    proposal: dict[str, Any],
    *,
    dry_run: bool,
    overwrite_existing: bool = False,
) -> tuple[int, str]:
    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    path = proposal_dir / f"{proposal['id']}.json"
    content = json.dumps(proposal, indent=2) + "\n"
    if dry_run:
        return (
            0,
            "vault-agent proposal dry run\n"
            f"Would write: {path}\n"
            f"Title: {proposal['title']}\n"
            "No files were changed.",
        )
    if path.exists() and not overwrite_existing:
        return 1, f"vault-agent proposal failed\nError: proposal already exists: {path}"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, content)
    return (
        0,
        "vault-agent proposal complete\n"
        f"Wrote: {path}\n"
        "Review with `vault-agent review-proposals --dry-run`.",
    )


def _write_checkpoint_proposal(
    *,
    config: AgentConfig,
    proposal_id: str,
    title: str,
    folder: str,
    operations: list[dict[str, Any]],
) -> None:
    proposal = {
        "id": proposal_id,
        "title": title,
        "kind": "folder-organization",
        "status": "pending",
        "summary": f"Checkpointed sparse metadata proposal for notes under `{folder}`.",
        "operations": operations,
    }
    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(proposal_dir / f"{proposal_id}.json", json.dumps(proposal, indent=2) + "\n")


def _load_checkpoint_operations(config: AgentConfig, proposal_id: str) -> list[dict[str, Any]]:
    path = config.vault_root / config.paths.review_dir / "proposals" / f"{proposal_id}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    operations = data.get("operations", [])
    if not isinstance(operations, list):
        return []
    return [operation for operation in operations if isinstance(operation, dict)]


def _scoped_cleanup_entries(
    config: AgentConfig, entries: list[dict[str, Any]], folder: str | None
) -> list[dict[str, Any]]:
    prefix = folder.strip("/").rstrip("/") if folder else ""
    scoped: list[dict[str, Any]] = []
    for entry in entries:
        path = entry["path"]
        relative = Path(path)
        if relative.is_relative_to(config.paths.system_dir):
            continue
        if prefix and not path.startswith(prefix + "/"):
            continue
        scoped.append(entry)
    return sorted(
        scoped,
        key=lambda entry: (
            0 if _entry_has_mappable_legacy(entry) else 1,
            entry["path"].lower(),
        ),
    )


def _entry_has_mappable_legacy(entry: dict[str, Any]) -> bool:
    frontmatter = entry.get("frontmatter", {})
    return any(key not in CORE_PROPERTY_ORDER for key in frontmatter) or any(
        entry.get(key) not in (None, "") for key in ("type", "status", "source_kind")
    )


def _cleanup_operation_for_entry(
    *,
    config: AgentConfig,
    path: str,
    remove_unknown: bool,
) -> dict[str, Any] | None:
    note_path = config.vault_root / path
    if not note_path.exists():
        return None
    parsed = parse_note(note_path.read_text(encoding="utf-8"))
    if parsed.error:
        return None
    original = dict(parsed.frontmatter)
    mapped = apply_legacy_mappings(original, config)
    set_values: dict[str, Any] = {}
    for key in CORE_PROPERTY_ORDER:
        if key in mapped and mapped.get(key) != original.get(key):
            set_values[key] = mapped[key]
        elif key not in original and key in mapped:
            set_values[key] = mapped[key]
    note_type = mapped.get("type") if mapped.get("type") in NOTE_TYPES else None
    accepted = accepted_properties_for(note_type)
    remove = sorted(key for key in mapped if key not in accepted) if remove_unknown else []
    if not set_values and not remove:
        return None
    return {
        "op": "update_frontmatter",
        "path": path,
        "set": set_values,
        "remove": remove,
    }


def _index_content(*, index_type: str, title: str, filter_value: str) -> str:
    frontmatter = (
        "---\n"
        "type: index\n"
        "status: active\n"
        "domain:\n"
        "parent:\n"
        "related: []\n"
        "cover:\n"
        "source_kind:\n"
        "capture_type:\n"
        "---\n"
    )
    if index_type == "type":
        filter_expr = f'type == "{filter_value}"'
    elif index_type == "domain":
        filter_expr = f'domain == "{filter_value}"'
    else:
        filter_expr = (
            f'parent == "[[{filter_value}]]" or parent == "{filter_value}"'
        )
    return frontmatter + f"""
# {title}

> [!abstract] Generated Index
> Proposed by `vault-agent propose-index`. Review before applying.

## Summary

This index gathers notes matching `{filter_expr}`.

## Notes

```base
filters:
  and:
    - 'file.ext == "md"'
    - '{filter_expr}'
views:
  - type: table
    name: "Notes"
    order:
      - file.name
      - type
      - status
      - domain
      - parent
      - related
      - file.mtime
```
"""


def _property_definition_markdown(
    *,
    config: AgentConfig | None,
    property_name: str,
    allowed_value: str,
    description: str | None,
) -> str:
    base = _load_current_property_values(config).rstrip()
    lines = [
        base,
        "",
        "## Proposed Additions",
        "",
        "This section was generated by a pending schema-change proposal. Review before approving.",
        "",
        f"- `{property_name}` -> `{allowed_value}`: {description or 'Proposed controlled value.'}",
        "",
    ]
    return "\n".join(lines)


def _load_current_schema(config: AgentConfig | None) -> dict[str, Any]:
    if config is None:
        return default_schema()
    schema_path = config.vault_root / config.paths.agent_dir / "schema.json"
    if not schema_path.exists():
        return default_schema()
    try:
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_schema()
    if not isinstance(loaded, dict):
        return default_schema()
    loaded.setdefault("core_properties", deepcopy(COMMON_PROPERTIES))
    loaded.setdefault("common_properties", deepcopy(COMMON_PROPERTIES))
    return loaded


def _load_current_property_values(config: AgentConfig | None) -> str:
    if config is None:
        return property_values_markdown()
    path = config.vault_root / config.paths.template_dir / "0.021 property values.md"
    if not path.exists():
        return property_values_markdown()
    return path.read_text(encoding="utf-8")


def _resolve_folder(vault_root: Path, folder: str) -> Path:
    target = Path(folder).expanduser()
    if not target.is_absolute():
        target = vault_root / target
    target = target.resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"target folder is outside vault root: {folder}")
    if not target.is_dir():
        raise ValueError(f"target folder does not exist: {folder}")
    return target


def _resolve_note(vault_root: Path, note: str) -> Path:
    target = Path(note).expanduser()
    if not target.is_absolute():
        target = vault_root / target
    target = target.resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"target note is outside vault root: {note}")
    if not target.is_file():
        raise ValueError(f"target note does not exist: {note}")
    if target.suffix.lower() != ".md":
        raise ValueError(f"target note is not a Markdown file: {note}")
    return target


def _llm_type_for_note(
    *,
    provider: ProposalProvider,
    config: AgentConfig,
    note_path: Path,
    note_text: str,
) -> tuple[list[str], str | None]:
    try:
        type_proposal = provider.propose_stage(
            note_path=note_path, note_text=note_text, stage="classify-type"
        )
    except Exception as exc:
        return [str(exc)], None
    type_validation = validate_stage_proposal(
        "classify-type", type_proposal, **schema_stage_extras(config.vault_root)
    )
    if not type_validation.valid:
        return type_validation.errors, None
    if _stage_blocked_by_review(config, type_validation.proposal):
        return ["classify-type confidence is below threshold"], None
    return [], type_validation.proposal["note_type"]


def _stage_blocked_by_review(config: AgentConfig, proposal: dict[str, Any]) -> bool:
    confidence = proposal.get("confidence")
    if (
        isinstance(confidence, (int, float))
        and confidence < config.llm_confidence_threshold
    ):
        return True
    return False


def _approved_type(value: Any) -> str | None:
    return value if isinstance(value, str) and value in NOTE_TYPES else None


def _approved_status(value: Any) -> str | None:
    allowed = COMMON_PROPERTIES["status"]["allowed"]
    return value if isinstance(value, str) and value in allowed else None


def _approved_source_kind(value: Any) -> str | None:
    allowed = COMMON_PROPERTIES["source_kind"]["allowed"]
    return value if isinstance(value, str) and value in allowed else None


def _approved_capture_type(value: Any) -> str | None:
    allowed = COMMON_PROPERTIES["capture_type"]["allowed"]
    return value if isinstance(value, str) and value in allowed else None


def _existing_parent(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _wikilink(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return stripped
    return f"[[{stripped}]]"


def _merged_related(*values: Any) -> list[str]:
    related: list[str] = []
    for value in values:
        for item in _related_items(value):
            if item not in related:
                related.append(item)
    return related


def _related_items(value: Any) -> list[str]:
    if value in (None, "", "None"):
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_related_items(item))
        return result
    text = str(value).strip()
    if not text or text.lower() == "none":
        return []
    if "," in text and not text.startswith("[["):
        return [part for item in text.split(",") for part in _related_items(item)]
    return [text.removeprefix("#").strip()]


def _folder_dashboard_content(
    *,
    title: str,
    project: str,
    project_link: str,
    domain: str,
    folder: str,
) -> str:
    parent_filter = f'(parent == "{project_link}" or parent == "{project}")'
    folder_filter = f'file.path.contains("{folder}")'
    project_filter = f'({parent_filter} or {folder_filter})'
    scope = ['file.ext == "md"', project_filter]
    frontmatter = _dashboard_frontmatter(domain=domain, parent=project_link)
    overview = _base_block(
        filters=scope,
        views=[
            {
                "type": "cards",
                "name": "Project Cards",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "source_kind"],
            },
            {
                "type": "table",
                "name": "All Notes",
                "group_by": ("type", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "domain", "source_kind", "related", "file.mtime"],
            },
        ],
    )
    meetings = _base_block(
        filters=scope + ['type == "meeting"'],
        views=[
            {
                "type": "table",
                "name": "Meetings",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "status", "related", "file.mtime"],
            },
        ],
    )
    sources = _base_block(
        filters=scope + ['(type == "source" or source_kind != "")'],
        views=[
            {
                "type": "cards",
                "name": "Source Cards",
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "source_kind", "status", "related"],
            },
            {
                "type": "table",
                "name": "Source Table",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "source_kind", "status", "file.mtime"],
            },
        ],
    )
    tasks = _base_block(
        filters=scope
        + [
            '(type == "task" or file.name.contains("Task") or file.name.contains("Deliverable"))',
        ],
        views=[
            {
                "type": "table",
                "name": "Tasks And Deliverables",
                "sort": [("status", "ASC"), ("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "related", "file.mtime"],
            },
        ],
    )
    people = _base_block(
        filters=scope
        + [
            '(type == "person" or type == "organization" or file.name.contains("Contact"))',
        ],
        views=[
            {
                "type": "table",
                "name": "People And Organizations",
                "group_by": ("type", "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "type", "status", "related"],
            },
        ],
    )
    return f"""{frontmatter}

# {title}

> [!abstract] {title}
> Project dashboard generated by `vault-agent propose-folder-organization`. Browse this project without moving notes — open in Reading view with the `dashboard` snippet enabled.

## Project Links

- Parent: {project_link}
- Folder: `{folder}`

## Overview

{overview}

## Meetings

{meetings}

## Sources And Research

{sources}

## Tasks And Deliverables

{tasks}

## People And Organizations

{people}
"""


def _title_for_index(index_type: str, label: str) -> str:
    if index_type == "type":
        return f"{label.title()} Index"
    if index_type == "domain":
        return f"{label.title()} Domain"
    return f"{label} Dashboard"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", value).strip()
    return cleaned.replace(" ", "-") or "Index"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "proposal"
