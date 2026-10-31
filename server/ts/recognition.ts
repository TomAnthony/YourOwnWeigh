/** Keep the scale's recognition reference in step with assigned weigh-ins.
 * The roster's `cr` is the measurement time, not the profile edit time. A
 * timestamp also stops old queued uploads or historical assignments replacing
 * a newer reference. This statement can follow an assignment/insert in a batch.
 */
export function refreshRecognitionWeight(
  db: D1Database,
  userId: number,
): D1PreparedStatement {
  return db
    .prepare(
      `WITH latest AS (
       SELECT ROUND(weight_value * CAST('1e' || weight_unit AS REAL),
                    MAX(0,-weight_unit)) AS kg, meastime
       FROM readings
       WHERE user_id=? AND time_quality='trusted'
         AND meastime BETWEEN 946684800 AND ?
         AND weight_unit BETWEEN -12 AND 12
         AND weight_value * CAST('1e' || weight_unit AS REAL) BETWEEN 2 AND 500
       ORDER BY meastime DESC, id DESC LIMIT 1
     )
     UPDATE users SET (reference_weight_kg,reference_weight_at) =
       (SELECT kg,meastime FROM latest)
     WHERE id=? AND EXISTS (
       SELECT 1 FROM latest
       WHERE reference_weight_at IS NULL OR meastime>reference_weight_at
     )`,
    )
    .bind(userId, Math.floor(Date.now() / 1000), userId);
}

/** Upgrade existing households lazily, including readings assigned before
 * recognition learning was introduced. No usable reading means keep the seed.
 */
export async function backfillRecognitionWeights(
  db: D1Database,
  users: Array<Record<string, any>>,
): Promise<void> {
  const missing = users.filter((u) => u.reference_weight_at === null);
  if (!missing.length) return;
  await db.batch(missing.map((u) => refreshRecognitionWeight(db, u.id)));
  for (const user of missing) {
    const reference = await db
      .prepare(
        "SELECT reference_weight_kg,reference_weight_at FROM users WHERE id=?",
      )
      .bind(user.id)
      .first();
    if (reference) Object.assign(user, reference);
  }
}
