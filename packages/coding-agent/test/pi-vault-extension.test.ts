import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CONFIG_DIR_NAME, ENV_AGENT_DIR, ENV_DEBUG_LOG, ENV_SESSION_DIR, USER_CONFIG_DIR_NAME } from "../src/config.ts";
import piVaultExtension, { findVaultRoot, loadVaultContext, readBootstrap } from "../src/pi-vault/extension.ts";

const temporaryDirectories: string[] = [];

function temporaryDirectory(): string {
	const directory = mkdtempSync(join(tmpdir(), "pi-vault-extension-"));
	temporaryDirectories.push(directory);
	return directory;
}

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("pi-vault extension", () => {
	it("uses shell-safe environment variable names", () => {
		expect(ENV_AGENT_DIR).toBe("PI_VAULT_CODING_AGENT_DIR");
		expect(ENV_SESSION_DIR).toBe("PI_VAULT_CODING_AGENT_SESSION_DIR");
		expect(ENV_DEBUG_LOG).toBe("PI_VAULT_DEBUG_LOG");
		expect(USER_CONFIG_DIR_NAME).toBe(".pi-vault");
		expect(CONFIG_DIR_NAME).toBe(".pi");
	});

	it("detects a vault from a nested working directory", () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".obsidian"));
		mkdirSync(join(root, "Notes", "Nested"), { recursive: true });

		expect(findVaultRoot(join(root, "Notes", "Nested"))).toBe(root);
	});

	it("loads compact context from configured custom folders", () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".pi-vault"), { recursive: true });
		writeFileSync(join(root, ".pi-vault", "config.yaml"), 'version: 1\nsystem_dir: "System"\ninbox_dir: "Capture"\n');
		mkdirSync(join(root, "System", "0.01 agent", "retrieval"), { recursive: true });
		mkdirSync(join(root, "System", "0.02 templates"), { recursive: true });
		writeFileSync(join(root, "System", "0.01 agent", "vault-purpose.md"), "# Purpose\n\nResearch.");
		writeFileSync(join(root, "System", "0.01 agent", "schema.json"), '{"types":["source"]}');
		writeFileSync(join(root, "System", "0.02 templates", "0.022 folder norms.md"), "# Folder Norms\n\nShallow.");
		writeFileSync(join(root, "System", "0.01 agent", "retrieval", "01 vault-map.md"), "# Map\n\n- Notes");

		const context = loadVaultContext(root);

		expect(context).toContain("System folder: System");
		expect(context).toContain("Inbox folder: Capture");
		expect(context).toContain("Research.");
		expect(context).toContain("# Map");
		expect(context).toContain('"source"');
		expect(context).toContain("Shallow.");
		expect(context).toContain("System/0.01 agent/schema.json");
	});

	it("rejects bootstrap folders that escape the vault", () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".pi-vault"), { recursive: true });
		writeFileSync(
			join(root, ".pi-vault", "config.yaml"),
			'version: 1\nsystem_dir: "../outside"\ninbox_dir: "Inbox"\n',
		);

		expect(readBootstrap(root)).toBeUndefined();
	});

	it("registers all cross-product mutation tools as sequential", () => {
		const tools: Array<{ name: string; executionMode?: string }> = [];
		piVaultExtension({
			registerTool(tool: { name: string; executionMode?: string }) {
				tools.push(tool);
			},
			on() {},
		} as never);
		for (const name of ["forge_transcribe", "forge_convert_files", "vault_submit_artifact"]) {
			expect(tools.find((tool) => tool.name === name)?.executionMode).toBe("sequential");
		}
	});
});
