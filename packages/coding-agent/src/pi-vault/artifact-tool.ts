import { Type } from "typebox";
import { defineTool } from "../core/extensions/types.ts";
import { findVaultRoot, readBootstrap } from "./extension.ts";
import { loadPiForgeIntegration, type PiForgeIntegrationConfig } from "./mcp-client.ts";
import { runVaultAgent } from "./vault-process.ts";

export const submitArtifactParameters = Type.Object({
	sourcePath: Type.String(),
	suggestedName: Type.Optional(Type.String()),
	title: Type.Optional(Type.String()),
	sourceTaskId: Type.Optional(Type.String()),
	sourceOperation: Type.Optional(Type.String()),
});

export const submitArtifactTool = defineTool({
	name: "vault_submit_artifact",
	label: "Submit Artifact to Vault",
	description: "Create a validated pending pi-vault proposal for a completed Markdown or text artifact.",
	parameters: submitArtifactParameters,
	executionMode: "sequential",
	async execute(_toolCallId, params, signal, _onUpdate, ctx) {
		const vaultRoot = findVaultRoot(ctx.cwd);
		if (!vaultRoot || !readBootstrap(vaultRoot)) {
			return {
				content: [{ type: "text" as const, text: "This directory is not an initialized pi-vault." }],
				details: { status: "failed", error: { code: "vault_not_initialized" } },
			};
		}
		let integration: PiForgeIntegrationConfig;
		try {
			integration = loadPiForgeIntegration(vaultRoot);
		} catch (error: unknown) {
			const message = error instanceof Error ? error.message : String(error);
			return {
				content: [{ type: "text" as const, text: message }],
				details: { status: "failed", error: { code: "invalid_configuration", message } },
			};
		}
		const args = ["--vault-root", vaultRoot, "submit-artifact", "--source-path", params.sourcePath];
		for (const root of [integration.outputRoot]) args.push("--read-root", root);
		if (params.suggestedName) args.push("--suggested-name", params.suggestedName);
		if (params.title) args.push("--title", params.title);
		if (params.sourceTaskId) args.push("--source-task-id", params.sourceTaskId);
		if (params.sourceOperation) args.push("--source-operation", params.sourceOperation);
		args.push("--json");
		const result = await runVaultAgent(args, vaultRoot, signal);
		const details = parseResult(result.stdout, result.stderr);
		return {
			content: [{ type: "text" as const, text: JSON.stringify(details) }],
			details,
		};
	},
});

export function parseResult(stdout: string, stderr: string): Record<string, unknown> {
	try {
		const parsed: unknown = JSON.parse(stdout.trim());
		if (typeof parsed === "object" && parsed !== null) return parsed as Record<string, unknown>;
	} catch {}
	return {
		status: "failed",
		error: { code: "invalid_worker_response", message: stderr || stdout || "vault-agent returned no JSON" },
	};
}
