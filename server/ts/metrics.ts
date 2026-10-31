/** Known public Withings metric IDs. Unknown IDs remain available as raw measures.
 * Values retain the wire integer/exponent representation; named API values are
 * decimal strings so clients do not have to round binary floating-point values.
 */
export const METRICS = [
  { type: 1, key: "weight_kg", label: "Weight", unit: "kg" },
  { type: 8, key: "fat_mass_kg", label: "Fat Mass", unit: "kg" },
  { type: 6, key: "fat_ratio_pct", label: "Body Fat", unit: "%" },
  { type: 5, key: "fat_free_mass_kg", label: "Fat-Free Mass", unit: "kg" },
  { type: 76, key: "muscle_mass_kg", label: "Muscle Mass", unit: "kg" },
  { type: 77, key: "water_mass_kg", label: "Water Mass", unit: "kg" },
  { type: 88, key: "bone_mass_kg", label: "Bone Mass", unit: "kg" },
  { type: 11, key: "heart_rate_bpm", label: "Heart Rate", unit: "bpm" },
  {
    type: 170,
    key: "visceral_fat_index",
    label: "Visceral Fat Index",
    unit: "index",
  },
  {
    type: 226,
    key: "basal_metabolic_rate_kcal",
    label: "Basal Metabolic Rate",
    unit: "kcal/day",
  },
  {
    type: 227,
    key: "metabolic_age_years",
    label: "Metabolic Age",
    unit: "years",
  },
] as const;
export type Metric = (typeof METRICS)[number];
export type Measure = {
  type: number;
  value: number;
  unit: number;
  position?: number;
  [key: string]: unknown;
};

export function decimalValue(value: number, exponent: number): string {
  const sign = value < 0 ? "-" : "";
  let digits = String(Math.abs(value));
  if (exponent >= 0) return sign + digits + "0".repeat(exponent);
  digits = digits.padStart(-exponent + 1, "0");
  return sign + digits.slice(0, exponent) + "." + digits.slice(exponent);
}
export function storedMeasures(row: Record<string, any>): Measure[] {
  const parsed = JSON.parse(row.measures_json);
  return Array.isArray(parsed) ? parsed : [];
}
/** Keep free-form sensor metadata bounded before hashing or restoring it. */
export function validateMetricJson(value: unknown, depth = 0): void {
  if (depth > 16 || (typeof value === "number" && !Number.isFinite(value)))
    throw new Error("invalid metric metadata");
  if (value && typeof value === "object")
    for (const child of Object.values(value))
      validateMetricJson(child, depth + 1);
}
function canonical(value: any): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
export function validateStoredMetrics(row: Record<string, any>): void {
  const measures = JSON.parse(row.measures_json);
  validateMetricJson(measures);
  if (
    !Array.isArray(measures) ||
    measures.length > 32 ||
    measures.some(
      (m) =>
        !m ||
        typeof m !== "object" ||
        !Number.isSafeInteger(m.type) ||
        m.type < 1 ||
        m.type > 0xffff ||
        !Number.isSafeInteger(m.value) ||
        m.value < -(2 ** 31) ||
        m.value >= 2 ** 31 ||
        !Number.isSafeInteger(m.unit) ||
        m.unit < -12 ||
        m.unit > 12 ||
        (m.position !== undefined &&
          (!Number.isSafeInteger(m.position) ||
            m.position < 0 ||
            m.position > 0xffff)),
    )
  )
    throw new Error("Invalid stored measures");
  const weight = measures.find((m) => m.type === 1);
  if (
    weight &&
    (weight.value !== row.weight_value || weight.unit !== row.weight_unit)
  )
    throw new Error("Stored weight does not match measures");
  if (row.weight_value === null && (!measures.length || weight))
    throw new Error("Invalid metric-only reading");
  if (row.group_json !== null) {
    // A captured group is authoritative: heart-rate-only uploads cannot gain
    // a weight via the legacy columns during restore. Older ungrouped rows
    // can still use their original weight columns without a type-1 measure.
    if (row.weight_value !== null && !weight)
      throw new Error("Stored weight does not match measures");
    const group = JSON.parse(row.group_json);
    validateMetricJson(group);
    if (
      !group ||
      Array.isArray(group) ||
      group.meastime !== row.meastime ||
      canonical(group.measures) !== canonical(measures)
    )
      throw new Error("Invalid stored measurement group");
  }
}
export function namedMetrics(row: Record<string, any>): Record<string, string> {
  const measures = storedMeasures(row);
  return Object.fromEntries(
    METRICS.flatMap((metric) => {
      const found = measures.filter((m) => m.type === metric.type);
      if (metric.type === 1 && !found.length && row.weight_value != null)
        return [
          [
            metric.key,
            decimalValue(Number(row.weight_value), Number(row.weight_unit)),
          ],
        ];
      // Segmented readings must remain individually identifiable in measures;
      // don't arbitrarily choose a body segment as a whole-body metric.
      return found.length === 1
        ? [[metric.key, decimalValue(found[0].value, found[0].unit)]]
        : [];
    }),
  );
}
export async function observedMetrics(
  db: D1Database,
  userId?: number,
): Promise<Metric[]> {
  const result = await db
    .prepare(
      "SELECT DISTINCT json_extract(m.value,'$.type') AS type FROM readings r, json_each(r.measures_json) m" +
        (userId === undefined ? "" : " WHERE r.user_id=?"),
    )
    .bind(...(userId === undefined ? [] : [userId]))
    .all<{ type: number }>();
  const seen = new Set([1, ...result.results.map((r) => r.type)]);
  return METRICS.filter((m) => seen.has(m.type));
}
