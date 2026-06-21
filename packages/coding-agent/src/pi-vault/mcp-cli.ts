#!/usr/bin/env node
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createVaultMcpServer } from "./mcp-server.ts";

function parseArguments(args: string[]): { vaultRoot: string; readRoots: string[]; help: boolean } {
	let vaultRoot: string | undefined;
	const readRoots: string[] = [];
	for (let index = 0; index < args.length; index += 1) {
		const argument = args[index];
		if (argument === "--help" || argument === "-h") return { vaultRoot: "", readRoots, help: true };
		if (argument === "--vault-root" || argument === "--read-root") {
			const value = args[index + 1];
			if (!value) throw new Error(`${argument} requires a path`);
			if (argument === "--vault-root") {
				if (vaultRoot) throw new Error("--vault-root may be specified exactly once");
				vaultRoot = value;
			} else readRoots.push(value);
			index += 1;
			continue;
		}
		throw new Error(`unknown argument: ${argument}`);
	}
	if (!vaultRoot) throw new Error("exactly one --vault-root is required");
	if (readRoots.length === 0) throw new Error("at least one --read-root is required");
	return { vaultRoot, readRoots, help: false };
}

async function main(): Promise<void> {
	const configuration = parseArguments(process.argv.slice(2));
	if (configuration.help) {
		process.stdout.write(
			"Usage: pi-vault-mcp --vault-root <absolute-path> --read-root <absolute-path> [--read-root ...]\n",
		);
		return;
	}
	const server = createVaultMcpServer(configuration);
	await server.connect(new StdioServerTransport());
}

main().catch((error: unknown) => {
	process.stderr.write(`pi-vault-mcp: ${error instanceof Error ? error.message : String(error)}\n`);
	process.exitCode = 1;
});
