import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CONFIG_DIR_NAME, ENV_AGENT_DIR, ENV_DEBUG_LOG, ENV_SESSION_DIR, USER_CONFIG_DIR_NAME } from "../src/config.ts";
import piVaultExtension, {
	buildContentProposeArgs,
	buildMaintainArgs,
	buildOrganizeProposeArgs,
	buildProcessNotesArgs,
	buildReadinessArgs,
	buildRecoveryArgs,
	buildRetrievalArgs,
	buildReviewApplyArgs,
	buildSchemaProposeArgs,
	buildSearchArgs,
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
		// Onboarding leads with the editable schema markdown and pauses for the user.
		expect(onboarding).toContain("editable schema markdown");
		expect(onboarding).toContain("0.00 Vault Schema.md");
		expect(onboarding).toContain("vault_schema_sync");
		expect(onboarding).toContain("schema_state is provisional");
	});

	it("threads the schema note path into the onboarding prompt", () => {
		const onboarding = startupAssessmentPrompt(
			'{"schema_state":"provisional"}',
			true,
			"99 System/0.00 Vault Schema.md",
		);
		expect(onboarding).toContain('"99 System/0.00 Vault Schema.md"');
	});

	describe("first-class vault tool builders", () => {
		it("vault_search builds read-only search argv and requires a query", () => {
			expect(buildSearchArgs("/vault", { query: "ethics", topK: 5 })).toEqual([
				"--vault-root",
				"/vault",
				"vault-search",
				"ethics",
				"--json",
				"--top-k",
				"5",
			]);
			expect(buildSearchArgs("/vault", { query: "  " })).toEqual({ error: "query is required for search." });
		});

		it("vault_search can never reach a write, index, propose, or apply path", () => {
			const forbidden = [
				"embed-index",
				"rebuild-retrieval",
				"propose-related-links",
				"propose-property",
				"propose-note-type",
				"propose-people",
				"propose-folder-refinement",
				"autonomous-run",
				"review-proposals",
				"norms-lock",
				"--apply-approved",
				"--apply-safe",
				"version",
				"--dry-run",
			];
			for (const params of [{ query: "a" }, { query: "a", topK: 1 }, { query: "a", topK: 100 }]) {
				const args = buildSearchArgs("/vault", params);
				expect(Array.isArray(args)).toBe(true);
				if (!Array.isArray(args)) continue;
				expect(args).toContain("vault-search");
				expect(args).toContain("--json");
				for (const flag of forbidden) expect(args).not.toContain(flag);
			}
		});

		it("vault_readiness builds the readiness and obsidian-check argv", () => {
			expect(buildReadinessArgs("/vault", { report: "readiness" })).toEqual([
				"--vault-root",
				"/vault",
				"organization-readiness",
				"--json",
			]);
			expect(buildReadinessArgs("/vault", { report: "obsidian" })).toEqual([
				"--vault-root",
				"/vault",
				"obsidian-check",
				"--json",
			]);
		});

		it("vault_retrieval builds embed/rebuild/related-links incl. dry-run default", () => {
			expect(buildRetrievalArgs("/vault", { operation: "embed-index" })).toEqual([
				"--vault-root",
				"/vault",
				"embed-index",
			]);
			expect(buildRetrievalArgs("/vault", { operation: "rebuild-retrieval" })).toEqual([
				"--vault-root",
				"/vault",
				"rebuild-retrieval",
			]);
			expect(
				buildRetrievalArgs("/vault", { operation: "related-links", maxNotes: 3, topK: 4, minSimilarity: 0.65 }),
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
			expect(buildRetrievalArgs("/vault", { operation: "related-links" })).toContain("--dry-run");
			expect(buildRetrievalArgs("/vault", { operation: "related-links", dryRun: false })).toEqual([
				"--vault-root",
				"/vault",
				"propose-related-links",
			]);
		});

		it("vault_schema_propose builds add-property/add-note-type and enforces required args", () => {
			expect(
				buildSchemaProposeArgs("/vault", {
					operation: "property",
					property: "domain",
					value: "legal",
					description: "Legal.",
				}),
			).toEqual([
				"--vault-root",
				"/vault",
				"propose-property",
				"--property",
				"domain",
				"--value",
				"legal",
				"--description",
				"Legal.",
				"--json",
			]);
			expect(
				buildSchemaProposeArgs("/vault", {
					operation: "note-type",
					name: "memo",
					description: "A memo.",
					folder: "06 Thoughts",
					title: "Memo",
				}),
			).toEqual([
				"--vault-root",
				"/vault",
				"propose-note-type",
				"--name",
				"memo",
				"--description",
				"A memo.",
				"--folder",
				"06 Thoughts",
				"--title",
				"Memo",
				"--json",
			]);
			expect(buildSchemaProposeArgs("/vault", { operation: "property" })).toEqual({
				error: "property and value are required to propose a property.",
			});
			expect(buildSchemaProposeArgs("/vault", { operation: "note-type", name: "memo" })).toEqual({
				error: "name, description, and folder are required to propose a note type.",
			});
		});

		it("vault_content_propose builds people/refine and requires a refine target", () => {
			expect(buildContentProposeArgs("/vault", { operation: "people", folder: "02 People", maxPeople: 5 })).toEqual([
				"--vault-root",
				"/vault",
				"propose-people",
				"--folder",
				"02 People",
				"--max-people",
				"5",
			]);
			expect(
				buildContentProposeArgs("/vault", { operation: "refine", folder: "05 Projects/Ex", maxNotes: 2 }),
			).toEqual([
				"--vault-root",
				"/vault",
				"propose-folder-refinement",
				"--folder",
				"05 Projects/Ex",
				"--max-notes",
				"2",
				"--dry-run",
			]);
			expect(buildContentProposeArgs("/vault", { operation: "refine" })).toEqual({
				error: "folder or note is required to refine.",
			});
		});

		it("vault_maintain builds scan/maintain/write-norms-lock with safe dry-run default", () => {
			expect(buildMaintainArgs("/vault", { operation: "scan" })).toEqual(["--vault-root", "/vault", "scan"]);
			expect(buildMaintainArgs("/vault", { operation: "write-norms-lock" })).toEqual([
				"--vault-root",
				"/vault",
				"norms-lock",
				"--write",
			]);
			expect(
				buildMaintainArgs("/vault", { operation: "maintain", applySafe: true, useLlm: true, maxNotes: 2 }),
			).toEqual([
				"--vault-root",
				"/vault",
				"autonomous-run",
				"--create-lock",
				"--apply-safe",
				"--use-llm",
				"--max-notes",
				"2",
				"--dry-run",
			]);
			expect(buildMaintainArgs("/vault", { operation: "maintain" })).toContain("--dry-run");
			expect(buildMaintainArgs("/vault", { operation: "refresh-dashboards" })).toEqual([
				"--vault-root",
				"/vault",
				"refresh-dashboard-table",
				"--json",
			]);
		});

		it("vault_schema_propose builds remap-properties argv", () => {
			expect(buildSchemaProposeArgs("/vault", { operation: "remap-properties", maxNotes: 50 })).toEqual([
				"--vault-root",
				"/vault",
				"propose-property-remap",
				"--max-notes",
				"50",
				"--json",
			]);
		});

		it("vault_organize_propose builds requested-dashboards argv", () => {
			expect(buildOrganizeProposeArgs("/vault", { operation: "requested-dashboards" })).toEqual([
				"--vault-root",
				"/vault",
				"propose-requested-dashboards",
				"--json",
			]);
		});

		it("vault_review_apply keeps review (dry-run) and apply-approved separate", () => {
			expect(buildReviewApplyArgs("/vault", { operation: "review" })).toEqual([
				"--vault-root",
				"/vault",
				"review-proposals",
				"--dry-run",
			]);
			expect(buildReviewApplyArgs("/vault", { operation: "apply-approved" })).toEqual([
				"--vault-root",
				"/vault",
				"review-proposals",
				"--apply-approved",
			]);
			expect(buildReviewApplyArgs("/vault", { operation: "review" })).not.toContain("--apply-approved");
		});

		it("vault_recovery builds undo and requires a run id", () => {
			expect(buildRecoveryArgs("/vault", { runId: "run-123" })).toEqual([
				"--vault-root",
				"/vault",
				"version",
				"undo-run",
				"run-123",
			]);
			expect(buildRecoveryArgs("/vault", { runId: "" })).toEqual({ error: "runId is required to undo a run." });
		});
	});

	describe("organization and processing tool builders", () => {
		it("vault_organize_propose builds dashboard/layout/folder proposals with --json", () => {
			expect(buildOrganizeProposeArgs("/vault", { operation: "base-hierarchy", useLlm: true, llmLimit: 3 })).toEqual(
				["--vault-root", "/vault", "propose-base-hierarchy", "--use-llm", "--llm-limit", "3", "--json"],
			);
			expect(buildOrganizeProposeArgs("/vault", { operation: "vault-layout" })).toEqual([
				"--vault-root",
				"/vault",
				"propose-vault-layout",
				"--json",
			]);
			expect(
				buildOrganizeProposeArgs("/vault", {
					operation: "folder-organization",
					folder: "05 Projects/Ex",
					project: "Ex",
					domain: "work",
					useLlm: true,
					checkpoint: true,
				}),
			).toEqual([
				"--vault-root",
				"/vault",
				"propose-folder-organization",
				"--folder",
				"05 Projects/Ex",
				"--project",
				"Ex",
				"--domain",
				"work",
				"--use-llm",
				"--checkpoint",
				"--json",
			]);
			expect(buildOrganizeProposeArgs("/vault", { operation: "inbox-sort", maxNotes: 10, safeOnly: true })).toEqual([
				"--vault-root",
				"/vault",
				"propose-inbox-sort",
				"--max-notes",
				"10",
				"--safe-only",
				"--json",
			]);
			expect(
				buildOrganizeProposeArgs("/vault", {
					operation: "index",
					indexType: "domain",
					value: "work",
					title: "Work",
				}),
			).toEqual([
				"--vault-root",
				"/vault",
				"propose-index",
				"--index-type",
				"domain",
				"--value",
				"work",
				"--title",
				"Work",
				"--json",
			]);
		});

		it("vault_organize_propose enforces required args and supports preview dry-run", () => {
			expect(buildOrganizeProposeArgs("/vault", { operation: "folder-organization" })).toEqual({
				error: "folder is required for folder-organization.",
			});
			expect(buildOrganizeProposeArgs("/vault", { operation: "index", indexType: "type" })).toEqual({
				error: "indexType and value are required for index.",
			});
			expect(buildOrganizeProposeArgs("/vault", { operation: "base-hierarchy", dryRun: true })).toEqual([
				"--vault-root",
				"/vault",
				"--dry-run",
				"propose-base-hierarchy",
				"--json",
			]);
		});

		it("vault_process_notes builds bounded passes and requires maxNotes for broad runs", () => {
			expect(
				buildProcessNotesArgs("/vault", { scope: "vault", stage: "classify-type", maxNotes: 5, useLlm: true }),
			).toEqual([
				"--vault-root",
				"/vault",
				"process-vault",
				"--stage",
				"classify-type",
				"--max-notes",
				"5",
				"--json",
			]);
			expect(
				buildProcessNotesArgs("/vault", {
					scope: "organize-pass",
					stage: "property-values",
					folder: "04 Work",
					useLlm: true,
					createLock: true,
				}),
			).toEqual([
				"--vault-root",
				"/vault",
				"organize-vault-pass",
				"--stage",
				"property-values",
				"--folder",
				"04 Work",
				"--use-llm",
				"--create-lock",
				"--json",
			]);
			expect(buildProcessNotesArgs("/vault", { scope: "reconcile", propertiesOnly: true })).toEqual([
				"--vault-root",
				"/vault",
				"reconcile",
				"--properties-only",
				"--json",
			]);
			expect(buildProcessNotesArgs("/vault", { scope: "vault", note: "A.md" })).toEqual([
				"--vault-root",
				"/vault",
				"process-vault",
				"--note",
				"A.md",
				"--json",
			]);
		});

		it("vault_process_notes rejects unbounded broad runs, including folder on process-vault", () => {
			expect(buildProcessNotesArgs("/vault", { scope: "vault" })).toEqual({
				error: "maxNotes is required for a broad vault run (no folder or note scope).",
			});
			// folder does not scope process-vault (no --folder flag), so it still needs maxNotes
			expect(buildProcessNotesArgs("/vault", { scope: "vault", folder: "04 Work" })).toEqual({
				error: "maxNotes is required for a broad vault run (no folder or note scope).",
			});
		});

		it("vault_schema_propose covers template and topic-hubs with --json", () => {
			expect(buildSchemaProposeArgs("/vault", { operation: "template", noteType: "source" })).toEqual([
				"--vault-root",
				"/vault",
				"propose-template",
				"--note-type",
				"source",
				"--json",
			]);
			expect(buildSchemaProposeArgs("/vault", { operation: "topic-hubs", domain: "work", minCluster: 3 })).toEqual([
				"--vault-root",
				"/vault",
				"propose-topic-hubs",
				"--domain",
				"work",
				"--min-cluster",
				"3",
				"--json",
			]);
			expect(buildSchemaProposeArgs("/vault", { operation: "template" })).toEqual({
				error: "noteType is required to propose a template.",
			});
		});

		it("vault_review_apply covers blocked-model review without touching apply-approved", () => {
			expect(buildReviewApplyArgs("/vault", { operation: "review-blocks", stage: "classify-type" })).toEqual([
				"--vault-root",
				"/vault",
				"review-model-blocks",
				"--dry-run",
				"--stage",
				"classify-type",
			]);
			expect(buildReviewApplyArgs("/vault", { operation: "approve-blocks-safe" })).toEqual([
				"--vault-root",
				"/vault",
				"review-model-blocks",
				"--approve-safe",
			]);
			expect(buildReviewApplyArgs("/vault", { operation: "approve-safe" })).toEqual([
				"--vault-root",
				"/vault",
				"review-proposals",
				"--agent-review",
				"--approve-safe",
			]);
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

	it("registers the first-class vault tools with safe execution modes", () => {
		const tools: Array<{ name: string; executionMode?: string }> = [];
		piVaultExtension({
			registerTool(tool: { name: string; executionMode?: string }) {
				tools.push(tool);
			},
			on() {},
		} as never);
		const names = tools.map((tool) => tool.name);
		for (const name of [
			"vault_status",
			"vault_readiness",
			"vault_search",
			"vault_retrieval",
			"vault_schema_propose",
			"vault_content_propose",
			"vault_organize_propose",
			"vault_process_notes",
			"vault_maintain",
			"vault_review_apply",
			"vault_recovery",
		]) {
			expect(names).toContain(name);
		}
		expect(names).not.toContain("vault_manage");
		// Mutating, index-refresh, and proposal-writing tools must be sequential.
		for (const name of [
			"vault_retrieval",
			"vault_schema_propose",
			"vault_content_propose",
			"vault_organize_propose",
			"vault_process_notes",
			"vault_maintain",
			"vault_review_apply",
			"vault_recovery",
		]) {
			expect(tools.find((tool) => tool.name === name)?.executionMode).toBe("sequential");
		}
		// Read-only tools stay parallel-safe.
		for (const name of ["vault_status", "vault_readiness", "vault_search"]) {
			expect(tools.find((tool) => tool.name === name)?.executionMode).not.toBe("sequential");
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
		expect(messageContents[0]).toContain("editable schema markdown");
		expect(messageContents[0]).toContain("99 System/0.00 Vault Schema.md");
		expect(messageContents[0]).toContain("vault_schema_sync");
	});
});
