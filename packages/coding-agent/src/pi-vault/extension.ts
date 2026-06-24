import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";
import { parse } from "yaml";
import { defineTool, type ExtensionAPI } from "../core/extensions/types.ts";
import { submitArtifactTool } from "./artifact-tool.ts";
import { loadPiForgeIntegration, PiForgeMcpClient } from "./mcp-client.ts";
import { runVaultAgent } from "./vault-process.ts";

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
		["Canonical schema", "0.01 agent/schema.json", join(agentDir, "schema.json")],
		["Vault schema", "0.02 templates/0.020 vault schema.md", join(templateDir, "0.020 vault schema.md")],
		["Property values", "0.02 templates/0.021 property values.md", join(templateDir, "0.021 property values.md")],
		["Folder norms", "0.02 templates/0.022 folder norms.md", join(templateDir, "0.022 folder norms.md")],
		["Topic hubs", "0.02 templates/0.023 topic hubs.md", join(templateDir, "0.023 topic hubs.md")],
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
		"If schema_state is provisional, treat defaults only as recommendations. If locked, follow the schema exactly. If drifted, do not perform broad processing until the drift is reviewed.",
		"Do not process inbox files, apply proposals, write a lock, or otherwise mutate the vault unless the user explicitly approves the work.",
		"",
		status,
	].join("\n");
}

const statusTool = defineTool({
	name: "vault_status",
	label: "Vault Status",
	description: "Read machine-readable pi-vault status for the current Obsidian vault.",
	parameters: Type.Object({}),
	async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot || !readBootstrap(vaultRoot)) {
			return {
				content: [{ type: "text", text: "This directory is not an initialized pi-vault. Run onboarding first." }],
				details: { exitCode: 1 },
				isError: true,
			};
		}
		const result = await runVaultAgent(["--vault-root", vaultRoot, "status", "--json"], vaultRoot, signal);
		return {
			content: [{ type: "text", text: result.stdout || result.stderr }],
			details: { exitCode: result.exitCode },
			isError: result.exitCode !== 0,
		};
	},
});

const manageTool = defineTool({
	name: "vault_manage",
	label: "Manage Vault",
	description:
		"Run a validated pi-vault workflow. Use dry-run and review before mutations; apply-approved only after explicit user approval.",
	parameters: Type.Object({
		action: Type.Union([
			Type.Literal("scan"),
			Type.Literal("readiness"),
			Type.Literal("maintain"),
			Type.Literal("review"),
			Type.Literal("apply-approved"),
			Type.Literal("obsidian-check"),
			Type.Literal("rebuild-retrieval"),
			Type.Literal("write-norms-lock"),
			Type.Literal("undo"),
		]),
		maxNotes: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
		useLlm: Type.Optional(Type.Boolean()),
		applySafe: Type.Optional(Type.Boolean()),
		dryRun: Type.Optional(Type.Boolean()),
		runId: Type.Optional(Type.String()),
	}),
	async execute(_toolCallId, params, signal, _onUpdate, ctx) {
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot || !readBootstrap(vaultRoot)) {
			return {
				content: [{ type: "text", text: "This directory is not an initialized pi-vault. Run onboarding first." }],
				details: { exitCode: 1, action: params.action },
				isError: true,
			};
		}
		const args = ["--vault-root", vaultRoot];
		switch (params.action) {
			case "scan":
				args.push("scan");
				break;
			case "readiness":
				args.push("organization-readiness", "--json");
				break;
			case "maintain":
				args.push("autonomous-run", "--create-lock");
				if (params.applySafe) args.push("--apply-safe");
				if (params.useLlm) args.push("--use-llm");
				if (params.maxNotes) args.push("--max-notes", String(params.maxNotes));
				if (params.dryRun !== false) args.push("--dry-run");
				break;
			case "review":
				args.push("review-proposals", "--dry-run");
				break;
			case "apply-approved":
				args.push("review-proposals", "--apply-approved");
				break;
			case "obsidian-check":
				args.push("obsidian-check", "--json");
				break;
			case "rebuild-retrieval":
				args.push("rebuild-retrieval");
				break;
			case "write-norms-lock":
				args.push("norms-lock", "--write");
				break;
			case "undo":
				if (!params.runId) {
					return {
						content: [{ type: "text", text: "runId is required for undo." }],
						details: { exitCode: 1, action: params.action },
						isError: true,
					};
				}
				args.push("version", "undo-run", params.runId);
				break;
		}
		const result = await runVaultAgent(args, vaultRoot, signal);
		return {
			content: [{ type: "text", text: result.stdout || result.stderr }],
			details: { exitCode: result.exitCode, action: params.action },
			isError: result.exitCode !== 0,
		};
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
	pi.registerTool(manageTool);
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
					ctx.ui.notify(suggestResult.stderr || suggestResult.stdout || "pi-vault suggest-layout failed.", "error");
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
