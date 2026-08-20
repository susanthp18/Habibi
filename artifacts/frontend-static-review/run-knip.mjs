import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";

const cwd = "D:\\Hackathon\\Habibi";
const outDir = "D:\\Hackathon\\artifacts\\frontend-static-review";
const config = path.join(outDir, "knip.config.json");

function run(command, args) {
  return new Promise((resolve) => {
    const started = Date.now();
    console.log(`[${new Date().toISOString()}] START knip`);
    const child = spawn(command, args, {
      cwd,
      shell: true,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const chunksOut = [];
    const chunksErr = [];
    child.stdout.on("data", (d) => chunksOut.push(d));
    child.stderr.on("data", (d) => chunksErr.push(d));
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 5000);
    }, 240_000);
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      const elapsedMs = Date.now() - started;
      console.log(`[${new Date().toISOString()}] END knip exit=${code} elapsed=${elapsedMs}ms`);
      resolve({
        code,
        signal,
        elapsedMs,
        stdout: Buffer.concat(chunksOut).toString("utf8"),
        stderr: Buffer.concat(chunksErr).toString("utf8"),
      });
    });
  });
}

const result = await run("npx", [
  "--yes",
  "knip",
  "-c",
  config,
  "--reporter",
  "json",
  "--no-progress",
  "--no-exit-code",
]);

writeFileSync(path.join(outDir, "knip.stdout.txt"), result.stdout, "utf8");
writeFileSync(path.join(outDir, "knip.stderr.txt"), result.stderr, "utf8");
writeFileSync(
  path.join(outDir, "knip.meta.json"),
  JSON.stringify(
    {
      name: "knip",
      code: result.code,
      signal: result.signal,
      elapsedMs: result.elapsedMs,
      stdoutBytes: Buffer.byteLength(result.stdout),
      stderrBytes: Buffer.byteLength(result.stderr),
    },
    null,
    2,
  ),
  "utf8",
);
writeFileSync(path.join(outDir, "knip.json"), result.stdout.trim() || "{}", "utf8");
console.log("KNIP_DONE");
