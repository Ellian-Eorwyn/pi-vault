import { execFile, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

interface VaultAgentInvocation {
	command: string;
	args: string[];
	env: NodeJS.ProcessEnv;
}

export interface VaultAgentResult {
	exitCode: number;
	stdout: string;
	stderr: string;
}

export interface VaultToolResult {
	content: Array<{ type: "text"; text: string }>;
	details: Record<string, unknown>;
	isError: boolean;
}

/**
 * Run a vault-agent invocation and shape it into the standard tool result.
 * Parses stdout as JSON into `details.json` when the engine emitted JSON, otherwise
 * the raw stdout (or stderr on failure) is returned as text — matching the prior behavior.
 */
export async function runVaultTool(args: string[], vaultRoot: string, signal?: AbortSignal): Promise<VaultToolResult> {
	const result = await runVaultAgent(args, vaultRoot, signal);
	const details: Record<string, unknown> = { exitCode: result.exitCode, command: args };
	const trimmed = result.stdout.trim();
	if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
		try {
			details.json = JSON.parse(trimmed);
		} catch {
			// Not JSON after all; leave the text content as-is.
		}
	}
	return {
		content: [{ type: "text", text: result.stdout || result.stderr }],
		details,
		isError: result.exitCode !== 0,
	};
}

const moduleDirectory = dirname(fileURLToPath(import.meta.url));

function bundledEngineDirectory(): string | undefined {
	const candidates = [
		resolve(moduleDirectory, "vault-manager"),
		resolve(moduleDirectory, "..", "vault-manager"),
		resolve(moduleDirectory, "../../../..", "vault-manager"),
	];
	return candidates.find((candidate) => existsSync(join(candidate, "vault_agent", "__main__.py")));
}

function invocation(args: string[]): VaultAgentInvocation {
	const explicitAgent = process.env.PI_VAULT_AGENT;
	if (explicitAgent) {
		return { command: explicitAgent, args, env: process.env };
	}

	const installRoot = process.env.PI_VAULT_INSTALL_DIR ?? join(homedir(), ".pi-vault");
	const runtimeRoot = process.env.PI_VAULT_HOME ?? join(installRoot, "runtime");
	const managedPython = join(runtimeRoot, "venv", "bin", "python");
	const python = process.env.PI_VAULT_PYTHON ?? (existsSync(managedPython) ? managedPython : "python3");
	const engineDirectory = bundledEngineDirectory();
	const env = { ...process.env };
	if (engineDirectory) {
		env.PYTHONPATH = env.PYTHONPATH
			? `${engineDirectory}${process.platform === "win32" ? ";" : ":"}${env.PYTHONPATH}`
			: engineDirectory;
	}
	return { command: python, args: ["-m", "vault_agent", ...args], env };
}

export function runVaultAgentSync(args: string[], cwd: string): number {
	const child = invocation(args);
	try {
		execFileSync(child.command, child.args, {
			cwd,
			env: child.env,
			stdio: "inherit",
		});
		return 0;
	} catch (error: unknown) {
		if (typeof error === "object" && error !== null && "status" in error) {
			const status = (error as { status?: number }).status;
			return typeof status === "number" ? status : 1;
		}
		return 1;
	}
}

export function runVaultAgent(args: string[], cwd: string, signal?: AbortSignal): Promise<VaultAgentResult> {
	const child = invocation(args);
	return new Promise((resolveResult) => {
		execFile(
			child.command,
			child.args,
			{ cwd, env: child.env, signal, maxBuffer: 8 * 1024 * 1024 },
			(error, stdout, stderr) => {
				const exitCode =
					typeof (error as (NodeJS.ErrnoException & { code?: number }) | null)?.code === "number"
						? ((error as NodeJS.ErrnoException & { code: number }).code ?? 1)
						: error
							? 1
							: 0;
				resolveResult({ exitCode, stdout, stderr });
			},
		);
	});
}
