import { accessSync, constants, existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { parse } from "yaml";

export interface PiForgeIntegrationConfig {
	command: string;
	readRoots: string[];
	outputRoot: string;
}

export function loadPiForgeIntegration(vaultRoot: string): PiForgeIntegrationConfig {
	const path = join(vaultRoot, ".pi-vault", "config.yaml");
	if (!existsSync(path)) throw new Error(`pi-forge integration requires initialized vault config: ${path}`);
	const value: unknown = parse(readFileSync(path, "utf8"));
	if (typeof value !== "object" || value === null) throw new Error(`${path} must contain a YAML mapping`);
	const integrations = (value as Record<string, unknown>).integrations;
	if (typeof integrations !== "object" || integrations === null) {
		throw new Error(`${path} is missing integrations.pi_forge`);
	}
	const forge = (integrations as Record<string, unknown>).pi_forge;
	if (typeof forge !== "object" || forge === null) throw new Error(`${path} is missing integrations.pi_forge`);
	const record = forge as Record<string, unknown>;
	if (typeof record.command !== "string") throw new Error("integrations.pi_forge.command must be an absolute path");
	if (!Array.isArray(record.read_roots) || record.read_roots.some((item) => typeof item !== "string")) {
		throw new Error("integrations.pi_forge.read_roots must be a non-empty list of absolute paths");
	}
	if (typeof record.output_root !== "string") {
		throw new Error("integrations.pi_forge.output_root must be an absolute path");
	}
	return {
		command: requireExecutable(record.command, "integrations.pi_forge.command"),
		readRoots: requireDirectories(record.read_roots as string[], "integrations.pi_forge.read_roots"),
		outputRoot: requireDirectory(record.output_root, "integrations.pi_forge.output_root"),
	};
}

export class PiForgeMcpClient {
	private clientPromise: Promise<Client> | undefined;
	private closed = false;
	private readonly configuration: PiForgeIntegrationConfig;

	constructor(configuration: PiForgeIntegrationConfig) {
		this.configuration = configuration;
	}

	async callTool(
		name: string,
		arguments_: Record<string, unknown>,
		signal?: AbortSignal,
	): Promise<Record<string, unknown>> {
		if (this.closed) throw new Error("pi-forge MCP client is closed");
		const client = await this.client();
		const result = await client.callTool({ name, arguments: arguments_ }, undefined, { signal });
		return result as Record<string, unknown>;
	}

	async close(): Promise<void> {
		if (this.closed) return;
		this.closed = true;
		const pending = this.clientPromise;
		this.clientPromise = undefined;
		if (pending) await (await pending).close();
	}

	private client(): Promise<Client> {
		if (!this.clientPromise) {
			this.clientPromise = this.connect().catch((error: unknown) => {
				this.clientPromise = undefined;
				throw error;
			});
		}
		return this.clientPromise;
	}

	private async connect(): Promise<Client> {
		const args = this.configuration.readRoots.flatMap((root) => ["--read-root", root]);
		args.push("--write-root", this.configuration.outputRoot);
		const transport = new StdioClientTransport({
			command: this.configuration.command,
			args,
			stderr: "inherit",
		});
		const client = new Client({ name: "pi-vault", version: "1.0.0" }, { capabilities: {} });
		await client.connect(transport);
		return client;
	}
}

function requireExecutable(value: string, label: string): string {
	if (!isAbsolute(value)) throw new Error(`${label} must be an absolute path`);
	const resolved = realpathSync(value);
	if (!statSync(resolved).isFile()) throw new Error(`${label} must resolve to a file: ${resolved}`);
	accessSync(resolved, constants.X_OK);
	return resolved;
}

function requireDirectories(values: string[], label: string): string[] {
	if (values.length === 0) throw new Error(`${label} must contain at least one path`);
	return values.map((value) => requireDirectory(value, label));
}

export function requireDirectory(value: string, label: string): string {
	if (!isAbsolute(value)) throw new Error(`${label} must contain only absolute paths`);
	const resolved = realpathSync(value);
	if (!statSync(resolved).isDirectory()) throw new Error(`${label} must resolve to a directory: ${resolved}`);
	return resolved;
}
