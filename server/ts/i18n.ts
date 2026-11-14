/** UI translations. English is the source catalog and the fallback; every
 * other catalog must cover the same keys (checked by the type system). */
export const LANGUAGES = ["en", "de"] as const;
export type Language = (typeof LANGUAGES)[number];
/** Stored values of the `display_language` setting. */
export const LANGUAGE_PREFERENCES = ["auto", ...LANGUAGES] as const;
export type LanguagePreference = (typeof LANGUAGE_PREFERENCES)[number];

const en = {
  "nav.dashboard": "Dashboard",
  "nav.readings": "Readings",
  "nav.scales": "Scales",
  "nav.users": "Users",
  "nav.sync": "Sync",
  "nav.settings": "Settings",
  "nav.firmware": "Firmware Bridge",
  "nav.signOut": "Sign Out",
  "time.unknown": "Unknown",
  "reading.receivedTime": "Received Time; Device Date Unverified",
  "reading.position": "Position {position}",
  "reading.positionUnspecified": "Unspecified",
  "metric.picker": "Measurement",
  "metric.show": "Show",
  "metric.weight_kg": "Weight",
  "metric.fat_mass_kg": "Fat Mass",
  "metric.fat_ratio_pct": "Body Fat",
  "metric.fat_free_mass_kg": "Fat-Free Mass",
  "metric.muscle_mass_kg": "Muscle Mass",
  "metric.water_mass_kg": "Water Mass",
  "metric.bone_mass_kg": "Bone Mass",
  "metric.heart_rate_bpm": "Heart Rate",
  "metric.visceral_fat_index": "Visceral Fat Index",
  "metric.basal_metabolic_rate_kcal": "Basal Metabolic Rate",
  "metric.metabolic_age_years": "Metabolic Age",
  "metric.pulse_wave_velocity_mps": "Pulse Wave Velocity",
  "metric.vascular_age_years": "Vascular Age",
  "dashboard.viewAllReadings": "View All Readings",
  "dashboard.allReadings": "All Readings →",
  "dashboard.when": "When",
  "dashboard.scale": "Scale",
  "dashboard.noReadings": "No readings recorded yet.",
  "dashboard.noUsers": "No users have been added yet.",
  "dashboard.addFirstScale": "Add Your First Scale",
  "settings.display": "Display",
  "settings.weightUnit": "Weight Unit",
  "settings.unit.kg": "Kilograms",
  "settings.unit.lb": "Pounds",
  "settings.unit.st": "Stones And Pounds",
  "settings.language": "Language",
  "settings.languageAuto": "Browser Default",
  "settings.saveDisplay": "Save Display Settings",
  "settings.displaySaved": "Display settings saved",
  "battery.chargeSoon": "Charge Soon",
  "battery.replace": "Replace Batteries",
  "battery.reportedTitle": "Battery reported {time}",
} as const;

export type MessageKey = keyof typeof en;
/** Every message key, in source order. */
export const MESSAGE_KEYS = Object.keys(en) as MessageKey[];

const de: Record<MessageKey, string> = {
  "nav.dashboard": "Dashboard",
  "nav.readings": "Messungen",
  "nav.scales": "Waagen",
  "nav.users": "Personen",
  "nav.sync": "Sync",
  "nav.settings": "Einstellungen",
  "nav.firmware": "Firmware-Bridge",
  "nav.signOut": "Abmelden",
  "time.unknown": "Unbekannt",
  "reading.receivedTime": "Empfangszeit; Gerätedatum nicht bestätigt",
  "reading.position": "Position {position}",
  "reading.positionUnspecified": "nicht angegeben",
  "metric.picker": "Messwert",
  "metric.show": "Anzeigen",
  "metric.weight_kg": "Gewicht",
  "metric.fat_mass_kg": "Fettmasse",
  "metric.fat_ratio_pct": "Körperfett",
  "metric.fat_free_mass_kg": "Fettfreie Masse",
  "metric.muscle_mass_kg": "Muskelmasse",
  "metric.water_mass_kg": "Körperwasser",
  "metric.bone_mass_kg": "Knochenmasse",
  "metric.heart_rate_bpm": "Herzfrequenz",
  "metric.visceral_fat_index": "Viszeralfett-Index",
  "metric.basal_metabolic_rate_kcal": "Grundumsatz",
  "metric.metabolic_age_years": "Stoffwechselalter",
  "metric.pulse_wave_velocity_mps": "Pulswellengeschwindigkeit",
  "metric.vascular_age_years": "Gefäßalter",
  "dashboard.viewAllReadings": "Alle Messungen",
  "dashboard.allReadings": "Alle Messungen →",
  "dashboard.when": "Zeitpunkt",
  "dashboard.scale": "Waage",
  "dashboard.noReadings": "Noch keine Messungen vorhanden.",
  "dashboard.noUsers": "Es wurden noch keine Personen angelegt.",
  "dashboard.addFirstScale": "Erste Waage hinzufügen",
  "settings.display": "Anzeige",
  "settings.weightUnit": "Gewichtseinheit",
  "settings.unit.kg": "Kilogramm",
  "settings.unit.lb": "Pfund",
  "settings.unit.st": "Stone und Pfund",
  "settings.language": "Sprache",
  "settings.languageAuto": "Browser-Standard",
  "settings.saveDisplay": "Anzeige speichern",
  "settings.displaySaved": "Anzeigeeinstellungen gespeichert",
  "battery.chargeSoon": "Bald aufladen",
  "battery.replace": "Batterien wechseln",
  "battery.reportedTitle": "Akkustand gemeldet am {time}",
};

const CATALOGS: Record<Language, Record<MessageKey, string>> = { en, de };

/** Locale used for dates and numbers in each language. */
export const LOCALES: Record<Language, string> = { en: "en-GB", de: "de-DE" };

/** Language names, always shown in their own language. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  de: "Deutsch",
};

export type Translate = (
  key: MessageKey,
  params?: Record<string, string | number>,
) => string;

/** Plain-text message lookup; callers escape the result for HTML. */
export function translator(language: Language): Translate {
  const catalog = CATALOGS[language];
  return (key, params) => {
    const text = catalog[key] ?? en[key];
    return params
      ? text.replace(/\{(\w+)\}/g, (match, name: string) =>
          name in params ? String(params[name]) : match,
        )
      : text;
  };
}

export function isLanguagePreference(
  value: unknown,
): value is LanguagePreference {
  return (LANGUAGE_PREFERENCES as readonly unknown[]).includes(value);
}

/** First supported language in an Accept-Language header, by quality. */
export function browserLanguage(header: string | null): Language | null {
  const ranked = (header ?? "")
    .split(",")
    .map((part, index) => {
      const [tag, ...attributes] = part.trim().split(";");
      const q = attributes
        .map((attribute) => attribute.trim().match(/^q=([\d.]+)$/))
        .find(Boolean);
      return {
        primary: tag.trim().toLowerCase().split("-")[0],
        quality: q ? Number(q[1]) : 1,
        index,
      };
    })
    .filter((entry) => entry.primary && entry.quality > 0)
    .sort((a, b) => b.quality - a.quality || a.index - b.index);
  for (const { primary } of ranked)
    if ((LANGUAGES as readonly string[]).includes(primary))
      return primary as Language;
  return null;
}

/** The stored preference wins; "auto" or no setting follows the browser,
 * falling back to English. */
export function resolveLanguage(
  preference: string | null,
  acceptLanguage: string | null,
): Language {
  if (preference && preference !== "auto" && isLanguagePreference(preference))
    return preference as Language;
  return browserLanguage(acceptLanguage) ?? "en";
}
