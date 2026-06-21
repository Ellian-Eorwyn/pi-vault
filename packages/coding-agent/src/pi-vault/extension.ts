import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";
import { parse } from "yaml";
import { defineTool, type ExtensionAPI } from "../core/extensions/types.ts";
import { submitArtifactTool } from "./artifact-tool.ts";
import { loadPiForgeIntegration, PiForgeMcpClient } from "./mcp-client.ts";
import { runVaultAgent } from "./vault-process.ts";

interface BootstrapConfig {
	version: 1;
	systemDir: string;
	inboxDir: string;
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
	return { version: 1, systemDir: record.system_dir, inboxDir: record.inbox_dir };
}

function readContextFile(path: string, limit = 8_000): string | undefined {
	if (!existsSync(path)) return undefined;
	const content = readFileSync(path, "utf8").trim();
	if (!content) return undefined;
	return content.length > limit ? `${content.slice(0, limit)}\n[truncated]` : content;
}

export function loadVaultContext(vaultRoot: string): string | undefined {
	const bootstrap = readBootstrap(vaultRoot);
	if (!bootstrap) return undefined;
	const agentDir = join(vaultRoot, bootstrap.systemDir, "0.01 agent");
	const sections: Array<[string, string]> = [];
	for (const [label, path] of [
		["Purpose", join(agentDir, "vault-purpose.md")],
		["Conventions", join(agentDir, "vault-conventions.md")],
		["Agent handoff", join(agentDir, "AGENT_HANDOFF.md")],
		["Vault map", join(agentDir, "retrieval", "01 vault-map.md")],
		["Summary brief", join(agentDir, "retrieval", "04 summary-brief.md")],
	] as const) {
		const content = readContextFile(path);
		if (content) sections.push([label, content]);
	}
	const header = [
		"## pi-vault context",
		`Vault root: ${vaultRoot}`,
		`System folder: ${bootstrap.systemDir}`,
		`Inbox folder: ${bootstrap.inboxDir}`,
		"Use vault tools and pending proposals for mutations. Do not bypass proposal review for organization changes.",
	].join("\n");
	return [header, ...sections.map(([label, content]) => `### ${label}\n\n${content}`)].join("\n\n");
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
		if (event.reason !== "startup" || !ctx.hasUI) return;
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot || readBootstrap(vaultRoot)) return;
		const initialize = await ctx.ui.confirm("Initialize pi-vault", `Use ${vaultRoot} as the vault root?`);
		if (!initialize) return;
		const systemDir = (await ctx.ui.input("System folder", "00 System"))?.trim() || "00 System";
		const inboxDir = (await ctx.ui.input("Inbox folder", "01 Inbox"))?.trim() || "01 Inbox";
		const result = await runVaultAgent(
			["--vault-root", vaultRoot, "init", "--system-dir", systemDir, "--inbox-dir", inboxDir],
			vaultRoot,
		);
		const scanResult =
			result.exitCode === 0 ? await runVaultAgent(["--vault-root", vaultRoot, "scan"], vaultRoot) : undefined;
		const successful = result.exitCode === 0 && scanResult?.exitCode === 0;
		ctx.ui.notify(
			successful
				? "pi-vault initialized. Discuss and approve vault norms before broad organization."
				: scanResult?.stderr ||
						scanResult?.stdout ||
						result.stderr ||
						result.stdout ||
						"pi-vault initialization failed.",
			successful ? "info" : "error",
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
