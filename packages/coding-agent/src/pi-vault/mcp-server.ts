import { existsSync } from "node:fs";
import { join } from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { parseResult } from "./artifact-tool.ts";
import { requireDirectory } from "./mcp-client.ts";
import { runVaultAgent } from "./vault-process.ts";

export interface VaultMcpConfiguration {
	vaultRoot: string;
	readRoots: string[];
}

interface ArtifactArguments {
	sourcePath: string;
	suggestedName?: string;
	title?: string;
	sourceTaskId?: string;
	sourceOperation?: string;
}

export function validateVaultMcpConfiguration(configuration: VaultMcpConfiguration): VaultMcpConfiguration {
	const vaultRoot = requireDirectory(configuration.vaultRoot, "--vault-root");
	if (!existsSync(join(vaultRoot, ".pi-vault", "config.yaml"))) {
		throw new Error(`--vault-root is not an initialized pi-vault: ${vaultRoot}`);
	}
	const readRoots = configuration.readRoots.map((root) => requireDirectory(root, "--read-root"));
	if (readRoots.length === 0) throw new Error("at least one --read-root is required");
	return { vaultRoot, readRoots };
}

export function createVaultMcpServer(input: VaultMcpConfiguration): Server {
	const configuration = validateVaultMcpConfiguration(input);
	const server = new Server({ name: "pi-vault", version: "1.0.0" }, { capabilities: { tools: {} } });
	server.setRequestHandler(ListToolsRequestSchema, async () => ({
		tools: [
			{
				name: "vault_status",
				description: "Read machine status for the configured initialized pi-vault.",
				inputSchema: { type: "object", properties: {}, additionalProperties: false },
				annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
			},
			{
				name: "vault_submit_artifact",
				description: "Create a validated pending proposal for a Markdown or text artifact.",
				inputSchema: {
					type: "object",
					properties: {
						sourcePath: { type: "string" },
						suggestedName: { type: "string" },
						title: { type: "string" },
						sourceTaskId: { type: "string" },
						sourceOperation: { type: "string" },
					},
					required: ["sourcePath"],
					additionalProperties: false,
				},
				annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
			},
		],
	}));
	server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
		if (request.params.name === "vault_status") {
			const result = await runVaultAgent(
				["--vault-root", configuration.vaultRoot, "status", "--json"],
				configuration.vaultRoot,
				extra.signal,
			);
			const structuredContent = parseResult(result.stdout, result.stderr);
			return {
				content: [{ type: "text", text: JSON.stringify(structuredContent) }],
				structuredContent,
				isError: result.exitCode !== 0,
			};
		}
		if (request.params.name !== "vault_submit_artifact") {
			return {
				content: [{ type: "text", text: `unknown tool: ${request.params.name}` }],
				isError: true,
			};
		}
		const args = requireArtifactArguments(request.params.arguments);
		const command = ["--vault-root", configuration.vaultRoot, "submit-artifact", "--source-path", args.sourcePath];
		for (const root of configuration.readRoots) command.push("--read-root", root);
		if (args.suggestedName) command.push("--suggested-name", args.suggestedName);
		if (args.title) command.push("--title", args.title);
		if (args.sourceTaskId) command.push("--source-task-id", args.sourceTaskId);
		if (args.sourceOperation) command.push("--source-operation", args.sourceOperation);
		command.push("--json");
		const result = await runVaultAgent(command, configuration.vaultRoot, extra.signal);
		const structuredContent = parseResult(result.stdout, result.stderr);
		return {
			content: [{ type: "text", text: JSON.stringify(structuredContent) }],
			structuredContent,
			isError: result.exitCode !== 0,
		};
	});
	return server;
}

function requireArtifactArguments(value: unknown): ArtifactArguments {
	if (typeof value !== "object" || value === null) throw new Error("tool arguments must be an object");
	const record = value as Record<string, unknown>;
	if (typeof record.sourcePath !== "string") throw new Error("sourcePath is required");
	for (const key of ["suggestedName", "title", "sourceTaskId", "sourceOperation"] as const) {
		if (record[key] !== undefined && typeof record[key] !== "string") throw new Error(`${key} must be a string`);
	}
	return {
		sourcePath: record.sourcePath,
		suggestedName: record.suggestedName as string | undefined,
		title: record.title as string | undefined,
		sourceTaskId: record.sourceTaskId as string | undefined,
		sourceOperation: record.sourceOperation as string | undefined,
	};
}
