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

	const managedPython = join(homedir(), ".pi-vault", "runtime", "venv", "bin", "python");
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
