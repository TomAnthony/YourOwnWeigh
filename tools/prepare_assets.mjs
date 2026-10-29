/** Copy the already signed, static Shortcut into Worker assets. No personalization
 * or signing occurs here. Run before Wrangler; the generated copy is ignored. */
import { copyFileSync } from "node:fs";
const root = new URL("../", import.meta.url);
copyFileSync(
  new URL("connectors/Apple Health/YourOwnWeigh Sync.shortcut", root),
  new URL("server/static/YourOwnWeigh-Sync.shortcut", root),
);
console.log("Static Apple Health Shortcut prepared.");
