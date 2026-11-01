/** Supported scale models: the single registry behind every model branch.
 * `transport` and `hash` are literal unions, not booleans: the Wi-Fi session
 * protocol is selected from the enrolled device's model, never from caller
 * input.
 */
export type ScaleTransport = "ble" | "classic";
export type SessionHash = "md5" | "sha1" | "sha256";

export interface ScaleModel {
  transport: ScaleTransport;
  hash: SessionHash;
  /** Hash marker the device sends alongside the digest. */
  hashParam: { name: string; value: string } | null;
  hashLength: number;
  label: string;
  /** Display name on the Scales page. */
  fullLabel: string;
  /** Regex the enrolled device export's name must match. */
  namePattern: string;
  /** Firmware versions accepted at enrollment. */
  enrolledFirmware: readonly number[];
  /** Owner-firmware versions that enable server write (http-only for classic). */
  ownerFirmware: readonly number[];
  hostnameLimit: number;
  /** Classic models skip the settings-fixture and roster gates. */
  classicGates: boolean;
  /** Vendor migration: origin host and session auth variant. */
  vendor: { origin: string; hash: SessionHash; cgiBin: boolean };
}

export const SCALE_MODELS: Record<string, ScaleModel> = {
  WBS06: {
    transport: "ble",
    hash: "sha256",
    hashParam: { name: "hashmethod", value: "sha256" },
    hashLength: 64,
    label: "Body (WBS06)",
    fullLabel: "Body Scale (WBS06)",
    namePattern: "^Body$",
    exportFormat: "YOW-BLE-device-v1",
    bootloader: 4,
    enrolledFirmware: [1181, 123, 124, 125, 126, 127],
    ownerFirmware: [123, 124, 125, 126, 127],
    hostnameLimit: 48,
    classicGates: false,
    vendor: { origin: "https://scalews.withings.net", hash: "sha256", cgiBin: false },
  },
  WBS13: {
    transport: "ble",
    hash: "sha256",
    hashParam: { name: "hashmethod", value: "sha256" },
    hashLength: 64,
    label: "Body Smart (WBS13)",
    fullLabel: "Body Smart (WBS13)",
    namePattern: "^Body Smart$",
    exportFormat: "YOW-BLE-device-v1",
    bootloader: 2,
    enrolledFirmware: [100],
    ownerFirmware: [100, 101, 102, 103],
    hostnameLimit: 48,
    classicGates: false,
    vendor: { origin: "https://scalews.withings.net", hash: "sha256", cgiBin: false },
  },
  WBS03: {
    transport: "classic",
    hash: "md5",
    hashParam: null,
    hashLength: 32,
    label: "WS-30 (WBS03)",
    fullLabel: "Wireless Scale (WBS03 / WS-30)",
    namePattern: "WS-?30",
    exportFormat: "YOW-Classic-device-v1",
    bootloader: 15,
    enrolledFirmware: [921, 100, 101, 102],
    ownerFirmware: [100, 101, 102],
    hostnameLimit: 59,
    classicGates: true,
    vendor: { origin: "https://scalews.withings.net", hash: "md5", cgiBin: false },
  },
  WS50: {
    transport: "classic",
    hash: "sha1",
    hashParam: { name: "method", value: "sha" },
    hashLength: 40,
    label: "WS-50 (WS50)",
    fullLabel: "Smart Body Analyzer (WS50)",
    namePattern: "WS-?50",
    exportFormat: "YOW-Classic-device-v1",
    bootloader: 12,
    enrolledFirmware: [1721, 1021],
    ownerFirmware: [1021],
    hostnameLimit: 59,
    classicGates: true,
    vendor: { origin: "https://wbs02-ws.withings.net", hash: "sha1", cgiBin: true },
  },
};

export function scaleModel(model: string | null | undefined): ScaleModel | null {
  return (model != null && SCALE_MODELS[model]) || null;
}
