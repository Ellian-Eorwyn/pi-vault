import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { prepareVaultLaunch } from "../src/pi-vault/vault-runtime.ts";

const temporaryDirectories: string[] = [];

function temporaryDirectory(): string {
	const directory = mkdtempSync(join(tmpdir(), "pi-vault-runtime-"));
	temporaryDirectories.push(directory);
	return directory;
}

function initializeVault(root: string, systemDir = "System"): void {
	mkdirSync(join(root, ".obsidian"), { recursive: true });
	mkdirSync(join(root, ".pi-vault"), { recursive: true });
	writeFileSync(
		join(root, ".pi-vault", "config.yaml"),
		`version: 1\nsystem_dir: ${JSON.stringify(systemDir)}\ninbox_dir: "Inbox"\n`,
	);
}

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("pi-vault runtime profile", () => {
	it("anchors nested launches and runtime state to the configured system folder", () => {
		const root = temporaryDirectory();
		const nested = join(root, "Projects", "Nested");
		const globalAgentDir = join(root, "global-agent");
		initializeVault(root);
		mkdirSync(nested, { recursive: true });

		const profile = prepareVaultLaunch(["--approve"], nested, globalAgentDir);

		expect(profile).toEqual({
			args: [
				"--approve",
				"--no-approve",
				"--no-context-files",
				"--continue",
				"--session-dir",
				join(root, "System", "0.01 agent", "sessions"),
			],
			cwd: root,
			debugLogPath: join(root, "System", "0.01 agent", "pi-vault-debug.log"),
			initialized: true,
		});
	});

	it("uses a vault-local bootstrap session until onboarding selects a system folder", () => {
		const root = temporaryDirectory();
		mkdirSync(join(root, ".obsidian"), { recursive: true });

		const profile = prepareVaultLaunch([], root, join(root, "global-agent"));

		expect(profile?.initialized).toBe(false);
		expect(profile?.args).toEqual([
			"--no-approve",
			"--no-context-files",
			"--session-dir",
			join(root, ".pi-vault", "onboarding-sessions"),
		]);
	});

	it("respects explicit session selection flags", () => {
		const root = temporaryDirectory();
		initializeVault(root);

		for (const args of [["--resume"], ["--session", "chosen"], ["--no-session"]]) {
			const profile = prepareVaultLaunch(args, root, join(root, "global-agent"));
			expect(profile?.args).not.toContain("--continue");
		}
	});

	it("migrates first-launch sessions into the selected system folder", () => {
		const root = temporaryDirectory();
		const onboardingSessions = join(root, ".pi-vault", "onboarding-sessions");
		mkdirSync(join(root, ".obsidian"), { recursive: true });
		mkdirSync(onboardingSessions, { recursive: true });
		writeFileSync(
			join(onboardingSessions, "first.jsonl"),
			`${JSON.stringify({ type: "session", version: 3, id: "first", timestamp: "2026-01-01", cwd: root })}\n`,
		);
		initializeVault(root);

		const profile = prepareVaultLaunch([], root, join(root, "global-agent"));

		expect(existsSync(join(onboardingSessions, "first.jsonl"))).toBe(false);
		expect(existsSync(join(root, "System", "0.01 agent", "sessions", "first.jsonl"))).toBe(true);
		expect(profile?.args).toContain("--continue");
	});

	it("migrates legacy global sessions and removes vault trust entries", () => {
		const root = temporaryDirectory();
		const nested = join(root, "Notes");
		const globalAgentDir = join(root, "global-agent");
		const legacySessionDir = join(globalAgentDir, "sessions", "--legacy--");
		initializeVault(root);
		mkdirSync(nested, { recursive: true });
		mkdirSync(legacySessionDir, { recursive: true });
		const legacySession = join(legacySessionDir, "session.jsonl");
		writeFileSync(
			legacySession,
			`${JSON.stringify({ type: "session", version: 3, id: "test", timestamp: "2026-01-01", cwd: nested })}\n${JSON.stringify({ type: "message", id: "message", parentId: null })}\n`,
		);
		writeFileSync(
			join(globalAgentDir, "trust.json"),
			`${JSON.stringify({ [nested]: true, "/tmp/unrelated-project": false })}\n`,
		);
		writeFileSync(
			join(globalAgentDir, "settings.json"),
			`${JSON.stringify({ theme: "dark", sessionDir: "/tmp/legacy-sessions" })}\n`,
		);

		prepareVaultLaunch([], nested, globalAgentDir);

		const migratedSession = join(root, "System", "0.01 agent", "sessions", "session.jsonl");
		expect(existsSync(legacySession)).toBe(false);
		expect(JSON.parse(readFileSync(migratedSession, "utf8").split("\n")[0]).cwd).toBe(root);
		expect(JSON.parse(readFileSync(join(globalAgentDir, "trust.json"), "utf8"))).toEqual({
			"/tmp/unrelated-project": false,
		});
		expect(JSON.parse(readFileSync(join(globalAgentDir, "settings.json"), "utf8"))).toEqual({ theme: "dark" });
	});
});
