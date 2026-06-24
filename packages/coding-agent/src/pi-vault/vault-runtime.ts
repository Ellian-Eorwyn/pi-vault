import {
	existsSync,
	mkdirSync,
	readdirSync,
	readFileSync,
	realpathSync,
	rmdirSync,
	statSync,
	unlinkSync,
	writeFileSync,
} from "node:fs";
import { devNull } from "node:os";
import { basename, extname, join, resolve } from "node:path";
import { APP_NAME } from "../config.ts";
import { findVaultRoot, readBootstrap } from "./extension.ts";

export interface VaultLaunchProfile {
	args: string[];
	cwd: string;
	debugLogPath: string;
	initialized: boolean;
}

interface SessionMigration {
	source: string;
	destination: string;
	vaultRoot: string;
}

const onboardingSessionsDirectory = join(".pi-vault", "onboarding-sessions");

function hasExplicitSessionSelection(args: string[]): boolean {
	return args.some((arg) =>
		["--continue", "-c", "--resume", "-r", "--session", "--session-id", "--fork", "--no-session"].includes(arg),
	);
}

function isWithin(path: string, root: string): boolean {
	const relative = path.slice(root.length);
	return path === root || (path.startsWith(root) && (relative.startsWith("/") || relative.startsWith("\\")));
}

function readSessionHeader(path: string): Record<string, unknown> | undefined {
	const firstLine = readFileSync(path, "utf8").split("\n", 1)[0];
	if (!firstLine) return undefined;
	try {
		const value: unknown = JSON.parse(firstLine);
		return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : undefined;
	} catch {
		return undefined;
	}
}

function uniqueDestination(directory: string, filename: string, reserved: Set<string>): string {
	let destination = join(directory, filename);
	if (!existsSync(destination) && !reserved.has(destination)) {
		reserved.add(destination);
		return destination;
	}
	const extension = extname(filename);
	const stem = basename(filename, extension);
	let suffix = 1;
	while (existsSync(destination) || reserved.has(destination)) {
		destination = join(directory, `${stem}-migrated-${suffix}${extension}`);
		suffix++;
	}
	reserved.add(destination);
	return destination;
}

function collectLegacySessionMigrations(globalAgentDir: string): SessionMigration[] {
	const sessionsRoot = join(globalAgentDir, "sessions");
	if (!existsSync(sessionsRoot)) return [];
	const migrations: SessionMigration[] = [];
	const reservedDestinations = new Set<string>();
	for (const entry of readdirSync(sessionsRoot, { withFileTypes: true })) {
		if (!entry.isDirectory()) continue;
		const directory = join(sessionsRoot, entry.name);
		for (const filename of readdirSync(directory)) {
			if (!filename.endsWith(".jsonl")) continue;
			const source = join(directory, filename);
			if (!statSync(source).isFile()) continue;
			const header = readSessionHeader(source);
			const sessionCwd = typeof header?.cwd === "string" ? header.cwd : undefined;
			if (!sessionCwd || !existsSync(sessionCwd)) continue;
			const vaultRoot = findVaultRoot(sessionCwd);
			const bootstrap = vaultRoot ? readBootstrap(vaultRoot) : undefined;
			if (!vaultRoot || !bootstrap) continue;
			const sessionDir = join(vaultRoot, bootstrap.systemDir, "0.01 agent", "sessions");
			mkdirSync(sessionDir, { recursive: true });
			migrations.push({
				source,
				destination: uniqueDestination(sessionDir, filename, reservedDestinations),
				vaultRoot,
			});
		}
	}
	return migrations;
}

function migrateLegacySessions(globalAgentDir: string): string[] {
	const migrations = collectLegacySessionMigrations(globalAgentDir);
	const destinationBySource = new Map(migrations.map(({ source, destination }) => [resolve(source), destination]));
	const vaultRoots = new Set<string>();
	for (const migration of migrations) {
		const content = readFileSync(migration.source, "utf8");
		const newline = content.indexOf("\n");
		const header = readSessionHeader(migration.source);
		if (!header) continue;
		header.cwd = migration.vaultRoot;
		if (typeof header.parentSession === "string") {
			header.parentSession = destinationBySource.get(resolve(header.parentSession)) ?? header.parentSession;
		}
		const remainder = newline >= 0 ? content.slice(newline + 1) : "";
		writeFileSync(migration.destination, `${JSON.stringify(header)}\n${remainder}`, { flag: "wx", mode: 0o600 });
		unlinkSync(migration.source);
		vaultRoots.add(migration.vaultRoot);
	}
	const sessionsRoot = join(globalAgentDir, "sessions");
	if (existsSync(sessionsRoot)) {
		for (const entry of readdirSync(sessionsRoot, { withFileTypes: true })) {
			if (!entry.isDirectory()) continue;
			const directory = join(sessionsRoot, entry.name);
			if (readdirSync(directory).length === 0) rmdirSync(directory);
		}
		if (readdirSync(sessionsRoot).length === 0) rmdirSync(sessionsRoot);
	}
	return [...vaultRoots];
}

function migrateOnboardingSessions(vaultRoot: string, destinationDirectory: string): void {
	const sourceDirectory = join(vaultRoot, onboardingSessionsDirectory);
	if (!existsSync(sourceDirectory)) return;
	const filenames = readdirSync(sourceDirectory).filter((filename) => filename.endsWith(".jsonl"));
	const reserved = new Set<string>();
	const migrations = filenames.map((filename) => ({
		source: join(sourceDirectory, filename),
		destination: uniqueDestination(destinationDirectory, filename, reserved),
		vaultRoot,
	}));
	const destinationBySource = new Map(migrations.map(({ source, destination }) => [resolve(source), destination]));
	for (const migration of migrations) {
		const content = readFileSync(migration.source, "utf8");
		const newline = content.indexOf("\n");
		const header = readSessionHeader(migration.source);
		if (!header) continue;
		header.cwd = vaultRoot;
		if (typeof header.parentSession === "string") {
			header.parentSession = destinationBySource.get(resolve(header.parentSession)) ?? header.parentSession;
		}
		const remainder = newline >= 0 ? content.slice(newline + 1) : "";
		writeFileSync(migration.destination, `${JSON.stringify(header)}\n${remainder}`, { flag: "wx", mode: 0o600 });
		unlinkSync(migration.source);
	}
	if (readdirSync(sourceDirectory).length === 0) rmdirSync(sourceDirectory);
}

function cleanGlobalTrust(globalAgentDir: string, knownVaultRoots: string[]): void {
	const trustPath = join(globalAgentDir, "trust.json");
	if (!existsSync(trustPath)) return;
	const value: unknown = JSON.parse(readFileSync(trustPath, "utf8"));
	if (typeof value !== "object" || value === null || Array.isArray(value)) return;
	const trust = value as Record<string, unknown>;
	let changed = false;
	for (const path of Object.keys(trust)) {
		const resolvedPath = resolve(path);
		const discoveredRoot = existsSync(resolvedPath) ? findVaultRoot(resolvedPath) : undefined;
		if (
			(discoveredRoot && readBootstrap(discoveredRoot)) ||
			knownVaultRoots.some((vaultRoot) => isWithin(resolvedPath, vaultRoot))
		) {
			delete trust[path];
			changed = true;
		}
	}
	if (!changed) return;
	if (Object.keys(trust).length === 0) {
		unlinkSync(trustPath);
	} else {
		writeFileSync(trustPath, `${JSON.stringify(trust, null, 2)}\n`, { mode: 0o600 });
	}
}

function cleanGlobalSettings(globalAgentDir: string): void {
	const settingsPath = join(globalAgentDir, "settings.json");
	if (!existsSync(settingsPath)) return;
	const value: unknown = JSON.parse(readFileSync(settingsPath, "utf8"));
	if (typeof value !== "object" || value === null || Array.isArray(value)) return;
	const settings = value as Record<string, unknown>;
	if (settings.sessionDir === undefined) return;
	delete settings.sessionDir;
	writeFileSync(settingsPath, `${JSON.stringify(settings, null, "\t")}\n`, { mode: 0o600 });
}

function cleanGlobalVaultState(globalAgentDir: string, currentVaultRoot: string): void {
	const migratedVaultRoots = migrateLegacySessions(globalAgentDir);
	cleanGlobalTrust(globalAgentDir, [currentVaultRoot, ...migratedVaultRoots]);
	cleanGlobalSettings(globalAgentDir);
	const globalDebugLog = join(globalAgentDir, `${APP_NAME}-debug.log`);
	if (existsSync(globalDebugLog)) unlinkSync(globalDebugLog);
}

export function prepareVaultLaunch(
	args: string[],
	cwd: string,
	globalAgentDir: string,
): VaultLaunchProfile | undefined {
	const vaultRoot = findVaultRoot(cwd);
	if (!vaultRoot) return undefined;
	const bootstrap = readBootstrap(vaultRoot);
	const isolatedArgs = [...args, "--no-approve", "--no-context-files"];
	if (!bootstrap) {
		return {
			args: [...isolatedArgs, "--session-dir", join(vaultRoot, onboardingSessionsDirectory)],
			cwd: vaultRoot,
			debugLogPath: devNull,
			initialized: false,
		};
	}
	const vaultAgentDir = join(vaultRoot, bootstrap.systemDir, "0.01 agent");
	const systemDir = join(vaultRoot, bootstrap.systemDir);
	if (existsSync(systemDir) && !isWithin(realpathSync(systemDir), realpathSync(vaultRoot))) {
		throw new Error(`Configured system folder resolves outside the vault: ${systemDir}`);
	}
	mkdirSync(vaultAgentDir, { recursive: true });
	const sessionDirectory = join(vaultAgentDir, "sessions");
	mkdirSync(sessionDirectory, { recursive: true });
	migrateOnboardingSessions(vaultRoot, sessionDirectory);
	cleanGlobalVaultState(globalAgentDir, vaultRoot);
	return {
		args: [
			...isolatedArgs,
			...(hasExplicitSessionSelection(args) ? [] : ["--continue"]),
			"--session-dir",
			sessionDirectory,
		],
		cwd: vaultRoot,
		debugLogPath: join(vaultAgentDir, `${APP_NAME}-debug.log`),
		initialized: true,
	};
}
