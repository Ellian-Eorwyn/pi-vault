#!/usr/bin/env node
/**
 * CLI entry point for the refactored coding agent.
 * Uses main.ts with AgentSession and new mode modules.
 *
 * Test with: npx tsx src/cli-new.ts [args...]
 */
import { APP_NAME, ENV_DEBUG_LOG, getAgentDir } from "./config.ts";
import { configureHttpDispatcher } from "./core/http-dispatcher.ts";
import { main } from "./main.ts";
import piVaultExtension from "./pi-vault/extension.ts";
import { dispatchVaultCommand } from "./pi-vault/vault-command.ts";
import { prepareVaultLaunch } from "./pi-vault/vault-runtime.ts";

process.title = APP_NAME;
process.env.PI_CODING_AGENT = "true";
process.emitWarning = (() => {}) as typeof process.emitWarning;

// Configure undici's global dispatcher before provider SDKs issue requests.
// Runtime settings are applied once SettingsManager has loaded global/project settings.
configureHttpDispatcher();

const args = process.argv.slice(2);
if (args[0] === "vault") {
	process.exitCode = dispatchVaultCommand(args.slice(1), process.cwd());
} else {
	const isHubCommand = ["config", "install", "list", "remove", "update"].includes(args[0] ?? "");
	const profile = isHubCommand ? undefined : prepareVaultLaunch(args, process.cwd(), getAgentDir());
	if (profile) {
		process.chdir(profile.cwd);
		process.env[ENV_DEBUG_LOG] = profile.debugLogPath;
	}
	main(profile?.args ?? (isHubCommand ? [...args, "--no-approve"] : args), {
		extensionFactories: [piVaultExtension],
	});
}
