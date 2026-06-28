import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";
import { parse } from "yaml";
import { defineTool, type ExtensionAPI } from "../core/extensions/types.ts";
import { submitArtifactTool } from "./artifact-tool.ts";
import { loadPiForgeIntegration, PiForgeMcpClient } from "./mcp-client.ts";
import { runVaultAgent, runVaultTool, type VaultToolResult } from "./vault-process.ts";

export interface BootstrapConfig {
	version: 1;
	systemDir: string;
	inboxDir: string;
	dashboardsDir?: string;
	contentDirs?: Record<string, string>;
}

const extensionDirectory = dirname(fileURLToPath(import.meta.url));
const skillsDirectory = join(extensionDirectory, "skills");

export function findVaultRoot(cwd: string): string | undefined {
	let current = resolve(cwd);
	while (true) {
		if (existsSync(join(current, ".obsidian")) || existsSync(join(current, ".pi-vault", "config.yaml"))) {
			return current;
		}
		const parent = dirname(current);
		if (parent === current) return undefined;
		current = parent;
	}
}

export function readBootstrap(vaultRoot: string): BootstrapConfig | undefined {
	const path = join(vaultRoot, ".pi-vault", "config.yaml");
	if (!existsSync(path)) return undefined;
	const value: unknown = parse(readFileSync(path, "utf8"));
	if (typeof value !== "object" || value === null) return undefined;
	const record = value as Record<string, unknown>;
	if (record.version !== 1 || typeof record.system_dir !== "string" || typeof record.inbox_dir !== "string") {
		return undefined;
	}
	const dashboardsDir = typeof record.dashboards_dir === "string" ? record.dashboards_dir : undefined;
	const contentDirs = record.content_dirs;
	if (
		contentDirs !== undefined &&
		(typeof contentDirs !== "object" || contentDirs === null || Array.isArray(contentDirs))
	) {
		return undefined;
	}
	const contentValues = contentDirs === undefined ? [] : Object.values(contentDirs as Record<string, unknown>);
	if (contentValues.some((value) => typeof value !== "string")) return undefined;
	for (const folder of [
		record.system_dir,
		record.inbox_dir,
		...(dashboardsDir ? [dashboardsDir] : []),
		...contentValues,
	]) {
		if (typeof folder !== "string") return undefined;
		const normalized = folder.replaceAll("\\", "/");
		const parts = normalized.split("/");
		if (
			isAbsolute(folder) ||
			/^[A-Za-z]:\//.test(normalized) ||
			parts.some((part) => !part || part === "." || part === "..") ||
			[".git", ".obsidian", ".pi-vault"].includes(parts[0])
		) {
			return undefined;
		}
	}
	return {
		version: 1,
		systemDir: record.system_dir,
		inboxDir: record.inbox_dir,
		...(dashboardsDir ? { dashboardsDir } : {}),
		...(contentDirs ? { contentDirs: contentDirs as Record<string, string> } : {}),
	};
}

function readContextFile(path: string, limit = 20_000): string | undefined {
	if (!existsSync(path)) return undefined;
	const content = readFileSync(path, "utf8").trim();
	if (!content) return undefined;
	return content.length > limit ? `${content.slice(0, limit)}\n[truncated]` : content;
}

export function loadVaultContext(vaultRoot: string): string | undefined {
	const bootstrap = readBootstrap(vaultRoot);
	if (!bootstrap) return undefined;
	const agentDir = join(vaultRoot, bootstrap.systemDir, "0.01 agent");
	const templateDir = join(vaultRoot, bootstrap.systemDir, "0.02 templates");
	const sections: Array<[string, string]> = [];
	for (const [label, relativePath, path] of [
		["Agent configuration", "0.01 agent/config.yaml", join(agentDir, "config.yaml")],
		["Purpose", "0.01 agent/vault-purpose.md", join(agentDir, "vault-purpose.md")],
		["Conventions", "0.01 agent/vault-conventions.md", join(agentDir, "vault-conventions.md")],
		["Agent handoff", "0.01 agent/AGENT_HANDOFF.md", join(agentDir, "AGENT_HANDOFF.md")],
		["Agent contract", "0.01 agent/AGENT_CONTRACT.md", join(agentDir, "AGENT_CONTRACT.md")],
		["Norms lock", "0.01 agent/norms-lock.json", join(agentDir, "norms-lock.json")],
		// The canonical, user-editable schema note (top of the system folder) plus the
		// compact structured schema.json are the single source of categories +
		// definitions. The generated `0.020/0.021/0.023` template docs are projections of
		// the same data and are intentionally NOT injected here (token efficiency).
		["Schema (editable canonical note)", "0.00 Vault Schema.md", join(vaultRoot, bootstrap.systemDir, "0.00 Vault Schema.md")],
		["Canonical schema", "0.01 agent/schema.json", join(agentDir, "schema.json")],
		["Folder norms", "0.02 templates/0.022 folder norms.md", join(templateDir, "0.022 folder norms.md")],
		[
			"Retrieval instructions",
			"0.01 agent/retrieval/00 retrieval-readme.md",
			join(agentDir, "retrieval", "00 retrieval-readme.md"),
		],
		["Vault map", "0.01 agent/retrieval/01 vault-map.md", join(agentDir, "retrieval", "01 vault-map.md")],
		["Summary brief", "0.01 agent/retrieval/04 summary-brief.md", join(agentDir, "retrieval", "04 summary-brief.md")],
	] as const) {
		const content = readContextFile(path);
		if (content) sections.push([`${label} (${bootstrap.systemDir}/${relativePath})`, content]);
	}
	const header = [
		"## pi-vault context",
		`Vault root: ${vaultRoot}`,
		`System folder: ${bootstrap.systemDir}`,
		`Inbox folder: ${bootstrap.inboxDir}`,
		"All vault-specific policy, state, sessions, and generated context belong under the configured system folder.",
		"Use vault tools and pending proposals for mutations. Do not bypass proposal review for organization changes.",
		`Schema source of truth: the user edits "${bootstrap.systemDir}/0.00 Vault Schema.md" (categories + definitions). If vault_status reports schema_note.changed, run vault_schema_sync FIRST to ingest the user's edits before any other work, then use the refreshed schema.`,
		existsSync(join(agentDir, "norms-lock.json"))
			? "Schema policy: the norms-lock snapshot is authoritative. Follow a current lock exactly; if vault_status reports drifted, block broad processing until the drift is reviewed and re-locked. Recommendations must remain proposal-first and preserve the approved intent."
			: "Schema policy: no norms lock exists, so the bundled schema and templates are provisional defaults for discussion only. Do not enforce them on existing notes. Use vault evidence to help the user decide, then apply approved proposals and write the lock.",
	].join("\n");
	return [header, ...sections.map(([label, content]) => `### ${label}\n\n${content}`)].join("\n\n");
}

export function startupAssessmentPrompt(status: string, newlyInitialized: boolean): string {
	const instructions = newlyInitialized
		? "This vault was just initialized and scanned. Begin onboarding now: summarize what was observed, explain that the default schema is provisional until the norms lock is written, and ask the user for the first durable decision about vault purpose and retrieval priorities."
		: "This is a returning vault. Use the resumed conversation to identify the last unfinished work, summarize current health and inbox changes, and offer specific next actions that pick up where the user left off.";
	return [
		"pi-vault generated this read-only startup assessment. It is context, not user authorization to modify files.",
		instructions,
		"First, if schema_note.changed is true in the status below, run vault_schema_sync to ingest the user's edits to the canonical schema note before anything else, so you work against current categories and definitions.",
		"If schema_state is provisional, treat defaults only as recommendations. If locked, follow the schema exactly. If drifted, do not perform broad processing until the drift is reviewed.",
		"Do not process inbox files, apply proposals, write a lock, or otherwise mutate the vault unless the user explicitly approves the work.",
		"",
		status,
	].join("\n");
}

type ArgsResult = string[] | { error: string };

export interface VaultSearchParams {
	query: string;
	topK?: number;
}

export interface VaultReadinessParams {
	report: "readiness" | "obsidian";
}

export interface VaultRetrievalParams {
	operation: "embed-index" | "rebuild-retrieval" | "related-links";
	maxNotes?: number;
	topK?: number;
	minSimilarity?: number;
	dryRun?: boolean;
}

export interface VaultSchemaProposeParams {
	operation:
		| "property"
		| "note-type"
		| "template"
		| "topic-hubs"
		| "schema-conversation"
		| "export-defaults"
		| "import-defaults";
	property?: string;
	value?: string;
	description?: string;
	name?: string;
	folder?: string;
	title?: string;
	noteType?: string;
	domain?: string;
	minCluster?: number;
	conversationFile?: string;
	includeCurrentSchemaSummary?: boolean;
	output?: string;
	schemaFile?: string;
}

export interface VaultOrganizeProposeParams {
	operation:
		| "vault-layout"
		| "base-hierarchy"
		| "folder-organization"
		| "cleanup-queue"
		| "inbox-sort"
		| "index"
		| "action-queue";
	folder?: string;
	project?: string;
	domain?: string;
	dashboardTitle?: string;
	indexType?: "type" | "project" | "parent" | "domain";
	value?: string;
	title?: string;
	maxItems?: number;
	maxNotes?: number;
	minChildNotes?: number;
	llmLimit?: number;
	useLlm?: boolean;
	safeOnly?: boolean;
	removeLegacy?: boolean;
	checkpoint?: boolean;
	resume?: boolean;
	massEdit?: boolean;
	dryRun?: boolean;
}

export type VaultProcessStage =
	| "frontmatter-shape"
	| "classify-type"
	| "property-values"
	| "template-body"
	| "assign-hub"
	| "assign-folder"
	| "summary";

export interface VaultProcessNotesParams {
	scope: "inbox" | "vault" | "organize-pass" | "reconcile";
	stage?: VaultProcessStage;
	folder?: string;
	note?: string;
	maxNotes?: number;
	maxRuntimeMinutes?: number;
	useLlm?: boolean;
	createLock?: boolean;
	propertiesOnly?: boolean;
	massEdit?: boolean;
	dryRun?: boolean;
}

export interface VaultContentProposeParams {
	operation: "people" | "refine";
	folder?: string;
	note?: string;
	maxNotes?: number;
	maxPeople?: number;
	dryRun?: boolean;
}

export interface VaultMaintainParams {
	operation: "scan" | "maintain" | "write-norms-lock";
	applySafe?: boolean;
	useLlm?: boolean;
	maxNotes?: number;
	dryRun?: boolean;
}

export interface VaultReviewApplyParams {
	operation: "review" | "apply-approved" | "approve-safe" | "review-blocks" | "approve-blocks-safe";
	stage?: VaultProcessStage;
	note?: string;
}

export interface VaultRecoveryParams {
	runId: string;
}

// Read-only semantic search. Deliberately has no flag that can reach a write path so this
// tool can back a write-incapable memory-retrieval surface.
export function buildSearchArgs(vaultRoot: string, params: VaultSearchParams): ArgsResult {
	if (!params.query?.trim()) return { error: "query is required for search." };
	const args = ["--vault-root", vaultRoot, "vault-search", params.query, "--json"];
	if (params.topK) args.push("--top-k", String(params.topK));
	return args;
}

export function buildReadinessArgs(vaultRoot: string, params: VaultReadinessParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	if (params.report === "obsidian") args.push("obsidian-check", "--json");
	else args.push("organization-readiness", "--json");
	return args;
}

export function buildRetrievalArgs(vaultRoot: string, params: VaultRetrievalParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	if (params.operation === "embed-index") {
		args.push("embed-index");
	} else if (params.operation === "rebuild-retrieval") {
		args.push("rebuild-retrieval");
	} else {
		if (params.dryRun !== false) args.push("--dry-run");
		args.push("propose-related-links");
		if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
		if (params.topK) args.push("--top-k", String(params.topK));
		if (params.minSimilarity !== undefined) args.push("--min-similarity", String(params.minSimilarity));
	}
	return args;
}

export function buildSchemaProposeArgs(vaultRoot: string, params: VaultSchemaProposeParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	switch (params.operation) {
		case "property":
			if (!params.property || !params.value) {
				return { error: "property and value are required to propose a property." };
			}
			args.push("propose-property", "--property", params.property, "--value", params.value);
			if (params.description) args.push("--description", params.description);
			args.push("--json");
			break;
		case "note-type":
			if (!params.name || !params.description || !params.folder) {
				return { error: "name, description, and folder are required to propose a note type." };
			}
			args.push(
				"propose-note-type",
				"--name",
				params.name,
				"--description",
				params.description,
				"--folder",
				params.folder,
			);
			if (params.title) args.push("--title", params.title);
			args.push("--json");
			break;
		case "template":
			if (!params.noteType) return { error: "noteType is required to propose a template." };
			args.push("propose-template", "--note-type", params.noteType, "--json");
			break;
		case "topic-hubs":
			args.push("propose-topic-hubs");
			if (params.domain) args.push("--domain", params.domain);
			if (params.minCluster) args.push("--min-cluster", String(params.minCluster));
			args.push("--json");
			break;
		case "schema-conversation":
			if (!params.conversationFile) return { error: "conversationFile is required for schema-conversation." };
			args.push("schema-conversation", "--conversation-file", params.conversationFile);
			if (params.includeCurrentSchemaSummary) args.push("--include-current-schema-summary");
			break;
		case "export-defaults":
			args.push("export-schema-defaults");
			if (params.output) args.push("--output", params.output);
			break;
		case "import-defaults":
			args.push("import-schema-defaults");
			if (params.schemaFile) args.push("--schema-file", params.schemaFile);
			break;
	}
	return args;
}

export function buildOrganizeProposeArgs(vaultRoot: string, params: VaultOrganizeProposeParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	if (params.dryRun) args.push("--dry-run");
	switch (params.operation) {
		case "vault-layout":
			args.push("propose-vault-layout");
			break;
		case "base-hierarchy":
			args.push("propose-base-hierarchy");
			if (params.useLlm) args.push("--use-llm");
			if (params.llmLimit) args.push("--llm-limit", String(params.llmLimit));
			if (params.minChildNotes) args.push("--min-child-notes", String(params.minChildNotes));
			break;
		case "folder-organization":
			if (!params.folder) return { error: "folder is required for folder-organization." };
			args.push("propose-folder-organization", "--folder", params.folder);
			if (params.project) args.push("--project", params.project);
			if (params.domain) args.push("--domain", params.domain);
			if (params.dashboardTitle) args.push("--dashboard-title", params.dashboardTitle);
			if (params.useLlm) args.push("--use-llm");
			if (params.llmLimit) args.push("--llm-limit", String(params.llmLimit));
			if (params.removeLegacy) args.push("--remove-legacy");
			if (params.checkpoint) args.push("--checkpoint");
			if (params.resume) args.push("--resume");
			if (params.massEdit) args.push("--mass-edit");
			break;
		case "cleanup-queue":
			args.push("propose-cleanup-queue");
			if (params.folder) args.push("--folder", params.folder);
			if (params.maxItems) args.push("--max-items", String(params.maxItems));
			if (params.massEdit) args.push("--mass-edit");
			break;
		case "inbox-sort":
			args.push("propose-inbox-sort");
			if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
			if (params.safeOnly) args.push("--safe-only");
			break;
		case "index":
			if (!params.indexType || !params.value) return { error: "indexType and value are required for index." };
			args.push("propose-index", "--index-type", params.indexType, "--value", params.value);
			if (params.title) args.push("--title", params.title);
			break;
		case "action-queue":
			args.push("propose-action-queue");
			if (params.folder) args.push("--folder", params.folder);
			if (params.maxItems) args.push("--max-items", String(params.maxItems));
			if (params.useLlm) args.push("--use-llm");
			if (params.llmLimit) args.push("--llm-limit", String(params.llmLimit));
			if (params.checkpoint) args.push("--checkpoint");
			if (params.resume) args.push("--resume");
			if (params.massEdit) args.push("--mass-edit");
			break;
	}
	args.push("--json");
	return args;
}

export function buildProcessNotesArgs(vaultRoot: string, params: VaultProcessNotesParams): ArgsResult {
	// `--folder` only scopes organize-pass; process-inbox/process-vault accept only --note.
	const scoped = Boolean(params.note) || (params.scope === "organize-pass" && Boolean(params.folder));
	if (params.scope !== "reconcile" && !scoped && !params.maxNotes) {
		return { error: `maxNotes is required for a broad ${params.scope} run (no folder or note scope).` };
	}
	const args = ["--vault-root", vaultRoot];
	if (params.dryRun) args.push("--dry-run");
	if (params.scope === "reconcile") {
		args.push("reconcile");
		if (params.propertiesOnly) args.push("--properties-only");
		if (params.massEdit) args.push("--mass-edit");
		args.push("--json");
		return args;
	}
	if (params.scope === "inbox") args.push("process-inbox");
	else if (params.scope === "vault") args.push("process-vault");
	else args.push("organize-vault-pass");
	if (params.stage) args.push("--stage", params.stage);
	if (params.folder && params.scope === "organize-pass") args.push("--folder", params.folder);
	if (params.note) args.push("--note", params.note);
	if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
	if (params.maxRuntimeMinutes) args.push("--max-runtime-minutes", String(params.maxRuntimeMinutes));
	if (params.useLlm && params.scope === "organize-pass") args.push("--use-llm");
	if (params.createLock && params.scope === "organize-pass") args.push("--create-lock");
	if (params.massEdit) args.push("--mass-edit");
	args.push("--json");
	return args;
}

export function buildContentProposeArgs(vaultRoot: string, params: VaultContentProposeParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	if (params.operation === "people") {
		args.push("propose-people");
		if (params.folder) args.push("--folder", params.folder);
		if (params.maxPeople) args.push("--max-people", String(params.maxPeople));
	} else {
		if (!params.folder && !params.note) return { error: "folder or note is required to refine." };
		args.push("propose-folder-refinement");
		if (params.folder) args.push("--folder", params.folder);
		if (params.note) args.push("--note", params.note);
		if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
		if (params.dryRun !== false) args.push("--dry-run");
	}
	return args;
}

export function buildMaintainArgs(vaultRoot: string, params: VaultMaintainParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	if (params.operation === "scan") {
		args.push("scan");
	} else if (params.operation === "write-norms-lock") {
		args.push("norms-lock", "--write");
	} else {
		args.push("autonomous-run", "--create-lock");
		if (params.applySafe) args.push("--apply-safe");
		if (params.useLlm) args.push("--use-llm");
		if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
		if (params.dryRun !== false) args.push("--dry-run");
	}
	return args;
}

export function buildReviewApplyArgs(vaultRoot: string, params: VaultReviewApplyParams): ArgsResult {
	const args = ["--vault-root", vaultRoot];
	switch (params.operation) {
		case "apply-approved":
			args.push("review-proposals", "--apply-approved");
			break;
		case "approve-safe":
			args.push("review-proposals", "--agent-review", "--approve-safe");
			break;
		case "review-blocks":
			args.push("review-model-blocks", "--dry-run");
			if (params.stage) args.push("--stage", params.stage);
			if (params.note) args.push("--note", params.note);
			break;
		case "approve-blocks-safe":
			args.push("review-model-blocks", "--approve-safe");
			if (params.stage) args.push("--stage", params.stage);
			if (params.note) args.push("--note", params.note);
			break;
		default:
			args.push("review-proposals", "--dry-run");
			break;
	}
	return args;
}

export function buildRecoveryArgs(vaultRoot: string, params: VaultRecoveryParams): ArgsResult {
	if (!params.runId) return { error: "runId is required to undo a run." };
	return ["--vault-root", vaultRoot, "version", "undo-run", params.runId];
}

const NOT_INITIALIZED: VaultToolResult = {
	content: [{ type: "text", text: "This directory is not an initialized pi-vault. Run onboarding first." }],
	details: { exitCode: 1 },
	isError: true,
};

/** Resolve the vault root and confirm it is bootstrapped, or return a standard error result. */
export function resolveInitializedVault(cwd: string): { vaultRoot: string } | { error: VaultToolResult } {
	const vaultRoot = findVaultRoot(cwd);
	if (!vaultRoot || !readBootstrap(vaultRoot)) return { error: NOT_INITIALIZED };
	return { vaultRoot };
}

/** Resolve the vault, build argv, and run it — the shared body of every first-class vault tool. */
async function runVaultBuilder(
	cwd: string,
	signal: AbortSignal | undefined,
	build: (vaultRoot: string) => string[] | { error: string },
): Promise<VaultToolResult> {
	const resolved = resolveInitializedVault(cwd);
	if ("error" in resolved) return resolved.error;
	const args = build(resolved.vaultRoot);
	if (!Array.isArray(args)) {
		return { content: [{ type: "text", text: args.error }], details: { exitCode: 1 }, isError: true };
	}
	return runVaultTool(args, resolved.vaultRoot, signal);
}

const statusTool = defineTool({
	name: "vault_status",
	label: "Vault Status",
	description: "Read machine-readable pi-vault status for the current Obsidian vault.",
	parameters: Type.Object({}),
	execute(_toolCallId, _params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => ["--vault-root", vaultRoot, "status", "--json"]);
	},
});

const schemaSyncTool = defineTool({
	name: "vault_schema_sync",
	label: "Sync Schema Note",
	description:
		"Ingest the user-editable canonical schema note (top of the system folder) into the structured schema, applying only what changed. Run this first when vault_status reports the schema note changed. Applies additions and definition edits directly (the user authored them); refuses to remove a value still used by notes.",
	parameters: Type.Object({}),
	execute(_toolCallId, _params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => ["--vault-root", vaultRoot, "schema-sync", "--json"]);
	},
});

const readinessTool = defineTool({
	name: "vault_readiness",
	label: "Vault Readiness",
	description:
		"Read-only pre-flight checks before broad work: organization readiness or static Obsidian compatibility. Never mutates the vault.",
	parameters: Type.Object({
		report: Type.Union([Type.Literal("readiness"), Type.Literal("obsidian")]),
	}),
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildReadinessArgs(vaultRoot, params));
	},
});

const searchTool = defineTool({
	name: "vault_search",
	label: "Search Vault",
	description:
		"Read-only semantic search over the embedding index. Returns ranked notes by meaning and never writes, rebuilds, or proposes anything.",
	parameters: Type.Object({
		query: Type.String({ minLength: 1 }),
		topK: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
	}),
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildSearchArgs(vaultRoot, params));
	},
});

const retrievalTool = defineTool({
	name: "vault_retrieval",
	label: "Vault Retrieval Index",
	description:
		"Build or refresh retrieval state and propose related links. `embed-index` and `rebuild-retrieval` regenerate indices; `related-links` writes an append-only pending proposal (dry-run by default) — never applies.",
	parameters: Type.Object({
		operation: Type.Union([
			Type.Literal("embed-index"),
			Type.Literal("rebuild-retrieval"),
			Type.Literal("related-links"),
		]),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		topK: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		minSimilarity: Type.Optional(Type.Number({ minimum: -1, maximum: 1 })),
		dryRun: Type.Optional(Type.Boolean()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildRetrievalArgs(vaultRoot, params));
	},
});

const schemaProposeTool = defineTool({
	name: "vault_schema_propose",
	label: "Propose Schema Change",
	description:
		"Author the schema/norms through pending proposals: a canonical property value (`property`), a new note type (`note-type`), a note-type template refresh (`template`), candidate topic hubs (`topic-hubs`), an onboarding/schema transcript (`schema-conversation`), or export/import of editable Markdown defaults. Writes pending proposals only — never approves or applies. Review and apply separately.",
	parameters: Type.Object({
		operation: Type.Union([
			Type.Literal("property"),
			Type.Literal("note-type"),
			Type.Literal("template"),
			Type.Literal("topic-hubs"),
			Type.Literal("schema-conversation"),
			Type.Literal("export-defaults"),
			Type.Literal("import-defaults"),
		]),
		property: Type.Optional(Type.String()),
		value: Type.Optional(Type.String()),
		description: Type.Optional(Type.String()),
		name: Type.Optional(Type.String()),
		folder: Type.Optional(Type.String()),
		title: Type.Optional(Type.String()),
		noteType: Type.Optional(Type.String()),
		domain: Type.Optional(Type.String()),
		minCluster: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		conversationFile: Type.Optional(Type.String()),
		includeCurrentSchemaSummary: Type.Optional(Type.Boolean()),
		output: Type.Optional(Type.String()),
		schemaFile: Type.Optional(Type.String()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildSchemaProposeArgs(vaultRoot, params));
	},
});

const contentProposeTool = defineTool({
	name: "vault_content_propose",
	label: "Propose Content Change",
	description:
		"Generate a pending content proposal: extract people into Contacts/Authors, or refine note bodies for structure (the word-preservation guard forbids changing wording or meaning). Writes a pending proposal only — never applies. Refine is dry-run by default.",
	parameters: Type.Object({
		operation: Type.Union([Type.Literal("people"), Type.Literal("refine")]),
		folder: Type.Optional(Type.String()),
		note: Type.Optional(Type.String()),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		maxPeople: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		dryRun: Type.Optional(Type.Boolean()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildContentProposeArgs(vaultRoot, params));
	},
});

const maintainTool = defineTool({
	name: "vault_maintain",
	label: "Maintain Vault",
	description:
		"Run bounded maintenance: `scan` updates the manifest, `maintain` runs a bounded autonomous pass (dry-run by default; pass dryRun:false and applySafe only after review), `write-norms-lock` snapshots the current norms. Use dry-run before broad changes.",
	parameters: Type.Object({
		operation: Type.Union([Type.Literal("scan"), Type.Literal("maintain"), Type.Literal("write-norms-lock")]),
		applySafe: Type.Optional(Type.Boolean()),
		useLlm: Type.Optional(Type.Boolean()),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
		dryRun: Type.Optional(Type.Boolean()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildMaintainArgs(vaultRoot, params));
	},
});

const reviewApplyTool = defineTool({
	name: "vault_review_apply",
	label: "Review and Apply Proposals",
	description:
		"Inspect or apply pending proposals. `review` is a read-only dry-run that validates the proposal queue; `apply-approved` applies only proposals already marked approved; `approve-safe` marks valid bounded non-schema proposals approved; `review-blocks` previews blocked model-stage proposals and `approve-blocks-safe` converts the safe ones. Dry-run and review before mutations; apply only after explicit approval.",
	parameters: Type.Object({
		operation: Type.Union([
			Type.Literal("review"),
			Type.Literal("apply-approved"),
			Type.Literal("approve-safe"),
			Type.Literal("review-blocks"),
			Type.Literal("approve-blocks-safe"),
		]),
		stage: Type.Optional(
			Type.Union([
				Type.Literal("frontmatter-shape"),
				Type.Literal("classify-type"),
				Type.Literal("property-values"),
				Type.Literal("template-body"),
				Type.Literal("assign-hub"),
				Type.Literal("assign-folder"),
				Type.Literal("summary"),
			]),
		),
		note: Type.Optional(Type.String()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildReviewApplyArgs(vaultRoot, params));
	},
});

const recoveryTool = defineTool({
	name: "vault_recovery",
	label: "Recover Vault Run",
	description: "Undo a previous versioned run, restoring only the files that run touched.",
	parameters: Type.Object({
		runId: Type.String({ minLength: 1 }),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildRecoveryArgs(vaultRoot, params));
	},
});

const processStageSchema = Type.Union([
	Type.Literal("frontmatter-shape"),
	Type.Literal("classify-type"),
	Type.Literal("property-values"),
	Type.Literal("template-body"),
	Type.Literal("assign-hub"),
	Type.Literal("assign-folder"),
	Type.Literal("summary"),
]);

const organizeProposeTool = defineTool({
	name: "vault_organize_propose",
	label: "Propose Organization",
	description:
		"Generate pending organization proposals: dashboard-first layout migration (`vault-layout`), a hierarchy of Bases dashboards (`base-hierarchy`), one folder's organization + dashboard (`folder-organization`), a bounded frontmatter cleanup queue (`cleanup-queue`), deterministic inbox move proposals (`inbox-sort`), an index note (`index`), or a queued-maintenance action plan (`action-queue`). Writes pending proposals only — never applies. Review and apply through vault_review_apply.",
	parameters: Type.Object({
		operation: Type.Union([
			Type.Literal("vault-layout"),
			Type.Literal("base-hierarchy"),
			Type.Literal("folder-organization"),
			Type.Literal("cleanup-queue"),
			Type.Literal("inbox-sort"),
			Type.Literal("index"),
			Type.Literal("action-queue"),
		]),
		folder: Type.Optional(Type.String()),
		project: Type.Optional(Type.String()),
		domain: Type.Optional(Type.String()),
		dashboardTitle: Type.Optional(Type.String()),
		indexType: Type.Optional(
			Type.Union([Type.Literal("type"), Type.Literal("project"), Type.Literal("parent"), Type.Literal("domain")]),
		),
		value: Type.Optional(Type.String()),
		title: Type.Optional(Type.String()),
		maxItems: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
		minChildNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		llmLimit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
		useLlm: Type.Optional(Type.Boolean()),
		safeOnly: Type.Optional(Type.Boolean()),
		removeLegacy: Type.Optional(Type.Boolean()),
		checkpoint: Type.Optional(Type.Boolean()),
		resume: Type.Optional(Type.Boolean()),
		massEdit: Type.Optional(Type.Boolean()),
		dryRun: Type.Optional(Type.Boolean()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildOrganizeProposeArgs(vaultRoot, params));
	},
});

const processNotesTool = defineTool({
	name: "vault_process_notes",
	label: "Process Notes",
	description:
		"Run a bounded, lock-aware processing pass over notes — `inbox`, `vault`, an `organize-pass` (folder/stage-scoped), or `reconcile` (apply approved defaults). One semantic `stage` per LLM run (frontmatter-shape, classify-type, property-values, template-body, assign-hub, assign-folder, summary). Emits review-gated stage proposals; never bypasses apply. A broad run (no folder/note) requires maxNotes; keep batches small until review queues are clean. `massEdit` is opt-in only.",
	parameters: Type.Object({
		scope: Type.Union([
			Type.Literal("inbox"),
			Type.Literal("vault"),
			Type.Literal("organize-pass"),
			Type.Literal("reconcile"),
		]),
		stage: Type.Optional(processStageSchema),
		folder: Type.Optional(Type.String()),
		note: Type.Optional(Type.String()),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
		maxRuntimeMinutes: Type.Optional(Type.Integer({ minimum: 1, maximum: 120 })),
		useLlm: Type.Optional(Type.Boolean()),
		createLock: Type.Optional(Type.Boolean()),
		propertiesOnly: Type.Optional(Type.Boolean()),
		massEdit: Type.Optional(Type.Boolean()),
		dryRun: Type.Optional(Type.Boolean()),
	}),
	executionMode: "sequential",
	execute(_toolCallId, params, signal, _onUpdate, ctx) {
		return runVaultBuilder(ctx.cwd, signal, (vaultRoot) => buildProcessNotesArgs(vaultRoot, params));
	},
});

export default function piVaultExtension(pi: ExtensionAPI) {
	let forgeClient: PiForgeMcpClient | undefined;
	const callForge = async (
		name: string,
		params: Record<string, unknown>,
		signal: AbortSignal | undefined,
		cwd: string,
	) => {
		const vaultRoot = findVaultRoot(cwd);
		if (!vaultRoot || !readBootstrap(vaultRoot)) throw new Error("This directory is not an initialized pi-vault.");
		forgeClient ??= new PiForgeMcpClient(loadPiForgeIntegration(vaultRoot));
		const result = await forgeClient.callTool(name, params, signal);
		const structured = result.structuredContent;
		const details =
			typeof structured === "object" && structured !== null ? (structured as Record<string, unknown>) : result;
		return {
			content: [{ type: "text" as const, text: JSON.stringify(details) }],
			details,
		};
	};
	pi.registerTool(
		defineTool({
			name: "forge_transcribe",
			label: "Transcribe with pi-forge",
			description: "Run deterministic local transcription through the configured pi-forge MCP server.",
			parameters: Type.Object({
				inputPath: Type.String(),
				outputRoot: Type.String(),
				recordingType: Type.Union([
					Type.Literal("lecture"),
					Type.Literal("interview"),
					Type.Literal("meeting"),
					Type.Literal("call"),
					Type.Literal("voice-note"),
					Type.Literal("other"),
				]),
				projectDictionaryPath: Type.Optional(Type.String()),
			}),
			executionMode: "sequential",
			execute(_toolCallId, params, signal, _onUpdate, ctx) {
				return callForge("forge_transcribe", params, signal, ctx.cwd);
			},
		}),
	);
	pi.registerTool(
		defineTool({
			name: "forge_convert_files",
			label: "Convert with pi-forge",
			description: "Run deterministic file conversion through the configured pi-forge MCP server.",
			parameters: Type.Object({
				inputPaths: Type.Array(Type.String(), { minItems: 1 }),
				target: Type.Union([
					Type.Literal("md"),
					Type.Literal("docx"),
					Type.Literal("html"),
					Type.Literal("txt"),
					Type.Literal("epub"),
					Type.Literal("csv"),
					Type.Literal("xlsx"),
				]),
				outputRoot: Type.String(),
				sourceFormat: Type.Optional(Type.String()),
				coverPath: Type.Optional(Type.String()),
				title: Type.Optional(Type.String()),
				author: Type.Optional(Type.String()),
				language: Type.Optional(Type.String()),
				date: Type.Optional(Type.String()),
			}),
			executionMode: "sequential",
			execute(_toolCallId, params, signal, _onUpdate, ctx) {
				return callForge("forge_convert_files", params, signal, ctx.cwd);
			},
		}),
	);
	pi.registerTool(statusTool);
	pi.registerTool(schemaSyncTool);
	pi.registerTool(readinessTool);
	pi.registerTool(searchTool);
	pi.registerTool(retrievalTool);
	pi.registerTool(schemaProposeTool);
	pi.registerTool(contentProposeTool);
	pi.registerTool(organizeProposeTool);
	pi.registerTool(processNotesTool);
	pi.registerTool(maintainTool);
	pi.registerTool(reviewApplyTool);
	pi.registerTool(recoveryTool);
	pi.registerTool(submitArtifactTool);
	pi.on("session_shutdown", async () => {
		const client = forgeClient;
		forgeClient = undefined;
		if (client) await client.close();
	});
	pi.on("resources_discover", () => ({ skillPaths: [skillsDirectory] }));
	pi.on("session_start", async (event, ctx) => {
		if (event.reason !== "startup" || ctx.mode !== "tui") return;
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot) return;
		let newlyInitialized = false;
		if (!readBootstrap(vaultRoot)) {
			const choice = await ctx.ui.select(`Initialize ${vaultRoot}`, [
				"Suggest a folder layout from my existing folders and notes (review before creating)",
				"Use dashboard-first defaults: 00 Inbox, 01 Dashboards, and 99 System",
				"Customize folders",
				"Cancel",
			]);
			if (!choice || choice === "Cancel") return;
			let layoutApplied = false;
			if (choice.startsWith("Suggest a folder layout")) {
				const suggestResult = await runVaultAgent(["--vault-root", vaultRoot, "suggest-layout"], vaultRoot);
				if (suggestResult.exitCode !== 0) {
					ctx.ui.notify(
						suggestResult.stderr || suggestResult.stdout || "pi-vault suggest-layout failed.",
						"error",
					);
					return;
				}
				const next = await ctx.ui.select(
					"A suggested layout was written to .pi-vault/layout-suggestion.yaml. Edit it to match the folders you want, then choose:",
					["Apply the layout and initialize", "Use dashboard-first defaults instead", "Cancel"],
				);
				if (!next || next === "Cancel") return;
				if (next.startsWith("Apply")) {
					const applyResult = await runVaultAgent(["--vault-root", vaultRoot, "apply-layout"], vaultRoot);
					if (applyResult.exitCode !== 0) {
						ctx.ui.notify(applyResult.stderr || applyResult.stdout || "pi-vault apply-layout failed.", "error");
						return;
					}
					layoutApplied = true;
				}
			}
			// When a layout is applied, init reads it from the bootstrap; otherwise pass the chosen folders.
			const initArgs = ["--vault-root", vaultRoot, "init"];
			if (!layoutApplied) {
				let systemDir = "99 System";
				let inboxDir = "00 Inbox";
				if (choice === "Customize folders") {
					const selectedSystemDir = await ctx.ui.input("System folder", systemDir);
					if (selectedSystemDir === undefined) return;
					const selectedInboxDir = await ctx.ui.input("Inbox folder", inboxDir);
					if (selectedInboxDir === undefined) return;
					systemDir = selectedSystemDir.trim() || systemDir;
					inboxDir = selectedInboxDir.trim() || inboxDir;
				}
				initArgs.push("--system-dir", systemDir, "--inbox-dir", inboxDir);
			}
			const result = await runVaultAgent(initArgs, vaultRoot);
			const scanResult =
				result.exitCode === 0 ? await runVaultAgent(["--vault-root", vaultRoot, "scan"], vaultRoot) : undefined;
			if (result.exitCode !== 0 || scanResult?.exitCode !== 0) {
				ctx.ui.notify(
					scanResult?.stderr ||
						scanResult?.stdout ||
						result.stderr ||
						result.stdout ||
						"pi-vault initialization failed.",
					"error",
				);
				return;
			}
			newlyInitialized = true;
			ctx.ui.notify(
				"pi-vault initialized. The default schema remains provisional until approved and locked.",
				"info",
			);
		}
		const status = await runVaultAgent(["--vault-root", vaultRoot, "status", "--json"], vaultRoot);
		if (status.exitCode !== 0) {
			ctx.ui.notify(status.stderr || status.stdout || "pi-vault startup assessment failed.", "error");
			return;
		}
		pi.sendMessage(
			{
				customType: "pi-vault-startup",
				content: startupAssessmentPrompt(status.stdout, newlyInitialized),
				display: false,
				details: { newlyInitialized },
			},
			{ triggerTurn: true },
		);
	});
	pi.on("before_agent_start", async (event, ctx) => {
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot) return;
		const context = loadVaultContext(vaultRoot);
		if (!context) {
			return {
				systemPrompt: `${event.systemPrompt}\n\n## pi-vault\nThis Obsidian vault is not initialized. Use the vault-onboarding skill before managing notes.`,
			};
		}
		return { systemPrompt: `${event.systemPrompt}\n\n${context}` };
	});
}
