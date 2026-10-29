/** Household Cloudflare setup/update wrapper (both supported scale models).
 * npm run setup:cloudflare -- --name my-scales --deploy
 * --dry-run bundles locally using a placeholder D1 ID; creates no cloud resources.
 * Local state makes interrupted deployments retryable. Never writes secrets to
 * tracked configuration, never deletes databases, and never deploys implicitly.
 */
import { parseArgs } from "node:util";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import {
  mkdirSync,
  readFileSync,
  writeFileSync,
  existsSync,
  chmodSync,
} from "node:fs";
const { values } = parseArgs({
  options: {
    name: { type: "string" },
    deploy: { type: "boolean" },
    "dry-run": { type: "boolean" },
    help: { type: "boolean" },
  },
});
if (values.help) {
  console.log(
    "Usage: npm run setup:cloudflare -- --name my-scales (--deploy | --dry-run)",
  );
  process.exit(0);
}
if (
  !values.name ||
  !/^[a-z][a-z0-9-]{2,40}$/.test(values.name) ||
  !!values.deploy === !!values["dry-run"]
)
  throw new Error(
    "Choose a lowercase 3–41 character name and exactly one of --deploy or --dry-run",
  );
const root = fileURLToPath(new URL("../", import.meta.url));
const directory = join(
  root,
  "local/deployment",
  values.name + (values["dry-run"] ? "-dry-run" : ""),
);
mkdirSync(directory, { recursive: true, mode: 0o700 });
const cli = join(root, "node_modules/wrangler/bin/wrangler.js");
function wrangler(args, capture = false) {
  const result = spawnSync(process.execPath, [cli, ...args], {
    cwd: root,
    encoding: "utf8",
    stdio: capture ? "pipe" : "inherit",
    env: { ...process.env, WRANGLER_SEND_METRICS: "false" },
  });
  if (result.error) throw result.error;
  if (result.status !== 0)
    throw new Error(
      `Wrangler ${args[0]} failed. Resolve the error and rerun this same command.`,
    );
  return capture ? result.stdout : "";
}
const configPath = join(directory, "wrangler.json"),
  secretsPath = join(directory, "secrets.json");
const old = existsSync(configPath)
  ? JSON.parse(readFileSync(configPath, "utf8"))
  : null;
let databaseId = old?.d1_databases?.[0]?.database_id;
const databaseName = values.name + "-data";
if (values.deploy && !databaseId) {
  // Wrangler manages authentication. If needed, run npx wrangler login first.
  let databases = JSON.parse(wrangler(["d1", "list", "--json"], true));
  let found = databases.find((d) => d.name === databaseName);
  if (!found) {
    wrangler(["d1", "create", databaseName]);
    databases = JSON.parse(wrangler(["d1", "list", "--json"], true));
    found = databases.find((d) => d.name === databaseName);
  }
  if (!found?.uuid)
    throw new Error(
      "Database creation was not confirmed. Retry; the existing database will be reused.",
    );
  databaseId = found.uuid;
}
databaseId ??= "00000000-0000-0000-0000-000000000000";
const config = {
  name: values.name,
  main: join(root, "server/cloudflare/worker_ts.ts"),
  compatibility_date: "2026-10-26",
  workers_dev: true,
  assets: {
    directory: join(root, "server/static"),
    binding: "ASSETS",
    run_worker_first: true,
  },
  durable_objects: {
    bindings: [{ name: "YOW_BRIDGE", class_name: "BridgeDurableObject" }],
  },
  migrations: [
    { tag: "bridge-v1", new_sqlite_classes: ["BridgeDurableObject"] },
  ],
  d1_databases: [
    {
      binding: "DB",
      database_name: databaseName,
      database_id: databaseId,
      migrations_dir: join(root, "server/migrations"),
    },
  ],
};
writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n", {
  mode: 0o600,
});
if (!existsSync(secretsPath))
  writeFileSync(
    secretsPath,
    JSON.stringify({ YOW_BOOTSTRAP_TOKEN: randomBytes(32).toString("hex") }) +
      "\n",
    { mode: 0o600 },
  );
chmodSync(secretsPath, 0o600);
await import("./prepare_assets.mjs");
if (values.deploy) {
  wrangler([
    "d1",
    "migrations",
    "apply",
    "DB",
    "--remote",
    "--config",
    configPath,
  ]);
  wrangler(["deploy", "--config", configPath, "--secrets-file", secretsPath]);
  console.log(
    "\nOpen the HTTPS URL printed by Wrangler. First-run bootstrap token:",
  );
  console.log(
    JSON.parse(readFileSync(secretsPath, "utf8"))
      .YOW_BOOTSTRAP_TOKEN,
  );
  console.log(
    "Set your admin password immediately. After initialization this token cannot sign in.",
  );
} else
  wrangler([
    "deploy",
    "--config",
    configPath,
    "--dry-run",
    "--outdir",
    join(directory, "bundle"),
  ]);
console.log(`Deployment configuration: ${configPath}`);
