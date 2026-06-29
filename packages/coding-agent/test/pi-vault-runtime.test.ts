import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
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

function scopedVaultName(root: string): string {
	const resolvedRoot = realpathSync(root);
	const name = basename(resolvedRoot).replaceAll(/[^A-Za-z0-9._-]/g, "-") || "vault";
	const hash = createHash("sha256").update(resolvedRoot).digest("hex").slice(0, 16);
	return `${name}-${hash}`;
}

function vaultSessions(globalAgentDir: string, root: string): string {
	return join(globalAgentDir, "sessions", "vaults", scopedVaultName(root));
}

function onboardingSessions(globalAgentDir: string, root: string): string {
	return join(globalAgentDir, "sessions", "onboarding", scopedVaultName(root));
}

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("pi-vault runtime profile", () => {
	it("anchors nested launches to install-scoped runtime state", () => {
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
				vaultSessions(globalAgentDir, root),
			],
			cwd: root,
			debugLogPath: join(globalAgentDir, "logs", "vaults", scopedVaultName(root), "pi-vault-debug.log"),
			initialized: true,
		});
	});

	it("uses an install-scoped bootstrap session until onboarding selects a system folder", () => {
		const root = temporaryDirectory();
		const globalAgentDir = join(root, "global-agent");
		mkdirSync(join(root, ".obsidian"), { recursive: true });

		const profile = prepareVaultLaunch([], root, globalAgentDir);

		expect(profile?.initialized).toBe(false);
		expect(profile?.args).toEqual([
			"--no-approve",
			"--no-context-files",
			"--session-dir",
			onboardingSessions(globalAgentDir, root),
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

	it("migrates first-launch sessions into the install-scoped vault session folder", () => {
		const root = temporaryDirectory();
		const globalAgentDir = join(root, "global-agent");
		const onboardingSessions = join(root, ".pi-vault", "onboarding-sessions");
		mkdirSync(join(root, ".obsidian"), { recursive: true });
		mkdirSync(onboardingSessions, { recursive: true });
		writeFileSync(
			join(onboardingSessions, "first.jsonl"),
			`${JSON.stringify({ type: "session", version: 3, id: "first", timestamp: "2026-01-01", cwd: root })}\n`,
		);
		initializeVault(root);

		const profile = prepareVaultLaunch([], root, globalAgentDir);

		expect(existsSync(join(onboardingSessions, "first.jsonl"))).toBe(false);
		expect(existsSync(join(vaultSessions(globalAgentDir, root), "first.jsonl"))).toBe(true);
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

		const migratedSession = join(vaultSessions(globalAgentDir, root), "session.jsonl");
		expect(existsSync(legacySession)).toBe(false);
		expect(JSON.parse(readFileSync(migratedSession, "utf8").split("\n")[0]).cwd).toBe(root);
		expect(JSON.parse(readFileSync(join(globalAgentDir, "trust.json"), "utf8"))).toEqual({
			"/tmp/unrelated-project": false,
		});
		expect(JSON.parse(readFileSync(join(globalAgentDir, "settings.json"), "utf8"))).toEqual({ theme: "dark" });
	});
});
