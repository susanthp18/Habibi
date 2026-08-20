import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const cwd = "D:\\Hackathon\\Habibi";
const outDir = "D:\\Hackathon\\artifacts\\frontend-static-review";
mkdirSync(outDir, { recursive: true });

function run(name, command, args, { timeoutMs } = {}) {
  return new Promise((resolve) => {
    const started = Date.now();
    console.log(`[${new Date().toISOString()}] START ${name}: ${command} ${args.join(" ")}`);
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

    let timedOut = false;
    const timer =
      timeoutMs == null
        ? null
        : setTimeout(() => {
            timedOut = true;
            child.kill("SIGTERM");
            setTimeout(() => child.kill("SIGKILL"), 5000);
          }, timeoutMs);

    child.on("close", (code, signal) => {
      if (timer) clearTimeout(timer);
      const elapsedMs = Date.now() - started;
      const stdout = Buffer.concat(chunksOut).toString("utf8");
      const stderr = Buffer.concat(chunksErr).toString("utf8");
      console.log(
        `[${new Date().toISOString()}] END ${name} exit=${code} signal=${signal} timedOut=${timedOut} elapsed=${elapsedMs}ms`,
      );
      resolve({ name, code, signal, timedOut, elapsedMs, stdout, stderr });
    });
  });
}

function save(result, basename) {
  writeFileSync(path.join(outDir, `${basename}.stdout.txt`), result.stdout, "utf8");
  writeFileSync(path.join(outDir, `${basename}.stderr.txt`), result.stderr, "utf8");
  writeFileSync(
    path.join(outDir, `${basename}.meta.json`),
    JSON.stringify(
      {
        name: result.name,
        code: result.code,
        signal: result.signal,
        timedOut: result.timedOut,
        elapsedMs: result.elapsedMs,
        stdoutBytes: Buffer.byteLength(result.stdout),
        stderrBytes: Buffer.byteLength(result.stderr),
      },
      null,
      2,
    ),
    "utf8",
  );
  if (basename === "knip" || basename === "oxlint" || basename === "biome") {
    const raw = result.stdout.trim();
    if (raw) writeFileSync(path.join(outDir, `${basename}.json`), raw, "utf8");
  }
  if (basename === "tsc") {
    writeFileSync(path.join(outDir, "tsc.txt"), result.stdout + result.stderr, "utf8");
  }
}

const tsc = await run(
  "tsc",
  "node",
  [path.join(cwd, "node_modules\\typescript\\bin\\tsc"), "--noEmit", "--pretty", "false"],
  { timeoutMs: 180_000 },
);
save(tsc, "tsc");

const knipArgs = [
  "--yes",
  "knip",
  "--reporter",
  "json",
  "--no-progress",
  "--no-exit-code",
  "--ignore",
  "src/routeTree.gen.ts",
  "--entry",
  "src/start.ts",
  "--entry",
  "src/server.ts",
  "--entry",
  "src/router.tsx",
  "--entry",
  "src/routes/**/*.{ts,tsx}",
  "--entry",
  "scripts/*.{ts,mjs}",
];
const knip = await run("knip", "npx", knipArgs, { timeoutMs: 240_000 });
save(knip, "knip");

const oxlint = await run(
  "oxlint",
  "npx",
  ["--yes", "oxlint", "src", "--format", "json", "--ignore-pattern", "src/routeTree.gen.ts"],
  { timeoutMs: 180_000 },
);
save(oxlint, "oxlint");

const biome = await run(
  "biome",
  "npx",
  ["--yes", "@biomejs/biome", "check", "src", "--reporter=json", "--files-ignore-unknown=true"],
  { timeoutMs: 180_000 },
);
save(biome, "biome");

console.log("ALL_DONE");
