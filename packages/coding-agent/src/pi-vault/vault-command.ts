import { existsSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { findVaultRoot } from "./extension.ts";
import { runVaultAgentSync } from "./vault-process.ts";

function takeOption(args: string[], name: string): { value?: string; remaining: string[] } {
	const index = args.indexOf(name);
	if (index === -1) return { remaining: args };
	const value = args[index + 1];
	return { value, remaining: args.filter((_item, itemIndex) => itemIndex !== index && itemIndex !== index + 1) };
}

function requireBootstrap(vaultRoot: string): boolean {
	if (existsSync(resolve(vaultRoot, ".pi-vault", "config.yaml"))) return true;
	console.error(
		`pi-vault: ${vaultRoot} is not initialized. Run \`pi-vault vault init --vault ${JSON.stringify(vaultRoot)}\`.`,
	);
	return false;
}

export function dispatchVaultCommand(args: string[], cwd: string): number {
	const command = args[0];
	if (!command) {
		console.error("Usage: pi-vault vault <init|status|maintain|review|undo|hermes-run> [options]");
		return 1;
	}
	const vaultOption = takeOption(args.slice(1), "--vault");
	const vaultRoot = resolve(cwd, vaultOption.value ?? findVaultRoot(cwd) ?? ".");
	let remaining = vaultOption.remaining;

	if (command !== "init" && command !== "hermes-run" && !requireBootstrap(vaultRoot)) return 1;

	switch (command) {
		case "init":
			return runVaultAgentSync(["--vault-root", vaultRoot, "init", ...remaining], cwd);
		case "status":
			return runVaultAgentSync(["--vault-root", vaultRoot, "status", ...remaining], cwd);
		case "maintain":
			return runVaultAgentSync(
				["--vault-root", vaultRoot, "autonomous-run", "--create-lock", "--apply-safe", ...remaining],
				cwd,
			);
		case "review":
			if (remaining.length === 0) remaining = ["--dry-run"];
			return runVaultAgentSync(["--vault-root", vaultRoot, "review-proposals", ...remaining], cwd);
		case "undo": {
			const runId = remaining[0];
			if (!runId) {
				console.error("Usage: pi-vault vault undo <run-id> [--vault <path>]");
				return 1;
			}
			return runVaultAgentSync(
				["--vault-root", vaultRoot, "version", "undo-run", runId, ...remaining.slice(1)],
				cwd,
			);
		}
		case "hermes-run": {
			const rootOption = takeOption(remaining, "--root");
			if (!rootOption.value) {
				console.error("Usage: pi-vault vault hermes-run --root <vault-parent> [options]");
				return 1;
			}
			const hermesRoot = resolve(cwd, rootOption.value);
			const uninitialized = readdirSync(hermesRoot, { withFileTypes: true })
				.filter((entry) => entry.isDirectory())
				.map((entry) => resolve(hermesRoot, entry.name))
				.filter((path) => !existsSync(resolve(path, ".pi-vault", "config.yaml")));
			if (uninitialized.length > 0) {
				console.error(`pi-vault: uninitialized vault directories under ${hermesRoot}: ${uninitialized.join(", ")}`);
				return 1;
			}
			return runVaultAgentSync(
				["--vault-root", vaultRoot, "hermes-run", "--hermes-root", hermesRoot, ...rootOption.remaining],
				cwd,
			);
		}
		default:
			console.error(`Unknown pi-vault vault command: ${command}`);
			return 1;
	}
}
