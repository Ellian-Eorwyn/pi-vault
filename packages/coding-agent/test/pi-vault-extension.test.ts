import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CONFIG_DIR_NAME, ENV_AGENT_DIR, ENV_SESSION_DIR, USER_CONFIG_DIR_NAME } from "../src/config.ts";
import piVaultExtension, { findVaultRoot, loadVaultContext } from "../src/pi-vault/extension.ts";

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
		writeFileSync(join(root, "System", "0.01 agent", "vault-purpose.md"), "# Purpose\n\nResearch.");
		writeFileSync(join(root, "System", "0.01 agent", "retrieval", "01 vault-map.md"), "# Map\n\n- Notes");

		const context = loadVaultContext(root);

		expect(context).toContain("System folder: System");
		expect(context).toContain("Inbox folder: Capture");
		expect(context).toContain("Research.");
		expect(context).toContain("# Map");
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
