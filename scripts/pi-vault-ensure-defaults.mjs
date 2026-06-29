#!/usr/bin/env node

import { chmodSync, copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const sourceDir = process.argv[2];
if (!sourceDir) {
	throw new Error("source directory is required");
}

const installDir = resolve(process.env.PI_VAULT_INSTALL_DIR ?? join(homedir(), ".pi-vault"));
const agentDir = resolve(process.argv[3] ?? process.env.PI_VAULT_CODING_AGENT_DIR ?? join(installDir, "agent"));
const defaultsDir = join(resolve(sourceDir), "defaults/agent");
const modelsPath = join(agentDir, "models.json");
const settingsPath = join(agentDir, "settings.json");

mkdirSync(agentDir, { recursive: true });

if (!existsSync(modelsPath)) {
	copyFileSync(join(defaultsDir, "models.json"), modelsPath);
	chmodSync(modelsPath, 0o600);
}

const models = JSON.parse(
	readFileSync(modelsPath, "utf8")
		.replace(/"(?:\\.|[^"\\])*"|\/\/[^\n]*/g, (match) => (match[0] === '"' ? match : ""))
		.replace(/"(?:\\.|[^"\\])*"|,(\s*[}\]])/g, (match, tail) => tail ?? (match[0] === '"' ? match : "")),
);
const hasDefaultModel = models.providers?.local?.models?.some((model) => model.id === "code") === true;

if (!existsSync(settingsPath)) {
	copyFileSync(join(defaultsDir, "settings.json"), settingsPath);
	chmodSync(settingsPath, 0o600);
} else {
	const settings = JSON.parse(readFileSync(settingsPath, "utf8"));
	if (hasDefaultModel && settings.defaultProvider === undefined && settings.defaultModel === undefined) {
		settings.defaultProvider = "local";
		settings.defaultModel = "code";
		writeFileSync(settingsPath, `${JSON.stringify(settings, null, "\t")}\n`, { mode: 0o600 });
		chmodSync(settingsPath, 0o600);
	}
}
