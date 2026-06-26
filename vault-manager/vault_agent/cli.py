"""Command-line interface for the vault agent.

This first skeleton intentionally exposes command routing only. Commands are
non-mutating placeholders until dry-run, validation, backup, and logging
foundations exist.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .config import AgentConfig, load_config

from .action_queue import run_action_plan, run_propose_action_queue
from .artifact_import import ArtifactImportError, submit_artifact
from .autonomous import run_autonomous
from .execution import MassEditBlocked, execute_versioned
from .hermes import run_hermes
from .init import apply_init, render_init_dry_run
from .layout_suggestion import (
    parse_layout_outline,
    parse_layout_routing,
    render_layout_outline,
    suggest_layout,
)
from .llm import (
    OpenAICompatibleProposalProvider,
    JsonFileProposalProvider,
    provider_from_config,
)
from .model_blocks import run_review_model_blocks
from .norms import run_norms_lock
from .obsidian_check import run_obsidian_check
from .organize_pass import run_organize_vault_pass
from .refine import run_propose_folder_refinement
from .processor import PROCESSING_STAGES, run_process_inbox, run_process_next, run_process_vault
from .proposals import (
    run_propose_base_hierarchy,
    run_propose_cleanup_queue,
    run_propose_cleanup,
    run_propose_folder_organization,
    run_propose_index,
    run_propose_inbox_sort,
    run_propose_property,
    run_propose_template,
    run_propose_topic_hubs,
    run_propose_vault_layout,
)
from .readiness import run_organization_readiness
from .reconcile import build_reconcile_plan, run_reconcile
from .retrieval import run_rebuild_retrieval
from .review import load_proposals, run_review_proposals
from .paths import render_bootstrap
from .scanner import run_scan, scan_vault
from .schema_conversation import run_schema_conversation
from .schema_defaults import run_export_schema_defaults, run_import_schema_defaults
from .status import run_status
from .validation import run_validate
from .version_cli import (
    run_version_changed_files,
    run_version_diff,
    run_version_init,
    run_version_log,
    run_version_restore,
    run_version_show,
    run_version_status,
    run_version_undo_run,
)


MAIN_COMMANDS = (
    "init",
    "suggest-layout",
    "apply-layout",
    "scan",
    "validate",
    "process-next",
    "process-inbox",
    "process-vault",
    "reconcile",
    "norms-lock",
    "organize-vault-pass",
    "autonomous-run",
    "organization-readiness",
    "action-plan",
    "propose-index",
    "propose-property",
    "propose-template",
    "propose-topic-hubs",
    "propose-cleanup",
    "propose-cleanup-queue",
    "propose-inbox-sort",
    "propose-vault-layout",
    "propose-base-hierarchy",
    "propose-action-queue",
    "propose-folder-organization",
    "propose-folder-refinement",
    "review-proposals",
    "review-model-blocks",
    "submit-artifact",
    "rebuild-retrieval",
    "status",
    "hermes-run",
    "obsidian-check",
    "schema-conversation",
    "export-schema-defaults",
    "import-schema-defaults",
    "version",
)

MAIN_COMMAND_HELP = {
    "init": "Preview or initialize vault-agent folders and starter files.",
    "suggest-layout": "Propose a folder layout from existing folders and notes before init.",
    "apply-layout": "Write the edited folder-layout outline to the vault bootstrap config.",
    "scan": "Scan Markdown notes and update generated manifest/catalog files.",
    "validate": "Validate notes and write review queues.",
    "process-next": "Process one eligible note from the configured inbox.",
    "process-inbox": "Process a bounded batch from the configured inbox.",
    "process-vault": "Process a bounded batch of eligible non-system, non-inbox notes.",
    "reconcile": "Apply approved property defaults and template sections across the vault.",
    "norms-lock": "Create or preview the generated vault norms lock.",
    "organize-vault-pass": "Run a bounded lock-aware organization pass and report.",
    "autonomous-run": "Run bounded autonomous maintenance and write an audit report.",
    "organization-readiness": "Report whether a vault is ready for a bounded organization pass.",
    "action-plan": "Report proposal-first maintenance actions available for this vault.",
    "propose-index": "Generate a pending proposal for an index note.",
    "propose-property": "Generate a pending proposal for a canonical property value.",
    "propose-template": "Generate a pending proposal for a note-type template refresh.",
    "propose-topic-hubs": "Surface candidate topic hubs from vault notes into the approved registry.",
    "propose-cleanup": "Generate a pending proposal for one note frontmatter cleanup.",
    "propose-cleanup-queue": "Generate bounded cleanup proposals from validation groups.",
    "propose-inbox-sort": "Generate bounded deterministic inbox move proposals.",
    "propose-vault-layout": "Generate a reviewed dashboard-first layout migration proposal.",
    "propose-base-hierarchy": "Generate hierarchical Bases dashboard proposals.",
    "propose-action-queue": "Generate a pending proposal for queued maintenance actions.",
    "propose-folder-organization": "Generate a pending proposal to organize one folder and dashboard.",
    "propose-folder-refinement": "Generate note-body refinement proposals for a folder using the configured LLM, guarded so wording never changes.",
    "review-proposals": "Validate and apply approved deterministic proposal files.",
    "review-model-blocks": "Review blocked model stage proposals and convert safe ones.",
    "submit-artifact": "Create a validated pending proposal for an external text artifact.",
    "rebuild-retrieval": "Regenerate deterministic retrieval files.",
    "status": "Show vault-agent health and inbox status.",
    "hermes-run": "Run scheduled maintenance across vaults in a Hermes directory.",
    "obsidian-check": "Validate frontmatter and embedded Bases for Obsidian compatibility.",
    "schema-conversation": "Turn a schema/onboarding transcript into reviewable proposals.",
    "export-schema-defaults": "Export editable Markdown vault defaults.",
    "import-schema-defaults": "Import editable Markdown defaults as pending proposals.",
    "version": "Inspect, snapshot, diff, and roll back Git-backed agent changes.",
}

MEMORY_COMMANDS = (
    "init",
    "scan",
    "validate",
    "ingest-chat",
    "ingest-vault",
    "extract",
    "consolidate",
    "rebuild",
    "retrieve",
    "status",
    "expire",
    "review",
)


def _add_shared_options(
    parser: argparse.ArgumentParser, *, defaults: bool = True
) -> None:
    default = None if defaults else argparse.SUPPRESS
    parser.add_argument(
        "--vault-root",
        default="." if defaults else argparse.SUPPRESS,
        help="Path to the Obsidian vault root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--config",
        default=default,
        help="Optional path to an agent config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="Preview planned actions without writing files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="Show additional diagnostic output.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault-agent",
        description="Local-first Obsidian vault management and retrieval agent.",
    )
    _add_shared_options(parser)

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for command in MAIN_COMMANDS:
        command_parser = subparsers.add_parser(
            command,
            help=MAIN_COMMAND_HELP[command],
        )
        _add_shared_options(command_parser, defaults=False)
        if command == "init":
            command_parser.add_argument(
                "--system-dir",
                default=None,
                help="Vault-relative folder for pi-vault state, templates, and reports.",
            )
            command_parser.add_argument(
                "--inbox-dir",
                default=None,
                help="Vault-relative inbox folder for captured notes.",
            )
            command_parser.set_defaults(handler=_handle_init)
        elif command == "suggest-layout":
            command_parser.set_defaults(handler=_handle_suggest_layout)
        elif command == "apply-layout":
            command_parser.add_argument(
                "--file",
                default=None,
                help="Path to the edited layout outline. Defaults to .pi-vault/layout-suggestion.yaml.",
            )
            command_parser.set_defaults(handler=_handle_apply_layout)
        elif command == "scan":
            command_parser.set_defaults(handler=_handle_scan)
        elif command == "validate":
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
                help="Render machine-readable validation groups and counts.",
            )
            command_parser.set_defaults(handler=_handle_validate)
        elif command == "process-next":
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES)
            command_parser.add_argument(
                "--note",
                help="Specific Markdown note path to process, relative to the vault root.",
            )
            command_parser.add_argument(
                "--proposal-file",
                help="Path to structured LLM proposal JSON for the selected note.",
            )
            command_parser.set_defaults(handler=_handle_process_next)
        elif command == "process-inbox":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES)
            command_parser.add_argument(
                "--note",
                help="Specific inbox note path to process, relative to the vault root.",
            )
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument("--max-runtime-minutes", type=int)
            command_parser.add_argument(
                "--proposal-file",
                help="Path to structured LLM proposal JSON. Intended for single-note runs.",
            )
            command_parser.set_defaults(handler=_handle_process_inbox)
        elif command == "process-vault":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES)
            command_parser.add_argument(
                "--note",
                help="Specific vault note path to process, relative to the vault root.",
            )
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument("--max-runtime-minutes", type=int)
            command_parser.add_argument(
                "--proposal-file",
                help="Path to structured LLM proposal JSON. Intended for single-note runs.",
            )
            command_parser.set_defaults(handler=_handle_process_vault)
        elif command == "reconcile":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument(
                "--properties-only",
                action="store_true",
                help="Backfill sparse core properties without inserting template body sections.",
            )
            command_parser.set_defaults(handler=_handle_reconcile)
        elif command == "norms-lock":
            command_parser.add_argument(
                "--write",
                action="store_true",
                help="Write the generated norms lock. Without this, preview only.",
            )
            command_parser.set_defaults(handler=_handle_norms_lock)
        elif command == "organize-vault-pass":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES)
            command_parser.add_argument(
                "--folder",
                help="Optional folder path to scope the pass, relative to the vault root.",
            )
            command_parser.add_argument(
                "--note",
                help="Optional Markdown note path to process, relative to the vault root.",
            )
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument("--max-runtime-minutes", type=int)
            command_parser.add_argument(
                "--use-llm",
                action="store_true",
                help="Use the configured LLM provider for semantic stages.",
            )
            command_parser.add_argument(
                "--create-lock",
                action="store_true",
                help="Create norms-lock.json first if it does not exist.",
            )
            command_parser.set_defaults(handler=_handle_organize_vault_pass)
        elif command == "autonomous-run":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow scheduled changes over configured thresholds.",
            )
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES)
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument(
                "--max-proposal-operations",
                type=int,
                default=10,
                help="Maximum operations for safe proposal auto-approval.",
            )
            command_parser.add_argument(
                "--use-llm",
                action="store_true",
                help="Use the configured LLM provider for semantic organization stages.",
            )
            command_parser.add_argument(
                "--create-lock",
                action="store_true",
                help="Create norms-lock.json first if it does not exist.",
            )
            command_parser.add_argument(
                "--apply-safe",
                action="store_true",
                help="Auto-approve/apply bounded safe non-schema proposals.",
            )
            command_parser.add_argument(
                "--report-format",
                choices=("markdown", "json", "both"),
                default="both",
            )
            command_parser.set_defaults(handler=_handle_autonomous_run)
        elif command == "organization-readiness":
            command_parser.add_argument(
                "--folder",
                help="Optional folder path to scope readiness, relative to the vault root.",
            )
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
                help="Render machine-readable readiness data.",
            )
            command_parser.set_defaults(handler=_handle_organization_readiness)
        elif command == "action-plan":
            command_parser.add_argument(
                "--folder",
                help="Optional folder path to scope the action plan, relative to the vault root.",
            )
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
                help="Render machine-readable JSON for chat agents.",
            )
            command_parser.set_defaults(handler=_handle_action_plan)
        elif command == "propose-index":
            command_parser.add_argument(
                "--index-type",
                choices=("type", "project", "parent", "domain"),
                required=True,
                help="Index filter shape to propose.",
            )
            command_parser.add_argument(
                "--value",
                required=True,
                help="Type, domain, project, or parent value to index.",
            )
            command_parser.add_argument("--title", help="Optional index note title.")
            command_parser.add_argument(
                "--output-path",
                help="Optional proposed output path relative to the vault root.",
            )
            command_parser.add_argument(
                "--overwrite",
                action="store_true",
                help="Generate proposal with if_exists overwrite.",
            )
            command_parser.set_defaults(handler=_handle_propose_index)
        elif command == "propose-property":
            command_parser.add_argument(
                "--property",
                required=True,
                help="Controlled core property to extend, e.g. domain.",
            )
            command_parser.add_argument(
                "--value",
                required=True,
                help="Proposed controlled value.",
            )
            command_parser.add_argument(
                "--description",
                help="Human-readable description for the proposed value.",
            )
            command_parser.add_argument(
                "--no-overwrite",
                action="store_true",
                help="Generate proposal operations with if_exists fail.",
            )
            command_parser.set_defaults(handler=_handle_propose_property)
        elif command == "propose-template":
            command_parser.add_argument(
                "--note-type",
                required=True,
                help="Note type whose template should be refreshed.",
            )
            command_parser.add_argument(
                "--no-overwrite",
                action="store_true",
                help="Generate proposal operation with if_exists fail.",
            )
            command_parser.set_defaults(handler=_handle_propose_template)
        elif command == "propose-topic-hubs":
            command_parser.add_argument(
                "--domain",
                help="Limit hub surfacing to one domain (default: all populated domains).",
            )
            command_parser.add_argument(
                "--min-cluster",
                type=int,
                default=3,
                help="Minimum notes in a folder cluster before it becomes a candidate hub.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing topic-hubs proposal with the same id.",
            )
            command_parser.set_defaults(handler=_handle_propose_topic_hubs)
        elif command == "propose-cleanup":
            command_parser.add_argument(
                "--note",
                required=True,
                help="Markdown note path to propose cleanup for, relative to the vault root.",
            )
            command_parser.add_argument(
                "--remove-unknown",
                action="store_true",
                help="Include non-core frontmatter properties in the removal list.",
            )
            command_parser.set_defaults(handler=_handle_propose_cleanup)
        elif command == "propose-cleanup-queue":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument(
                "--folder",
                help="Optional folder path to scope queued cleanup, relative to the vault root.",
            )
            command_parser.add_argument(
                "--max-items",
                type=int,
                default=25,
                help="Maximum cleanup operations to include in the generated proposal.",
            )
            command_parser.add_argument(
                "--remove-unknown",
                action="store_true",
                help="Include non-core frontmatter properties in removal lists.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing cleanup-queue proposal with the same id.",
            )
            command_parser.set_defaults(handler=_handle_propose_cleanup_queue)
        elif command == "propose-base-hierarchy":
            command_parser.add_argument(
                "--output-root",
                help="Dashboard output folder relative to the vault root (default: configured dashboards folder).",
            )
            command_parser.add_argument(
                "--min-child-notes",
                type=int,
                default=2,
                help="Minimum child notes required before creating a parent dashboard.",
            )
            command_parser.add_argument(
                "--use-llm",
                action="store_true",
                help="Use the configured LLM for bounded coverage wording.",
            )
            command_parser.add_argument(
                "--llm-limit",
                type=int,
                default=3,
                help="Maximum domains to include in the optional coverage wording prompt.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing base hierarchy proposal with the same id.",
            )
            command_parser.set_defaults(handler=_handle_propose_base_hierarchy)
        elif command == "propose-inbox-sort":
            command_parser.add_argument("--max-notes", type=int, default=5)
            command_parser.add_argument(
                "--safe-only",
                action="store_true",
                help="Include only notes with current norms and high-confidence completed model stages.",
            )
            command_parser.add_argument("--overwrite-proposal", action="store_true")
            command_parser.set_defaults(handler=_handle_propose_inbox_sort)
        elif command == "propose-vault-layout":
            command_parser.add_argument("--overwrite-proposal", action="store_true")
            command_parser.set_defaults(handler=_handle_propose_vault_layout)
        elif command == "propose-action-queue":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument(
                "--actions",
                required=True,
                help="Comma-separated actions: transcript,people,categorization.",
            )
            command_parser.add_argument(
                "--folder",
                help="Optional folder path to scope queued actions, relative to the vault root.",
            )
            command_parser.add_argument(
                "--use-llm",
                action="store_true",
                help="Use the configured LLM for bounded transcript/categorization proposal enrichment.",
            )
            command_parser.add_argument(
                "--llm-limit",
                type=int,
                default=1,
                help="Maximum notes to consult with the configured LLM.",
            )
            command_parser.add_argument(
                "--max-items",
                type=int,
                help="Maximum queued items per action to include in the generated proposal.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing action-queue proposal with the same id.",
            )
            command_parser.add_argument(
                "--checkpoint",
                action="store_true",
                help="Reserve checkpointing for long LLM-backed queue generation.",
            )
            command_parser.add_argument(
                "--resume",
                action="store_true",
                help="Reserve resume behavior for checkpointed queue generation.",
            )
            command_parser.set_defaults(handler=_handle_propose_action_queue)
        elif command == "propose-folder-organization":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow changes over configured mass-edit thresholds.",
            )
            command_parser.add_argument(
                "--folder",
                required=True,
                help="Folder path to organize, relative to the vault root.",
            )
            command_parser.add_argument(
                "--project",
                required=True,
                help="Project parent note name or wikilink.",
            )
            command_parser.add_argument(
                "--domain",
                required=True,
                help="Approved domain value to apply to organized notes.",
            )
            command_parser.add_argument(
                "--dashboard-title",
                help="Optional dashboard note title.",
            )
            command_parser.add_argument(
                "--dashboard-path",
                help="Optional dashboard output path relative to the vault root.",
            )
            command_parser.add_argument(
                "--no-overwrite-dashboard",
                action="store_true",
                help="Generate dashboard write with if_exists fail.",
            )
            command_parser.add_argument(
                "--use-llm",
                action="store_true",
                help="Use the configured LLM backend for bounded semantic decisions.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing folder organization proposal with the same id.",
            )
            command_parser.add_argument(
                "--remove-legacy",
                action="store_true",
                help="Remove non-core frontmatter properties in the generated organization proposal.",
            )
            command_parser.add_argument(
                "--checkpoint",
                action="store_true",
                help="Write the proposal after each processed note and print progress.",
            )
            command_parser.add_argument(
                "--resume",
                action="store_true",
                help="Reuse completed organize_note operations from an existing checkpoint proposal.",
            )
            command_parser.add_argument(
                "--llm-limit",
                type=int,
                default=3,
                help="Maximum notes to consult the configured LLM for when --use-llm is set.",
            )
            command_parser.set_defaults(handler=_handle_propose_folder_organization)
        elif command == "propose-folder-refinement":
            command_parser.add_argument(
                "--folder",
                help="Folder path to refine, relative to the vault root.",
            )
            command_parser.add_argument(
                "--note",
                help="Single note path to refine, relative to the vault root.",
            )
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument("--max-runtime-minutes", type=int)
            command_parser.set_defaults(handler=_handle_propose_folder_refinement)
        elif command == "review-proposals":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow applying proposals over configured mass-edit thresholds.",
            )
            command_parser.add_argument(
                "--apply-approved",
                action="store_true",
                help="Apply proposals whose status is approved.",
            )
            command_parser.add_argument(
                "--agent-review",
                action="store_true",
                help="Render an agent-oriented proposal review report.",
            )
            command_parser.add_argument(
                "--approve-safe",
                action="store_true",
                help="Mark valid bounded pending proposals approved without applying them.",
            )
            command_parser.add_argument(
                "--max-operations",
                type=int,
                default=25,
                help="Maximum operations a proposal may contain for agent safe approval.",
            )
            command_parser.add_argument(
                "--include-schema",
                action="store_true",
                help="Allow agent safe approval of schema-change proposals.",
            )
            command_parser.add_argument(
                "--proposal-dir",
                help="Proposal directory. Defaults to the configured system review/proposals folder.",
            )
            command_parser.set_defaults(handler=_handle_review_proposals)
        elif command == "submit-artifact":
            command_parser.add_argument("--source-path", required=True)
            command_parser.add_argument("--read-root", action="append", required=True)
            command_parser.add_argument("--suggested-name")
            command_parser.add_argument("--title")
            command_parser.add_argument("--source-task-id")
            command_parser.add_argument("--source-operation")
            command_parser.add_argument("--json", action="store_true", dest="json_output")
            command_parser.set_defaults(handler=_handle_submit_artifact)
        elif command == "rebuild-retrieval":
            command_parser.set_defaults(handler=_handle_rebuild_retrieval)
        elif command == "status":
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
                help="Render machine-readable vault status.",
            )
            command_parser.set_defaults(handler=_handle_status)
        elif command == "hermes-run":
            command_parser.add_argument(
                "--mass-edit",
                action="store_true",
                help="Explicitly allow scheduled vault changes over configured thresholds.",
            )
            command_parser.add_argument("--hermes-root", required=True)
            command_parser.add_argument("--max-notes", type=int)
            command_parser.add_argument(
                "--apply-safe",
                action="store_true",
                help="Auto-approve/apply bounded safe proposals in each scheduled vault.",
            )
            command_parser.add_argument(
                "--max-proposal-operations",
                type=int,
                default=10,
                help="Maximum operations for safe proposal auto-approval.",
            )
            command_parser.set_defaults(handler=_handle_hermes_run)
        elif command == "obsidian-check":
            command_parser.add_argument(
                "--live-obsidian",
                action="store_true",
                help="Run optional Obsidian CLI checks when Obsidian is available.",
            )
            command_parser.add_argument(
                "--require-live",
                action="store_true",
                help="Fail when live Obsidian checks cannot run.",
            )
            command_parser.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
                help="Render machine-readable compatibility results.",
            )
            command_parser.set_defaults(handler=_handle_obsidian_check)
        elif command == "schema-conversation":
            command_parser.add_argument(
                "--conversation-file",
                required=True,
                help="Markdown, JSON, or YAML transcript file to convert into proposals.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace existing generated proposal files.",
            )
            command_parser.add_argument(
                "--include-current-schema-summary",
                action="store_true",
                help="Include current controlled values in the generated summary.",
            )
            command_parser.set_defaults(handler=_handle_schema_conversation)
        elif command == "export-schema-defaults":
            command_parser.add_argument(
                "--output",
                required=True,
                help="Markdown output path for the editable vault defaults contract.",
            )
            command_parser.set_defaults(handler=_handle_export_schema_defaults)
        elif command == "import-schema-defaults":
            command_parser.add_argument(
                "--schema-file",
                required=True,
                help="Edited Markdown defaults file to convert into a pending proposal.",
            )
            command_parser.add_argument(
                "--overwrite-proposal",
                action="store_true",
                help="Replace an existing vault-schema-defaults proposal.",
            )
            command_parser.set_defaults(handler=_handle_import_schema_defaults)
        elif command == "review-model-blocks":
            command_parser.add_argument(
                "--approve-safe",
                action="store_true",
                help="Convert selected blocked model proposals into pending review proposals.",
            )
            command_parser.add_argument("--note", help="Only review one note path.")
            command_parser.add_argument("--stage", choices=PROCESSING_STAGES, help="Only review one stage.")
            command_parser.set_defaults(handler=_handle_review_model_blocks)
        elif command == "version":
            version_subparsers = command_parser.add_subparsers(
                dest="version_command", metavar="version-command"
            )
            init_parser = version_subparsers.add_parser("init", help="Initialize Git versioning.")
            _add_shared_options(init_parser, defaults=False)
            init_parser.set_defaults(handler=_handle_version_init)
            status_parser = version_subparsers.add_parser("status", help="Show Git version status.")
            _add_shared_options(status_parser, defaults=False)
            status_parser.set_defaults(handler=_handle_version_status)
            log_parser = version_subparsers.add_parser("log", help="Show recent runs and commits.")
            _add_shared_options(log_parser, defaults=False)
            log_parser.add_argument("--limit", type=int, default=20)
            log_parser.set_defaults(handler=_handle_version_log)
            show_parser = version_subparsers.add_parser("show", help="Show a run or commit.")
            _add_shared_options(show_parser, defaults=False)
            show_parser.add_argument("target")
            show_parser.set_defaults(handler=_handle_version_show)
            diff_parser = version_subparsers.add_parser("diff", help="Show a run or commit diff.")
            _add_shared_options(diff_parser, defaults=False)
            diff_parser.add_argument("target")
            diff_parser.set_defaults(handler=_handle_version_diff)
            changed_parser = version_subparsers.add_parser(
                "changed-files", help="List paths affected by a run or commit."
            )
            _add_shared_options(changed_parser, defaults=False)
            changed_parser.add_argument("target")
            changed_parser.set_defaults(handler=_handle_version_changed_files)
            restore_parser = version_subparsers.add_parser(
                "restore", help="Restore one path or all paths for a run."
            )
            _add_shared_options(restore_parser, defaults=False)
            restore_parser.add_argument("target")
            restore_parser.add_argument("--path", action="append", dest="paths", default=[])
            restore_parser.add_argument("--all", action="store_true", dest="all_paths")
            restore_parser.add_argument("--force", action="store_true")
            restore_parser.set_defaults(handler=_handle_version_restore)
            undo_parser = version_subparsers.add_parser(
                "undo-run", help="Restore only files touched by a run."
            )
            _add_shared_options(undo_parser, defaults=False)
            undo_parser.add_argument("run_id")
            undo_parser.add_argument("--force", action="store_true")
            undo_parser.set_defaults(handler=_handle_version_undo_run)
        else:
            command_parser.set_defaults(handler=_handle_placeholder)

    memory_parser = subparsers.add_parser(
        "memory",
        help="Memory-layer command group.",
    )
    _add_shared_options(memory_parser, defaults=False)
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_command",
        metavar="memory-command",
    )
    for command in MEMORY_COMMANDS:
        command_parser = memory_subparsers.add_parser(
            command,
            help=f"Placeholder for vault-agent memory {command}.",
        )
        _add_shared_options(command_parser, defaults=False)
        command_parser.set_defaults(handler=_handle_memory_placeholder)

    return parser


def _print_config_diagnostics(config: AgentConfig) -> None:
    if not config.verbose:
        return

    print(f"Vault root: {config.vault_root}")
    print(f"System folder: {config.paths.system_dir}")
    print(f"Inbox folder: {config.paths.inbox_dir}")
    print(f"Config path: {config.config_path if config.config_path else '(none)'}")
    print(f"Dry run: {config.dry_run}")


def _handle_placeholder(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    print(
        f"vault-agent {args.command} is planned but not implemented yet. "
        "No files were changed."
    )
    return 0


def _handle_init(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    if config.dry_run:
        print(render_init_dry_run(config))
        return 0

    exit_code, output = apply_init(config)
    print(output)
    return exit_code


LAYOUT_SUGGESTION_FILE = Path(".pi-vault") / "layout-suggestion.yaml"
BOOTSTRAP_CONFIG_FILE = Path(".pi-vault") / "config.yaml"


def _handle_suggest_layout(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    scan = scan_vault(config.vault_root)
    suggestion = suggest_layout(scan, config.paths)
    outline = render_layout_outline(suggestion)

    if config.dry_run:
        print("vault-agent suggest-layout dry run")
        print("No files were changed. Proposed outline:\n")
        print(outline)
        return 0

    target = config.vault_root / LAYOUT_SUGGESTION_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(outline, encoding="utf-8")
    print("vault-agent suggest-layout complete")
    print(f"Wrote proposed layout to {LAYOUT_SUGGESTION_FILE.as_posix()}")
    print(
        "Review and edit it, then run `vault-agent apply-layout` followed by "
        "`vault-agent init`."
    )
    return 0


def _handle_apply_layout(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    file_arg = getattr(args, "file", None)
    outline_path = (
        Path(file_arg).expanduser()
        if file_arg
        else config.vault_root / LAYOUT_SUGGESTION_FILE
    )
    if not outline_path.exists():
        print("vault-agent apply-layout failed")
        print(f"Error: layout outline not found: {outline_path}")
        print("Run `vault-agent suggest-layout` first, or pass --file.")
        return 1

    outline_text = outline_path.read_text(encoding="utf-8")
    paths = parse_layout_outline(outline_text)
    routing = parse_layout_routing(outline_text)
    bootstrap = render_bootstrap(paths, routing=routing)

    if config.dry_run:
        print("vault-agent apply-layout dry run")
        print("No files were changed. Resolved bootstrap config:\n")
        print(bootstrap)
        return 0

    target = config.vault_root / BOOTSTRAP_CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bootstrap, encoding="utf-8")
    print("vault-agent apply-layout complete")
    print(f"Wrote vault bootstrap to {BOOTSTRAP_CONFIG_FILE.as_posix()}")
    print("Run `vault-agent init` to create the folders.")
    return 0


def _handle_scan(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_scan(config)
    print(output)
    return exit_code


def _handle_validate(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_validate(
        config,
        json_output=bool(getattr(args, "json_output", False)),
    )
    print(output)
    return exit_code


def _handle_process_next(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_process_next(
        config,
        proposal_provider=(
            _proposal_provider_from_args(args)
            or _proposal_provider_from_config(config)
        ),
        stage=getattr(args, "stage", None),
        note=getattr(args, "note", None),
    )
    print(output)
    return exit_code


def _handle_process_inbox(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_process_inbox(
        config,
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_runtime_minutes=(
            args.max_runtime_minutes
            if args.max_runtime_minutes is not None
            else config.max_runtime_minutes
        ),
        proposal_provider=(
            _proposal_provider_from_args(args)
            or _proposal_provider_from_config(config)
        ),
        stage=getattr(args, "stage", None),
        note=getattr(args, "note", None),
    )
    print(output)
    return exit_code


def _handle_process_vault(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_process_vault(
        config,
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_runtime_minutes=(
            args.max_runtime_minutes
            if args.max_runtime_minutes is not None
            else config.max_runtime_minutes
        ),
        proposal_provider=(
            _proposal_provider_from_args(args)
            or _proposal_provider_from_config(config)
        ),
        stage=getattr(args, "stage", None),
        note=getattr(args, "note", None),
    )
    print(output)
    return exit_code


def _handle_rebuild_retrieval(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_rebuild_retrieval(config)
    print(output)
    return exit_code


def _handle_reconcile(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_reconcile(
        config, properties_only=bool(getattr(args, "properties_only", False))
    )
    print(output)
    return exit_code


def _handle_norms_lock(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_norms_lock(config, write=bool(getattr(args, "write", False)))
    print(output)
    return exit_code


def _handle_organize_vault_pass(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    proposal_provider = None
    if bool(getattr(args, "use_llm", False)):
        proposal_provider = _proposal_provider_from_config(config)
        if proposal_provider is None:
            print(
                "vault-agent organize-vault-pass failed\n"
                "Error: --use-llm requires llm.enabled and a supported provider in config."
            )
            return 1
    exit_code, output = run_organize_vault_pass(
        config,
        proposal_provider=proposal_provider,
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_runtime_minutes=(
            args.max_runtime_minutes
            if args.max_runtime_minutes is not None
            else config.max_runtime_minutes
        ),
        folder=getattr(args, "folder", None),
        note=getattr(args, "note", None),
        stage=getattr(args, "stage", None),
        create_lock=bool(getattr(args, "create_lock", False)),
    )
    print(output)
    return exit_code


def _handle_autonomous_run(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    proposal_provider = None
    if bool(getattr(args, "use_llm", False)):
        proposal_provider = _proposal_provider_from_config(config)
        if proposal_provider is None:
            print(
                "vault-agent autonomous-run failed\n"
                "Error: --use-llm requires llm.enabled and a supported provider in config."
            )
            return 1
    exit_code, output = run_autonomous(
        config,
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_proposal_operations=int(getattr(args, "max_proposal_operations", 10)),
        stage=getattr(args, "stage", None),
        proposal_provider=proposal_provider,
        create_lock=bool(getattr(args, "create_lock", False)),
        apply_safe=bool(getattr(args, "apply_safe", False)),
        report_format=getattr(args, "report_format", "both"),
    )
    print(output)
    return exit_code


def _handle_review_model_blocks(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_review_model_blocks(
        config,
        note=getattr(args, "note", None),
        stage=getattr(args, "stage", None),
        approve_safe=bool(getattr(args, "approve_safe", False)),
    )
    print(output)
    return exit_code


def _handle_organization_readiness(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_organization_readiness(
        config,
        folder=getattr(args, "folder", None),
        json_output=bool(getattr(args, "json_output", False)),
    )
    print(output)
    return exit_code


def _handle_action_plan(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_action_plan(
        config,
        folder=getattr(args, "folder", None),
        json_output=bool(getattr(args, "json_output", False)),
    )
    print(output)
    return exit_code


def _handle_review_proposals(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_review_proposals(
        config,
        apply_approved=bool(getattr(args, "apply_approved", False)),
        agent_review=bool(getattr(args, "agent_review", False)),
        approve_safe=bool(getattr(args, "approve_safe", False)),
        max_operations=int(getattr(args, "max_operations", 25)),
        include_schema=bool(getattr(args, "include_schema", False)),
        proposal_dir=getattr(args, "proposal_dir", None),
    )
    print(output)
    return exit_code


def _handle_submit_artifact(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    try:
        result = submit_artifact(
            config,
            source_path=args.source_path,
            read_roots=list(args.read_root),
            suggested_name=args.suggested_name,
            title=args.title,
            source_task_id=args.source_task_id,
            source_operation=args.source_operation,
        )
    except ArtifactImportError as exc:
        print(json.dumps({"schemaVersion": 1, "status": "failed", "error": {"code": exc.code, "message": str(exc)}}))
        return 1
    print(json.dumps(result) if args.json_output else json.dumps(result, indent=2))
    return 0


def _handle_propose_index(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    try:
        exit_code, output = run_propose_index(
            config,
            index_type=args.index_type,
            title=args.title,
            filter_value=args.value,
            output_path=args.output_path,
            overwrite=bool(args.overwrite),
        )
    except ValueError as exc:
        exit_code, output = 1, f"vault-agent propose-index failed\nError: {exc}"
    print(output)
    return exit_code


def _handle_propose_property(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_property(
        config,
        property_name=args.property,
        allowed_value=args.value,
        description=args.description,
        overwrite=not bool(args.no_overwrite),
    )
    print(output)
    return exit_code


def _handle_propose_template(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_template(
        config,
        note_type=args.note_type,
        overwrite=not bool(args.no_overwrite),
    )
    print(output)
    return exit_code


def _handle_propose_topic_hubs(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_topic_hubs(
        config,
        domain=getattr(args, "domain", None),
        min_cluster=int(getattr(args, "min_cluster", 3)),
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
    )
    print(output)
    return exit_code


def _handle_propose_cleanup(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_cleanup(
        config,
        note=args.note,
        remove_unknown=bool(args.remove_unknown),
    )
    print(output)
    return exit_code


def _handle_propose_cleanup_queue(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_cleanup_queue(
        config,
        folder=getattr(args, "folder", None),
        max_items=int(getattr(args, "max_items", 25)),
        remove_unknown=bool(getattr(args, "remove_unknown", False)),
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
    )
    print(output)
    return exit_code


def _handle_propose_base_hierarchy(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    proposal_provider = None
    if bool(getattr(args, "use_llm", False)):
        proposal_provider = _proposal_provider_from_config(config)
        if proposal_provider is None:
            print(
                "vault-agent propose-base-hierarchy failed\n"
                "Error: --use-llm requires llm.enabled and a supported provider in config."
            )
            return 1
    exit_code, output = run_propose_base_hierarchy(
        config,
        output_root=getattr(args, "output_root", None),
        min_child_notes=int(getattr(args, "min_child_notes", 2)),
        proposal_provider=proposal_provider,
        llm_limit=int(getattr(args, "llm_limit", 0)) if proposal_provider else 0,
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
    )
    print(output)
    return exit_code


def _handle_propose_inbox_sort(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_inbox_sort(
        config,
        max_notes=int(getattr(args, "max_notes", 5)),
        safe_only=bool(getattr(args, "safe_only", False)),
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
    )
    print(output)
    return exit_code


def _handle_propose_vault_layout(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_propose_vault_layout(
        config,
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
    )
    print(output)
    return exit_code


def _handle_propose_action_queue(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    proposal_provider = None
    if bool(getattr(args, "use_llm", False)):
        proposal_provider = _proposal_provider_from_config(config)
        if proposal_provider is None:
            print(
                "vault-agent propose-action-queue failed\n"
                "Error: --use-llm requires llm.enabled and a supported provider in config."
            )
            return 1
    exit_code, output = run_propose_action_queue(
        config,
        actions=args.actions,
        folder=getattr(args, "folder", None),
        use_llm=bool(getattr(args, "use_llm", False)),
        llm_limit=int(getattr(args, "llm_limit", 0)),
        max_items=getattr(args, "max_items", None),
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
        checkpoint=bool(getattr(args, "checkpoint", False)),
        resume=bool(getattr(args, "resume", False)),
        proposal_provider=proposal_provider,
    )
    print(output)
    return exit_code


def _handle_propose_folder_organization(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    proposal_provider = None
    if bool(args.use_llm):
        proposal_provider = _proposal_provider_from_config(config)
        if proposal_provider is None:
            print(
                "vault-agent propose-folder-organization failed\n"
                "Error: --use-llm requires llm.enabled and a supported provider in config."
            )
            return 1
    exit_code, output = run_propose_folder_organization(
        config,
        folder=args.folder,
        project=args.project,
        domain=args.domain,
        dashboard_title=args.dashboard_title,
        dashboard_path=args.dashboard_path,
        overwrite_dashboard=not bool(args.no_overwrite_dashboard),
        proposal_provider=proposal_provider,
        llm_limit=args.llm_limit if bool(args.use_llm) else 0,
        overwrite_proposal=bool(args.overwrite_proposal),
        remove_legacy=bool(args.remove_legacy),
        checkpoint=bool(args.checkpoint),
        resume=bool(args.resume),
    )
    print(output)
    return exit_code


def _handle_propose_folder_refinement(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    if not args.folder and not args.note:
        print(
            "vault-agent propose-folder-refinement failed\n"
            "Error: pass --folder or --note to choose what to refine."
        )
        return 1
    proposal_provider = _proposal_provider_from_config(config)
    exit_code, output = run_propose_folder_refinement(
        config,
        folder=args.folder,
        note=args.note,
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_runtime_minutes=(
            args.max_runtime_minutes
            if args.max_runtime_minutes is not None
            else config.max_runtime_minutes
        ),
        proposal_provider=proposal_provider,
    )
    print(output)
    return exit_code


def _handle_status(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_status(
        config, json_output=bool(getattr(args, "json_output", False))
    )
    print(output)
    return exit_code


def _handle_hermes_run(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_hermes(
        config,
        hermes_root=Path(args.hermes_root),
        max_notes=args.max_notes if args.max_notes is not None else config.max_notes,
        max_proposal_operations=int(getattr(args, "max_proposal_operations", 10)),
        apply_safe=bool(getattr(args, "apply_safe", False)),
        mass_edit=bool(getattr(args, "mass_edit", False)),
    )
    print(output)
    return exit_code


def _handle_obsidian_check(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_obsidian_check(
        config,
        live_obsidian=bool(getattr(args, "live_obsidian", False)),
        require_live=bool(getattr(args, "require_live", False)),
        json_output=bool(getattr(args, "json_output", False)),
    )
    print(output)
    return exit_code


def _handle_schema_conversation(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_schema_conversation(
        config,
        conversation_file=args.conversation_file,
        overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
        include_current_schema_summary=bool(getattr(args, "include_current_schema_summary", False)),
    )
    print(output)
    return exit_code


def _handle_export_schema_defaults(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    try:
        exit_code, output = run_export_schema_defaults(config, output=args.output)
    except ValueError as exc:
        exit_code, output = 1, f"vault-agent export-schema-defaults failed\nError: {exc}"
    print(output)
    return exit_code


def _handle_import_schema_defaults(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    try:
        exit_code, output = run_import_schema_defaults(
            config,
            schema_file=args.schema_file,
            overwrite_proposal=bool(getattr(args, "overwrite_proposal", False)),
        )
    except ValueError as exc:
        exit_code, output = 1, f"vault-agent import-schema-defaults failed\nError: {exc}"
    print(output)
    return exit_code


def _handle_version_init(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_init(config)
    print(output)
    return exit_code


def _handle_version_status(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_status(config)
    print(output)
    return exit_code


def _handle_version_log(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_log(config, limit=int(getattr(args, "limit", 20)))
    print(output)
    return exit_code


def _handle_version_show(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_show(config, args.target)
    print(output)
    return exit_code


def _handle_version_diff(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_diff(config, args.target)
    print(output)
    return exit_code


def _handle_version_changed_files(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_changed_files(config, args.target)
    print(output)
    return exit_code


def _handle_version_restore(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_restore(
        config,
        args.target,
        paths=list(getattr(args, "paths", []) or []),
        all_paths=bool(getattr(args, "all_paths", False)),
        force=bool(getattr(args, "force", False)),
    )
    print(output)
    return exit_code


def _handle_version_undo_run(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    exit_code, output = run_version_undo_run(
        config, args.run_id, force=bool(getattr(args, "force", False))
    )
    print(output)
    return exit_code


def _proposal_provider_from_args(args: argparse.Namespace):
    proposal_file = getattr(args, "proposal_file", None)
    if not proposal_file:
        return None
    return JsonFileProposalProvider(Path(proposal_file).expanduser().resolve())


def _proposal_provider_from_config(config: AgentConfig):
    return provider_from_config(config)


def _handle_memory_placeholder(args: argparse.Namespace, config: AgentConfig) -> int:
    _print_config_diagnostics(config)
    print(
        f"vault-agent memory {args.memory_command} is planned but not implemented yet. "
        "No files were changed."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    try:
        config = load_config(args)
        if _should_version_command(args, config):
            return execute_versioned(
                config,
                task_name=_task_name(args),
                command_args=["vault-agent", *(argv or [])],
                mass_edit=bool(getattr(args, "mass_edit", False)),
                expected_changed_files=_expected_changed_files(args, config),
                expected_deletions=_expected_deletions(args, config),
                operation=lambda: handler(args, config),
            )
        return handler(args, config)
    except Exception as exc:
        if (
            exc.__class__.__module__.endswith("versioning")
            or isinstance(exc, (MassEditBlocked, ValueError))
        ):
            print(f"vault-agent {getattr(args, 'command', '')} failed\nError: {exc}")
            return 1
        raise


def _task_name(args: argparse.Namespace) -> str:
    command = getattr(args, "command", "")
    if command == "version":
        return f"version-{getattr(args, 'version_command', '')}"
    return command


def _should_version_command(args: argparse.Namespace, config: AgentConfig) -> bool:
    if config.dry_run:
        return False
    command = getattr(args, "command", None)
    if command in {
        "status",
        "suggest-layout",
        "apply-layout",
        "organization-readiness",
        "action-plan",
        "obsidian-check",
        "submit-artifact",
        "export-schema-defaults",
        "import-schema-defaults",
        "version",
        "memory",
    }:
        return False
    if command == "norms-lock":
        return bool(getattr(args, "write", False))
    if command == "review-proposals":
        return bool(
            getattr(args, "apply_approved", False)
            or getattr(args, "agent_review", False)
            or getattr(args, "approve_safe", False)
        )
    if command == "hermes-run":
        return False
    return command in MAIN_COMMANDS


def _expected_changed_files(args: argparse.Namespace, config: AgentConfig) -> int | None:
    command = getattr(args, "command", "")
    if command in {"process-inbox", "process-vault", "organize-vault-pass"}:
        return getattr(args, "max_notes", None) or config.max_notes
    if command == "autonomous-run":
        max_notes = getattr(args, "max_notes", None) or config.max_notes
        return max_notes + int(getattr(args, "max_proposal_operations", 10)) + 10
    if command == "schema-conversation":
        return 5
    if command == "import-schema-defaults":
        return 1
    if command == "propose-cleanup-queue":
        return 1 if (getattr(args, "max_items", 25) or 0) else 0
    if command == "review-proposals" and getattr(args, "apply_approved", False):
        proposal_dir = getattr(args, "proposal_dir", None)
        directory = (
            Path(proposal_dir).expanduser()
            if proposal_dir
            else config.vault_root / config.paths.review_dir / "proposals"
        )
        if not directory.is_absolute():
            directory = config.vault_root / directory
        return sum(
            len(item.data.get("operations", []))
            for item in load_proposals(directory)
            if item.status == "approved" and not item.errors
        )
    if command == "reconcile":
        return len(build_reconcile_plan(config))
    return None


def _expected_deletions(args: argparse.Namespace, config: AgentConfig) -> int | None:
    return None
