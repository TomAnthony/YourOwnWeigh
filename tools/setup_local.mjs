/** Start the local application and write a scale-only Caddy configuration.
 * npm run setup:local -- --scale-host 192.168.1.20
 * Dashboard stays on loopback:8080. Caddy forwards fixed scale ports to :8081.
 * This script never invokes sudo or changes the computer's network/firewall. */
import { parseArgs } from "node:util";
import { isIP } from "node:net";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync } from "node:fs";
const { values } = parseArgs({
  options: { "scale-host": { type: "string" }, help: { type: "boolean" } },
});
if (values.help) {
  console.log("Usage: npm run setup:local -- --scale-host YOUR_MAC_LAN_IP");
  process.exit(0);
}
if (
  !values["scale-host"] ||
  isIP(values["scale-host"]) !== 4 ||
  values["scale-host"].startsWith("127.")
)
  throw new Error("Provide this Mac’s LAN IPv4 address with --scale-host");
const root = fileURLToPath(new URL("../", import.meta.url)),
  folder = join(root, "local/deployment/local");
mkdirSync(folder, { recursive: true, mode: 0o700 });
const file = join(folder, "Caddyfile");
const config = process.env;
const scalePort = Number(config.YOW_SCALE_PORT || 8081);
if (!Number.isInteger(scalePort) || scalePort < 1 || scalePort > 65535)
  throw new Error("Invalid YOW_SCALE_PORT");
writeFileSync(
  file,
  `# Scale ports only. The dashboard/bridge remain on loopback:8080.\n{\n  auto_https disable_redirects\n  skip_install_trust\n  default_bind ${values["scale-host"]}\n}\nhttp://${values["scale-host"]}:80 {\n  reverse_proxy 127.0.0.1:${scalePort} {\n    header_up Host 127.0.0.1:${scalePort}\n  }\n}\nhttps://${values["scale-host"]}:443 {\n  tls internal\n  reverse_proxy 127.0.0.1:${scalePort} {\n    header_up Host 127.0.0.1:${scalePort}\n  }\n}\n`,
  { mode: 0o600 },
);
console.log(
  `In a second Terminal, run: sudo caddy run --config '${file.replaceAll("'", "'\\''")}'`,
);
console.log(
  `Configure the scale with ${values["scale-host"]} (WBS06: HTTPS; WS-30: HTTP).`,
);
process.env.YOW_SCALE_PORT ??= config.YOW_SCALE_PORT ?? "8081";
const { startLocal } = await import("../server/ts/local.ts");
await startLocal();
