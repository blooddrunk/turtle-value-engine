import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const CLIENT_DIRECTORY = resolve("dist/client");
const SECRET_ENV_NAMES = [
  "CLOUDFLARE_API_TOKEN",
  "SURFACE_API_ACCESS_CLIENT_ID",
  "SURFACE_API_ACCESS_CLIENT_SECRET",
  "TVE_DASHBOARD_ACCESS_CLIENT_ID",
  "TVE_DASHBOARD_ACCESS_CLIENT_SECRET",
];

function filesUnder(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...filesUnder(path));
    } else if (entry.isFile()) {
      files.push(path);
    }
  }
  return files;
}

if (!statSync(CLIENT_DIRECTORY, { throwIfNoEntry: false })?.isDirectory()) {
  console.error("Client bundle secret scan failed: dist/client is missing");
  process.exit(2);
}

const secrets = SECRET_ENV_NAMES.map((name) => process.env[name]).filter(
  (value) => value && value.length > 0,
);
if (secrets.length === 0) {
  console.error("Client bundle secret scan requires runtime secret sentinel values");
  process.exit(2);
}

for (const file of filesUnder(CLIENT_DIRECTORY)) {
  const contents = readFileSync(file, "utf8");
  if (secrets.some((secret) => contents.includes(secret))) {
    console.error(`Client bundle secret scan failed: ${relative(process.cwd(), file)}`);
    process.exit(1);
  }
}

console.log(`Client bundle secret scan passed (${filesUnder(CLIENT_DIRECTORY).length} files)`);
