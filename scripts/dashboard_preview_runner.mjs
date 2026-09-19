import { spawn } from "node:child_process";

const [command, ...args] = process.argv.slice(2);
if (!command) {
  console.error("dashboard_preview_runner requires a command");
  process.exit(2);
}

let shuttingDown = false;
const child = spawn(command, args, {
  env: process.env,
  stdio: "inherit",
});

function requestShutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  child.kill("SIGINT");
}

process.on("SIGINT", requestShutdown);
process.on("SIGTERM", requestShutdown);

child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(shuttingDown ? 0 : (code ?? 1));
});
