import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(new URL("..", import.meta.url).pathname);
const schema = resolve(root, "../../schemas/research-surface-api-v1.openapi.json");
const generated = resolve(root, "src/generated/surface-api.d.ts");
const tempRoot = mkdtempSync(join(tmpdir(), "tve-dashboard-openapi-"));
const candidate = join(tempRoot, "surface-api.d.ts");
const executable = resolve(root, "node_modules/.bin/openapi-typescript");

try {
  const result = spawnSync(executable, [schema, "-o", candidate], {
    cwd: root,
    encoding: "utf8",
  });
  if (result.error || result.status !== 0) {
    process.stderr.write(result.stderr || String(result.error));
    process.exit(result.status ?? 1);
  }
  const current = readFileSync(generated, "utf8");
  const next = readFileSync(candidate, "utf8");
  if (current !== next) {
    console.error("Generated Dashboard API types are stale; run pnpm api:generate");
    process.exit(1);
  }
  console.log("Generated Dashboard API types are current");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
