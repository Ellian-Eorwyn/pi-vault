import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CONFIG_DIR_NAME, ENV_AGENT_DIR, ENV_DEBUG_LOG, ENV_SESSION_DIR, USER_CONFIG_DIR_NAME } from "../src/config.ts";
import piVaultExtension, {
	buildVaultManageArgs,
	findVaultRoot,
	loadVaultContext,
	readBootstrap,
	startupAssessmentPrompt,
} from "../src/pi-vault/extension.ts";

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
		expect(context).toContain("no norms lock exists");
	});

	it("describes locked and provisional schema behavior in startup prompts", () => {
		const returning = startupAssessmentPrompt('{"schema_state":"locked"}', false);
		const onboarding = startupAssessmentPrompt('{"schema_state":"provisional"}', true);

		expect(returning).toContain("resumed conversation");
		expect(returning).toContain("follow the schema exactly");
		expect(onboarding).toContain("Begin onboarding now");
		expect(onboarding).toContain("default schema is provisional");
	});

	it("routes embedding manage actions through safe vault-agent commands", () => {
		expect(buildVaultManageArgs("/vault", { action: "embed-index" })).toEqual([
			"--vault-root",
			"/vault",
			"embed-index",
		]);
		expect(buildVaultManageArgs("/vault", { action: "semantic-search", query: "buddhist ethics", topK: 7 })).toEqual([
			"--vault-root",
			"/vault",
			"vault-search",
			"buddhist ethics",
			"--json",
			"--top-k",
			"7",
		]);
		expect(
			buildVaultManageArgs("/vault", {
				action: "related-links",
				maxNotes: 3,
				topK: 4,
				minSimilarity: 0.65,
			}),
		).toEqual([
			"--vault-root",
			"/vault",
			"--dry-run",
			"propose-related-links",
			"--max-notes",
			"3",
			"--top-k",
			"4",
			"--min-similarity",
			"0.65",
		]);
		expect(buildVaultManageArgs("/vault", { action: "related-links", dryRun: false })).toEqual([
			"--vault-root",
			"/vault",
			"propose-related-links",
		]);
	});

	it("requires a query for semantic search", () => {
		expect(buildVaultManageArgs("/vault", { action: "semantic-search" })).toEqual({
			error: "query is required for semantic-search.",
		});
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

	it("runs a hidden read-only assessment at startup", async () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".obsidian"));
		mkdirSync(join(root, ".pi-vault"), { recursive: true });
		writeFileSync(join(root, ".pi-vault", "config.yaml"), 'version: 1\nsystem_dir: "System"\ninbox_dir: "Inbox"\n');
		const handlers = new Map<string, (event: never, context: never) => Promise<void>>();
		const messages: Array<{
			message: { customType: string; display: boolean };
			options?: { triggerTurn?: boolean };
		}> = [];
		piVaultExtension({
			registerTool() {},
			on(event: string, handler: (event: never, context: never) => Promise<void>) {
				handlers.set(event, handler);
			},
			sendMessage(message: { customType: string; display: boolean }, options?: { triggerTurn?: boolean }) {
				messages.push({ message, options });
			},
		} as never);

		await handlers.get("session_start")?.(
			{ reason: "startup" } as never,
			{
				cwd: root,
				hasUI: true,
				mode: "tui",
				ui: { notify() {} },
			} as never,
		);

		expect(messages).toHaveLength(1);
		expect(messages[0]).toEqual({
			message: expect.objectContaining({ customType: "pi-vault-startup", display: false }),
			options: { triggerTurn: true },
		});
	});

	it("initializes default folders from one startup choice and begins onboarding", async () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".obsidian"));
		const handlers = new Map<string, (event: never, context: never) => Promise<void>>();
		const messageContents: string[] = [];
		let inputCalls = 0;
		piVaultExtension({
			registerTool() {},
			on(event: string, handler: (event: never, context: never) => Promise<void>) {
				handlers.set(event, handler);
			},
			sendMessage(message: { content: string }) {
				messageContents.push(message.content);
			},
		} as never);

		await handlers.get("session_start")?.(
			{ reason: "startup" } as never,
			{
				cwd: root,
				hasUI: true,
				mode: "tui",
				ui: {
					select: async () => "Use dashboard-first defaults: 00 Inbox, 01 Dashboards, and 99 System",
					input: async () => {
						inputCalls++;
						return undefined;
					},
					notify() {},
				},
			} as never,
		);

		expect(inputCalls).toBe(0);
		expect(readBootstrap(root)).toEqual(
			expect.objectContaining({
				version: 1,
				systemDir: "99 System",
				inboxDir: "00 Inbox",
				dashboardsDir: "01 Dashboards",
			}),
		);
		expect(messageContents).toHaveLength(1);
		expect(messageContents[0]).toContain("Begin onboarding now");
	});
});
