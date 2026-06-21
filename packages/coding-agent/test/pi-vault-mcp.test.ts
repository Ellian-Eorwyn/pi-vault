import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, describe, expect, it } from "vitest";
import { loadPiForgeIntegration, PiForgeMcpClient } from "../src/pi-vault/mcp-client.ts";
import { createVaultMcpServer } from "../src/pi-vault/mcp-server.ts";
import { runVaultAgent } from "../src/pi-vault/vault-process.ts";

const temporaryDirectories: string[] = [];

function temporaryDirectory(): string {
	const directory = mkdtempSync(join(tmpdir(), "pi-vault-mcp-"));
	temporaryDirectories.push(directory);
	return directory;
}

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("pi-vault MCP", () => {
	it("discovers only status and pending artifact submission tools", async () => {
		const root = temporaryDirectory();
		const vault = join(root, "vault");
		const artifacts = join(root, "artifacts");
		mkdirSync(vault);
		mkdirSync(artifacts);
		expect((await runVaultAgent(["--vault-root", vault, "init"], vault)).exitCode).toBe(0);
		const source = join(artifacts, "result.md");
		writeFileSync(source, "# Result\n");
		const server = createVaultMcpServer({ vaultRoot: vault, readRoots: [artifacts] });
		const client = new Client({ name: "test", version: "1.0.0" }, { capabilities: {} });
		const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
		await server.connect(serverTransport);
		await client.connect(clientTransport);
		try {
			const tools = await client.listTools();
			expect(tools.tools.map((tool) => tool.name).sort()).toEqual(["vault_status", "vault_submit_artifact"]);
			const result = await client.callTool({
				name: "vault_submit_artifact",
				arguments: { sourcePath: source, sourceTaskId: "forge-task", sourceOperation: "convert" },
			});
			expect(result.isError).toBe(false);
			expect(result.structuredContent).toMatchObject({ status: "pending_review", reviewValid: true });
			expect(existsSync(join(vault, "01 Inbox", "result.md"))).toBe(false);
		} finally {
			await client.close();
			await server.close();
		}
	});

	it("validates vault-local pi-forge configuration and forwards structured results", async () => {
		const root = temporaryDirectory();
		const vault = join(root, "vault");
		const readRoot = join(root, "read");
		const outputRoot = join(root, "output");
		mkdirSync(join(vault, ".pi-vault"), { recursive: true });
		mkdirSync(readRoot);
		mkdirSync(outputRoot);
		const serverScript = join(root, "fake-server.mjs");
		const launcher = join(root, "fake-server");
		const sdk = join(process.cwd(), "..", "..", "node_modules", "@modelcontextprotocol", "sdk", "dist", "esm");
		writeFileSync(
			serverScript,
			`import { Server } from ${JSON.stringify(`file://${join(sdk, "server", "index.js")}`)};
import { StdioServerTransport } from ${JSON.stringify(`file://${join(sdk, "server", "stdio.js")}`)};
import { CallToolRequestSchema, ListToolsRequestSchema } from ${JSON.stringify(`file://${join(sdk, "types.js")}`)};
const server = new Server({name:"fake",version:"1"},{capabilities:{tools:{}}});
server.setRequestHandler(ListToolsRequestSchema, async () => ({tools:[{name:"forge_convert_files",inputSchema:{type:"object"}}]}));
server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
  if (request.params.arguments?.slow === true) await new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, 10000);
    extra.signal.addEventListener("abort", () => { clearTimeout(timer); reject(extra.signal.reason); }, {once:true});
  });
  return {content:[{type:"text",text:"ok"}],structuredContent:{status:"success",operation:request.params.name}};
});
await server.connect(new StdioServerTransport());
`,
		);
		writeFileSync(launcher, `#!/bin/sh\nexec "${process.execPath}" "${serverScript}" "$@"\n`);
		chmodSync(launcher, 0o755);
		writeFileSync(
			join(vault, ".pi-vault", "config.yaml"),
			`version: 1\nsystem_dir: "00 System"\ninbox_dir: "01 Inbox"\nintegrations:\n  pi_forge:\n    command: ${JSON.stringify(launcher)}\n    read_roots:\n      - ${JSON.stringify(readRoot)}\n    output_root: ${JSON.stringify(outputRoot)}\n`,
		);
		const configuration = loadPiForgeIntegration(vault);
		const client = new PiForgeMcpClient(configuration);
		try {
			await expect(client.callTool("forge_convert_files", {})).resolves.toMatchObject({
				structuredContent: { status: "success", operation: "forge_convert_files" },
			});
			const controller = new AbortController();
			const pending = client.callTool("forge_convert_files", { slow: true }, controller.signal);
			setTimeout(() => controller.abort(), 25);
			await expect(pending).rejects.toThrow(/abort/i);
		} finally {
			await client.close();
			await client.close();
		}
	});

	it("keeps the pi-vault MCP stdio launcher protocol-clean", async () => {
		const root = temporaryDirectory();
		const vault = join(root, "vault");
		const artifacts = join(root, "artifacts");
		mkdirSync(vault);
		mkdirSync(artifacts);
		expect((await runVaultAgent(["--vault-root", vault, "init"], vault)).exitCode).toBe(0);
		const transport = new StdioClientTransport({
			command: process.execPath,
			args: [
				join(process.cwd(), "..", "..", "node_modules", "tsx", "dist", "cli.mjs"),
				join(process.cwd(), "src", "pi-vault", "mcp-cli.ts"),
				"--vault-root",
				vault,
				"--read-root",
				artifacts,
			],
			stderr: "pipe",
		});
		const client = new Client({ name: "stdio-test", version: "1.0.0" }, { capabilities: {} });
		try {
			await client.connect(transport);
			const tools = await client.listTools();
			expect(tools.tools.map((tool) => tool.name).sort()).toEqual(["vault_status", "vault_submit_artifact"]);
		} finally {
			await client.close();
		}
	});

	it("rejects malformed integration configuration before spawning", () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".pi-vault"));
		writeFileSync(join(root, ".pi-vault", "config.yaml"), "version: 1\nsystem_dir: System\ninbox_dir: Inbox\n");
		expect(() => loadPiForgeIntegration(root)).toThrow("integrations.pi_forge");
	});
});
