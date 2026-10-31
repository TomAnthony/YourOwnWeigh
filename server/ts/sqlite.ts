/** Local SQLite adapter for the D1-shaped interface used by the shared app. */
import { DatabaseSync, type StatementSync } from "node:sqlite";
import { readFileSync, mkdirSync, chmodSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));

type Value = string | number | null;
type Result<T = Record<string, unknown>> = {
  results: T[];
  meta: { changes: number; last_row_id: number };
};

class LocalStatement {
  private values: Value[] = [];
  private database: DatabaseSync;
  private sql: string;
  constructor(database: DatabaseSync, sql: string) {
    this.database = database;
    this.sql = sql;
  }
  bind(...values: Value[]): LocalStatement {
    const statement = new LocalStatement(this.database, this.sql);
    statement.values = values;
    return statement;
  }
  private prepared(): StatementSync {
    return this.database.prepare(this.sql);
  }
  async first<T = Record<string, unknown>>(): Promise<T | null> {
    return (this.prepared().get(...this.values) as T | undefined) ?? null;
  }
  async all<T = Record<string, unknown>>(): Promise<Result<T>> {
    return {
      results: this.prepared().all(...this.values) as T[],
      meta: { changes: 0, last_row_id: 0 },
    };
  }
  async run(): Promise<Result> {
    const result = this.prepared().run(...this.values);
    return {
      results: [],
      meta: {
        changes: Number(result.changes),
        last_row_id: Number(result.lastInsertRowid),
      },
    };
  }
  // A batch must run synchronously between BEGIN and COMMIT. Do not await inside it.
  runInBatch(): Result {
    const statement = this.prepared();
    if (statement.columns().length)
      return {
        results: statement.all(...this.values) as Record<string, unknown>[],
        meta: { changes: 0, last_row_id: 0 },
      };
    const result = statement.run(...this.values);
    return {
      results: [],
      meta: {
        changes: Number(result.changes),
        last_row_id: Number(result.lastInsertRowid),
      },
    };
  }
}

export class LocalSqlite {
  private database: DatabaseSync;
  constructor(path: string) {
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    this.database = new DatabaseSync(path);
    this.database.exec(
      "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=10000; PRAGMA synchronous=FULL;",
    );
    // Take the writer lock before inspecting the schema. Another process may
    // finish an upgrade (and accept new readings) while this opener is waiting.
    try {
      this.database.exec("BEGIN IMMEDIATE");
      try {
        this.initializeSchema();
        this.database.exec("COMMIT");
      } catch (error) {
        this.database.exec("ROLLBACK");
        throw error;
      }
    } catch (error) {
      this.database.close();
      throw error;
    }
    try {
      chmodSync(path, 0o600);
    } catch {
      /* Windows may not support mode changes. */
    }
  }
  /** Called only while holding the startup transaction's writer lock. */
  private initializeSchema(): void {
    const schema = readFileSync(
      join(ROOT, "server/migrations/0002_scale_core.sql"),
      "utf8",
    );
    this.database.exec(schema);
    this.upgradeOlderDatabase();
    this.database.exec(
      readFileSync(
        join(ROOT, "server/migrations/0003_admin_sessions.sql"),
        "utf8",
      ),
    );
    this.database.exec(
      readFileSync(
        join(ROOT, "server/migrations/0004_health_sync.sql"),
        "utf8",
      ),
    );
    this.database.exec(
      readFileSync(
        join(ROOT, "server/migrations/0005_integrated_setup.sql"),
        "utf8",
      ),
    );
    this.database.exec(
      readFileSync(
        join(ROOT, "server/migrations/0007_diagnostic_retention.sql"),
        "utf8",
      ),
    );
    if (
      !(
        this.database.prepare("PRAGMA table_info(readings)").all() as Array<{
          name: string;
        }>
      ).some((c) => c.name === "group_json")
    ) {
      this.database.exec(
        readFileSync(
          join(ROOT, "server/migrations/0008_measurement_groups.sql"),
          "utf8",
        ),
      );
    }
  }
  private upgradeOlderDatabase(): void {
    const columns = (table: string): Set<string> =>
      new Set(
        (
          this.database.prepare(`PRAGMA table_info(${table})`).all() as Array<{
            name: string;
          }>
        ).map((row) => row.name),
      );
    const scale = columns("scales");
    const extraScale: Record<string, string> = {
      model: "TEXT NOT NULL DEFAULT 'WBS06'",
      reported_feature_mask: "INTEGER",
      reported_feature_at: "INTEGER",
      reported_mfgid: "INTEGER",
      time_zone: "TEXT",
      withings_capture: "TEXT",
      ble_name: "TEXT",
      ble_probe_identifier: "TEXT",
      ble_hardware_version: "INTEGER",
      ble_bootloader_version: "INTEGER",
      ble_firmware_version: "INTEGER",
      ble_rescue_version: "INTEGER",
      ble_wifi_ssid: "TEXT",
      ble_owner_host: "TEXT",
      ble_owner_transport: "TEXT",
      ble_captured_at: "INTEGER",
    };
    for (const [name, kind] of Object.entries(extraScale)) {
      if (!scale.has(name))
        this.database.exec(`ALTER TABLE scales ADD COLUMN ${name} ${kind}`);
    }
    if (!scale.has("firmware_version")) {
      this.database.exec(
        readFileSync(
          join(ROOT, "server/migrations/0006_firmware_observations.sql"),
          "utf8",
        ),
      );
    }
    if (!columns("readings").has("time_quality")) {
      this.database.exec(
        "ALTER TABLE readings ADD COLUMN time_quality TEXT NOT NULL DEFAULT 'trusted'",
      );
    }
    if (!columns("users").has("birth_date"))
      this.database.exec("ALTER TABLE users ADD COLUMN birth_date TEXT");
    if (!columns("users").has("reference_weight_at"))
      this.database.exec(
        readFileSync(
          join(ROOT, "server/migrations/0009_recognition_weight.sql"),
          "utf8",
        ),
      );
  }
  prepare(sql: string): LocalStatement {
    return new LocalStatement(this.database, sql);
  }
  async batch(statements: LocalStatement[]): Promise<Result[]> {
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const results = statements.map((statement) => statement.runInBatch());
      this.database.exec("COMMIT");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
  close(): void {
    this.database.close();
  }
  /** Structural compatibility with D1; Node alone imports node:sqlite. */
  asD1(): D1Database {
    return this as unknown as D1Database;
  }
}
