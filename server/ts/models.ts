/** Supported scale models: the single registry behind every model branch.
 * `transport` and `hash` are literal unions, not booleans: the Wi-Fi session
 * protocol is selected from the enrolled device's model, never from caller
 * input.
 */
export type ScaleTransport = "ble" | "classic";
export type SessionHash = "md5" | "sha256";

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
  /** Device export schema accepted at enrollment. */
  exportFormat: "YOW-BLE-device-v1" | "YOW-Classic-device-v1";
  /** Bootloader version accepted at enrollment. */
  bootloader: number;
  /** Firmware versions accepted at enrollment. */
  enrolledFirmware: readonly number[];
  /** Owner-firmware versions that enable server write (http-only for classic). */
  ownerFirmware: readonly number[];
  hostnameLimit: number;
  /** Classic models skip the settings-fixture and roster gates. */
  classicGates: boolean;
  /** Build the roster from selected household users, without vendor import. */
  localRoster: boolean;
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
    localRoster: false,
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
    enrolledFirmware: [100, 101, 102, 103],
    ownerFirmware: [100, 101, 102, 103],
    hostnameLimit: 48,
    classicGates: false,
    localRoster: true,
  },
  WBS04: {
    transport: "ble",
    hash: "sha256",
    hashParam: { name: "hashmethod", value: "sha256" },
    hashLength: 64,
    label: "Body Cardio (WBS04)",
    fullLabel: "Body Cardio (WBS04)",
    namePattern: "^Body Cardio$",
    exportFormat: "YOW-BLE-device-v1",
    bootloader: 12,
    enrolledFirmware: [2231, 100, 101, 102],
    ownerFirmware: [100, 101, 102],
    hostnameLimit: 48,
    classicGates: false,
    localRoster: false,
  },
  WBS05: {
    transport: "ble",
    hash: "sha256",
    hashParam: { name: "hashmethod", value: "sha256" },
    hashLength: 64,
    label: "Body+ (WBS05)",
    fullLabel: "Body+ (WBS05)",
    namePattern: "^Body\\+$",
    exportFormat: "YOW-BLE-device-v1",
    bootloader: 6,
    enrolledFirmware: [1651, 100],
    ownerFirmware: [100],
    hostnameLimit: 48,
    classicGates: false,
    localRoster: true,
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
    localRoster: false,
  },
  WBS02: {
    transport: "classic",
    hash: "md5",
    hashParam: null,
    hashLength: 32,
    label: "WS-50 (WBS02)",
    fullLabel: "Smart Body Analyzer (WBS02)",
    namePattern: "WS-?50",
    exportFormat: "YOW-Classic-device-v1",
    bootloader: 12,
    enrolledFirmware: [1721, 1023],
    ownerFirmware: [1023],
    hostnameLimit: 59,
    classicGates: true,
    localRoster: false,
  },
};

export function scaleModel(model: string | null | undefined): ScaleModel | null {
  return model != null && Object.hasOwn(SCALE_MODELS, model) ? SCALE_MODELS[model] : null;
}
