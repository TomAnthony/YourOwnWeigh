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
  "common.continue": "Continue",
  "common.delete": "Delete",
  "common.edit": "Edit",
  "common.later": "Later",
  "setup.welcome": "Welcome To YourOwnWeigh",
  "setup.tokenIntro": "Enter the bootstrap token shown by the setup command.",
  "setup.token": "Bootstrap Token",
  "setup.passwordTitle": "Set Your Password",
  "setup.passwordIntro":
    "Protect your dashboard and Sync API. Passwords must contain at least eight characters.",
  "auth.adminPassword": "Admin Password",
  "setup.confirmAdmin": "Confirm Admin Password",
  "sync.alternativePassword": "Set Alternative Password For Sync API",
  "setup.syncPassword": "Sync API Password",
  "setup.syncConfirm": "Confirm Sync API Password",
  "setup.create": "Create Household",
  "auth.signIn": "Sign In",
  "health.notAcknowledged": "Not Acknowledged",
  "health.acknowledged": "Acknowledged",
  "readings.user": "User",
  "readings.healthSync": "Health Sync",
  "readings.actions": "Actions",
  "readings.unassigned": "Unassigned",
  "readings.assignTo": "Assign To",
  "readings.chooseUser": "Choose User",
  "readings.assign": "Assign",
  "readings.confirmDelete": "Delete this unassigned reading permanently?",
  "userReadings.back": "← Dashboard",
  "userReadings.title": "{name} Readings",
  "userReadings.attribution": "Attribution",
  "userReadings.none": "No readings recorded for this user.",
  "attribution.device": "device",
  "attribution.ambiguous": "ambiguous",
  "attribution.unassigned": "unassigned",
  "attribution.manual": "manual",
  "users.name": "Name",
  "users.shortName": "Short Name",
  "users.heightCm": "Height (cm)",
  "users.height": "Height",
  "users.birthDate": "Date of Birth",
  "users.approxAge": "Approximate Age (if DOB unknown)",
  "users.ageDob": "Age / DOB",
  "users.sex": "Sex",
  "users.male": "Male",
  "users.female": "Female",
  "users.recognitionWeight": "Recognition Weight (kg)",
  "users.recognitionHint":
    "Updated from the latest assigned weigh-in and sent on the scale’s next Wi-Fi sync.",
  "users.importWithings": "Import From Withings",
  "users.add": "Add User",
  "users.importFrom": "Import Users From {scale}",
  "users.settingsReady": "Device settings are ready.",
  "users.settingsIncomplete":
    "Device settings import is incomplete; use Finish Device Import on Scales to retry.",
  "users.retained": "Existing users are retained.",
  "users.allPresent": "All users are already in this household.",
  "users.importSelected": "Import Selected Users",
  "users.status": "Status",
  "users.active": "Active",
  "users.retired": "Retired",
  "users.importIntro":
    "Read the selected scale’s existing users and settings over verified HTTPS. New users are shown for selection; existing local users are preserved.",
  "users.chooseScale": "Choose Scale",
  "users.fetch": "Fetch From Withings",
  "users.importUnavailable": "Withings import is unavailable on this server.",
  "users.save": "Save User",
  "users.edit": "Edit {name}",
  "users.retire": "Retire User",
  "users.delete": "Delete User",
  "users.confirmDelete":
    "Delete this user locally? Their readings will become unassigned.",
  "setup.pageTitle": "First-Run Setup",
  "bridge.notConnected": "Python Bridge Not Connected",
  "bridge.disconnectHint":
    "Disconnect from this server. An active firmware transfer continues locally.",
  "bridge.disconnect": "Disconnect Bridge",
  "bridge.connectTitle": "Connect The Python Bridge",
  "bridge.connectIntro":
    "Run the bridge on your Mac or Linux computer and leave it running while setting up a scale.",
  "bridge.stepInstall": "Install: ",
  "bridge.stepRunBefore": "Run ",
  "bridge.stepRunAfter": " in Terminal.",
  "bridge.stepInvite": "Generate an invitation and paste it into Terminal.",
  "bridge.newInvitation": "Generate Connection Invitation",
  "bridge.copyInvitation": "Copy Invitation",
  "bridge.invitation": "Connection Invitation",
  "bridge.invitationHint":
    "Invitations last ten minutes. Allow Bluetooth access for Terminal when macOS asks.",
  "bridge.connect": "Connect",
  "bridge.disconnected": "Disconnected",
  "bridge.setupMode":
    "Put your scale into setup mode with its hardware button.",
  "bridge.scanBleHint":
    "Find Body, Body+, Body Cardio and Body Smart scales using Bluetooth Low Energy.",
  "bridge.scanBle": "Scan BLE",
  "bridge.scanClassicHint":
    "Find WS-30, WS-50 and Body (WBS06 v551) scales using Bluetooth Classic.",
  "bridge.scanClassic": "Scan Classic",
  "bridge.identifyTitle": "Help Identify This Scale",
  "bridge.identifyIntro":
    "This scale answered the identity probe, but its model is not yet supported for setup or updates. You can ask Withings what firmware it offers without installing anything. The device MAC and secret are used for this request and are excluded from the details you copy.",
  "bridge.modelCode": "Model Code From Scale Label",
  "bridge.reportVersion": "Firmware Version To Report",
  "bridge.manufacturerId": "Manufacturer ID (If Known)",
  "bridge.reportHint":
    "Reporting one version below the probed version can reveal the current stock image. A missing offer does not prove that no firmware exists.",
  "bridge.checkOffer": "Check Withings Firmware Offer",
  "bridge.offerUrl": "Firmware URL",
  "bridge.offerHint":
    "Metadata reported by Withings. The image has not been downloaded or verified.",
  "bridge.copyIssue": "Copy GitHub Issue Details",
  "bridge.completeHint":
    "End setup without changing Wi-Fi, hostname, or other settings.",
  "bridge.complete": "Complete Setup",
  "bridge.disconnectScale": "Disconnect Scale",
  "bridge.probe": "Retry Connection Check",
  "bridge.revealSecret": "Reveal Secret",
  "bridge.importDevice": "Import Device",
  "bridge.exportDevice": "Download Device Export",
  "bridge.firmware": "Firmware",
  "bridge.firmwareIntro":
    "Download stock firmware and generate YourOwnWeigh firmware. Files stay on the computer running the bridge.",
  "bridge.generateWbs06": "Generate Firmware For WBS06",
  "bridge.selectManually": "Select Manually",
  "bridge.install": "Send Update To Device",
  "bridge.downloadFirmware": "Download Firmware",
  "bridge.progress": "Firmware Progress",
  "bridge.configure": "Configure",
  "bridge.readConfig": "Read From Scale",
  "bridge.server": "Server",
  "bridge.serverHost": "Server Hostname",
  "bridge.useThisHost": "Use This Server’s Hostname",
  "bridge.transport": "Transport",
  "bridge.setServer": "Save Server On Scale",
  "bridge.wifi": "Wi-Fi",
  "bridge.wifiSsid": "Wi-Fi Name (SSID)",
  "bridge.wifiPassword": "Wi-Fi Password",
  "bridge.wifiPasswordHint":
    "Enter the password to save or reconnect this network.",
  "bridge.connectWifi": "Save And Connect Wi-Fi",
  "common.timeZone": "Time Zone",
  "bridge.setTime": "Save Time Zone",
  "bridge.timeHint":
    "Time-zone changes are also sent on future Wi-Fi syncs for an imported scale.",
  "common.notifications": "Notifications",
  "bridge.flashTitle": "Install Firmware?",
  "bridge.flashIntro":
    "This replaces an external firmware slot. Keep the scale powered and the Python bridge running until transfer finishes. Keep your original firmware backup and recovery instructions.",
  "bridge.flashPrompt": "Type FLASH",
  "bridge.confirmFlash": "Confirm Update",
  "common.cancel": "Cancel",
  "bridge.enrollTitle": "Import Device To Server?",
  "bridge.enrollIntro":
    "Save this scale and check Withings for existing users and settings. You choose which new users to import.",
  "bridge.deviceLabel": "Scale Name",
  "bridge.rosterTitle": "Import Users",
  "bridge.scaleTimeZone": "Scale Time Zone",
  "scales.goff": "UTC Offset (Seconds)",
  "scales.dst": "Next DST Change (Unix Time)",
  "scales.ngoff": "Next UTC Offset (Seconds)",
  "scales.featureMask": "Feature Mask",
  "scales.betaWs": "Beta Services (0 Or 1)",
  "scales.tempCode": "Temperature Unit Code",
  "scales.weightCode": "Weight Unit Code",
  "scales.editSettings": "Edit Settings",
  "scales.usersOnScale": "Users On This Scale",
  "scales.usersOnScaleIntro":
    "Choose the local users to send on each sync. This replaces the scale’s current roster; Withings import is unavailable for this model.",
  "scales.addUserFirst": "{link} first.",
  "scales.addUserLink": "Add A User",
  "scales.advanced": "Advanced",
  "scales.lastSync": "Last Sync",
  "scales.notYetSeen": "Not Yet Seen",
  "scales.advancedHint":
    "Internal protocol settings. The selected time zone supplies clock offsets automatically.",
  "scales.classicRetains":
    "This model retains its internal settings and on-scale users.",
  "scales.saveSettings": "Save Settings",
  "scales.finishImport": "Finish Device Import",
  "scales.importUsers": "Import Users From Withings",
  "scales.firmwareSeenWifi":
    "Last confirmed {time} via Wi-Fi sync. This is the last observed running version.",
  "scales.firmwareSeenBle":
    "Last confirmed {time} via Bluetooth. This is the last observed running version.",
  "scales.firmwareUnknown":
    "No firmware version observed yet. Connect and probe this scale, import its device export, or let it sync over Wi-Fi.",
  "scales.firmwareConfirmation": "Firmware Confirmation",
  "scales.notYetConfirmed": "Not Yet Confirmed",
  "scales.ready": "Ready",
  "scales.chooseUsers": "Choose Users",
  "scales.importIncomplete": "Import Incomplete",
  "scales.model": "Model",
  "scales.secret": "Secret",
  "scales.clickToReveal": "(Click To Reveal)",
  "scales.none": "No scales yet.",
  "scales.connectFirst": "Connect A Scale",
  "scales.importFile": "Import Device File",
  "scales.nameOptional": "Name (Optional)",
  "scales.deviceExport": "Device Export",
  "sync.appleHealth": "Apple Health",
  "sync.shortcutIntro":
    "Download the static signed Shortcut, then set its first three Text actions. You can install and configure it on your Mac; iCloud syncs it to Shortcuts on your iPhone. Run it on the iPhone to grant Health access.",
  "sync.download": "Download YourOwnWeigh Sync",
  "sync.serverUrl": "Server URL",
  "sync.userId": "User ID Or Three-Letter Name",
  "sync.addUserFirst": "Add a user first.",
  "sync.password": "Password",
  "sync.passwordHint":
    "Your Sync API password (the admin password unless you set a separate one).",
  "sync.automationHint":
    "For a daily sync, create a Personal Automation in iPhone Shortcuts: Time Of Day → 09:00 → Daily → Run Immediately → Run Shortcut → YourOwnWeigh Sync. Run the Shortcut manually any time too.",
  "sync.http": "Read Over HTTP",
  "sync.httpIntro":
    "Use a numeric user ID or an unambiguous three-letter display name. Requests return JSON and do not mark readings as imported into Apple Health.",
  "sync.curlHint":
    "curl prompts for the password. Use HTTPS for remote servers. The household credential can read every user; the selected ID controls this request, not access rights.",
  "sync.readingsHint":
    "<code>/readings</code> returns all measurement groups, named metrics and raw values. Follow <code>next_cursor</code> using the <code>cursor</code> parameter to paginate. <code>/weights</code> remains available for weight-only clients.",
  "sync.healthSyncHint":
    "The Apple Shortcut uses the separate <code>health-sync/next</code> and <code>health-sync/ack</code> endpoints so it acknowledges a reading only after writing it to Health.",
  "settings.backup": "Backup And Restore",
  "settings.backupIntro": "Back up your household or restore a saved export.",
  "settings.export": "Export Database",
  "settings.import": "Import Database",
  "settings.exportHint":
    "Exports include device secrets and password hashes. Keep them private.",
  "common.close": "Close",
  "settings.importIntro":
    "Choose a saved database export. You can review it before adding missing data or replacing the household.",
  "settings.backupFile": "Backup File",
  "settings.importHint":
    "Your current passwords stay unless you explicitly choose to restore access settings.",
  "settings.reviewImport": "Review Import",
  "settings.currentAdmin": "Current Admin Password",
  "settings.newPassword": "New Password",
  "settings.confirmPassword": "Confirm Password",
  "settings.changeAdmin": "Change Admin Password",
  "settings.newSync": "New Sync Password",
  "settings.confirmSync": "Confirm Sync Password",
  "settings.saveSync": "Save Sync Password Settings",
  "settings.syncSeparate": "The Sync API uses a separate password.",
  "settings.syncShared":
    "The Sync API uses this password too. Update your Shortcut after changing it.",
  "bridge.targetModel": "Target Model",
  "battery.label": "Battery",
  "battery.notReported": "Not Yet Reported",
  "battery.reported": "Reported {time}",
  "msg.aScaleCanHaveAtMost": "A scale can have at most eight users",
  "msg.adminPasswordChangedOtherSessionsWere":
    "Admin password changed; other sessions were signed out",
  "msg.administrationPasswordSet": "Administration password set",
  "msg.captureBelongsToADifferentScale": "Capture belongs to a different scale",
  "msg.captureContainsAnInvalidUser": "Capture contains an invalid user",
  "msg.captureExceeds128Kb": "Capture exceeds 128 KB",
  "msg.captureHasNoTimeOrDevice": "Capture has no time or device settings",
  "msg.captureHasNoValidRoster": "Capture has no valid roster",
  "msg.captureIsMissingValidScreenIds":
    "Capture is missing valid screen IDs (cs) for a user",
  "msg.captureLacksDisplayResponses": "Capture lacks display responses",
  "msg.captureRemovesExistingRosterUsersReview":
    "Capture removes existing roster users; review separately",
  "msg.captureStagedReviewUsersBeforeImport":
    "Capture staged. Review users before import.",
  "msg.capturedFeatureMaskDiffersFromAuthenticated":
    "Captured feature mask differs from authenticated scale request",
  "msg.capturedFeatureMaskDiffersFromScale":
    "Captured feature mask differs from scale",
  "msg.capturedRoutingSelectorPointsToA":
    "Captured routing selector points to a Withings beta host",
  "msg.capturedScaleSettingsImported": "Captured scale settings imported",
  "msg.capturedSettingsDoNotMatchThis":
    "Captured settings do not match this scale's reported feature mask",
  "msg.chooseABackupFileOfAt": "Choose a backup file of at most 10 MiB",
  "msg.chooseACaptureJsonFile": "Choose a capture JSON file",
  "msg.chooseADeviceEnrollmentJsonFile": "Choose a device enrollment JSON file",
  "msg.chooseAKnownScale": "Choose a known scale",
  "msg.chooseATimeZone": "Choose a time zone",
  "msg.chooseActiveHouseholdUsers": "Choose active household users",
  "msg.chooseOneToEightUsersFor": "Choose one to eight users for this scale",
  "msg.chooseUsersFromThisImportedProfile":
    "Choose users from this imported profile",
  "msg.confirmTheReviewedImportFirst": "Confirm the reviewed import first",
  "msg.currentAdminPasswordIsIncorrect": "Current admin password is incorrect",
  "msg.deviceExportIsOlderThanThe": "Device export is older than the saved one",
  "msg.deviceRecordMustBeAtMost": "Device record must be at most 4 KB",
  "msg.deviceSavedTimeZoneChangesApply":
    "Device saved. Time-zone changes apply on the next Wi-Fi sync.",
  "msg.deviceSettingsImportedChooseAnyNew":
    "Device settings imported. Choose any new users to add.",
  "msg.directWithingsCaptureIsUnavailableIn":
    "Direct Withings capture is unavailable in this deployment",
  "msg.duplicateScaleSelection": "Duplicate scale selection",
  "msg.enrolledScaleHasADifferentSecret":
    "Enrolled scale has a different secret",
  "msg.fixtureExceeds16Kb": "Fixture exceeds 16 KB",
  "msg.fixtureMustHaveStatus0And": "Fixture must have status 0 and body",
  "msg.importedProfileChangedFetchItAgain":
    "Imported profile changed; fetch it again",
  "msg.invalidIanaTimeZone": "Invalid IANA time zone",
  "msg.invalidMacAddress": "Invalid MAC address",
  "msg.invalidWiFiSsid": "Invalid Wi‑Fi SSID",
  "msg.invalidBirthDate": "Invalid birth date",
  "msg.invalidBootstrapToken": "Invalid bootstrap token",
  "msg.invalidDeviceCaptureTime": "Invalid device capture time",
  "msg.invalidDeviceSecret": "Invalid device secret",
  "msg.invalidDisplayLanguage": "Invalid display language",
  "msg.invalidDisplayUnit": "Invalid display unit",
  "msg.invalidFirmwareVersion": "Invalid firmware version",
  "msg.invalidInternalDeviceSettings": "Invalid internal device settings",
  "msg.invalidOwnerTarget": "Invalid owner target",
  "msg.invalidPassword": "Invalid password",
  "msg.invalidProfileFields": "Invalid profile fields",
  "msg.invalidRosterBaseline": "Invalid roster baseline",
  "msg.invalidRosterRecord": "Invalid roster record",
  "msg.invalidScaleName": "Invalid scale name",
  "msg.invalidScaleSettings": "Invalid scale settings",
  "msg.invalidSummaryDate": "Invalid summary date",
  "msg.invalidWeatherSeries": "Invalid weather series",
  "msg.nameAndTimeZoneSavedOther":
    "Name and time zone saved; other on-scale settings are retained",
  "msg.newPasswordsDoNotMatch": "New passwords do not match",
  "msg.noReviewedCaptureForThisScale": "No reviewed capture for this scale",
  "msg.noUserIdsRemain": "No user IDs remain",
  "msg.onScaleRosterDeliveryIsNot":
    "On-scale roster delivery is not implemented for this model",
  "msg.ownerTransportRequiresAHost": "Owner transport requires a host",
  "msg.passwordMustContain8To1024":
    "Password must contain 8 to 1024 characters",
  "msg.passwordsDoNotMatch": "Passwords do not match",
  "msg.probeIdentityDoesNotMatchThe":
    "Probe identity does not match the registered scale",
  "msg.readingAssigned": "Reading assigned",
  "msg.readingCandidateListIsMalformed": "Reading candidate list is malformed",
  "msg.readingIsMissingOrAlreadyAssigned":
    "Reading is missing or already assigned",
  "msg.readingIsMissingOrAssigned": "Reading is missing or assigned",
  "msg.readingsApiPasswordSet": "Readings API password set",
  "msg.reviewedCaptureHasChanged": "Reviewed capture has changed",
  "msg.rosterBaselineOrUsersMissing": "Roster baseline or users missing",
  "msg.rosterBaselineSavedOneShotDelivery":
    "Roster baseline saved; one-shot delivery remains off",
  "msg.savedRosterIsMalformed": "Saved roster is malformed",
  "msg.savedScaleRosterIsMalformed": "Saved scale roster is malformed",
  "msg.scaleAddedImportAReviewedCapture":
    "Scale added. Import a reviewed capture to stage its settings and users.",
  "msg.scaleAlreadyHasActiveSettingsOr":
    "Scale already has active settings or fixtures",
  "msg.scaleConfigurationSaved": "Scale configuration saved",
  "msg.scaleImportedWithSettingsChooseAny":
    "Scale imported with settings. Choose any new users to add.",
  "msg.scaleLabelIsTooLong": "Scale label is too long",
  "msg.scaleOrWithingsImportUnavailable":
    "Scale or Withings import unavailable",
  "msg.scaleSavedChooseItsUsersIn":
    "Scale saved. Choose its users in Edit Settings before its first sync.",
  "msg.scaleSavedWithingsImportIsIncomplete":
    "Scale saved. Withings import is incomplete; use Finish Device Import to retry.",
  "msg.scaleSecretReplacedSessionsInvalidated":
    "Scale secret replaced; sessions invalidated",
  "msg.scaleSettingsAreAlreadyActiveReview":
    "Scale settings are already active; review changes in Device Config",
  "msg.secretMustContain1To256": "Secret must contain 1 to 256 characters",
  "msg.selectedUsersImportedExistingUsersRetained":
    "Selected users imported; existing users retained",
  "msg.separateSyncApiPasswordSaved": "Separate Sync API password saved",
  "msg.settingsSavedForTheNextWi":
    "Settings saved for the next Wi-Fi connection",
  "msg.signedIn": "Signed in",
  "msg.signedOut": "Signed out",
  "msg.summaryBodyMustBeAnArray": "Summary body must be an array",
  "msg.supplyALabelAndExactScale": "Supply a label and exact scale secret",
  "msg.syncApiNowUsesTheAdmin": "Sync API now uses the admin password",
  "msg.syncPasswordsDoNotMatch": "Sync passwords do not match",
  "msg.tooManyAttemptsTryAgainIn":
    "Too many attempts; try again in ten minutes",
  "msg.unassignedReadingDeleted": "Unassigned reading deleted",
  "msg.unexpectedCaptureFormat": "Unexpected capture format",
  "msg.unknownFixtureEndpoint": "Unknown fixture endpoint",
  "msg.unknownImportedUser": "Unknown imported user",
  "msg.unknownScale": "Unknown scale",
  "msg.unknownUser": "Unknown user",
  "msg.unsupportedDeviceEnrollmentRecord":
    "Unsupported device enrollment record",
  "msg.userAbsentFromRosterBaseline": "User absent from roster baseline",
  "msg.userDeletedLocallyTheirReadingsAre":
    "User deleted locally; their readings are now unassigned",
  "msg.userRetiredHistoricalReadingsRemain":
    "User retired; historical readings remain",
  "msg.userUpdatedRosterEditsWillBe":
    "User updated; roster edits will be sent to supported scales on their next connection",
  "msg.withingsImportIsUnavailable": "Withings import is unavailable",
  "msg.withingsImportUnavailable": "Withings import unavailable",
  "msg.displaySettingsSaved": "Display settings saved",
  "msg.requestFailed": "Request failed",
  "msg.endpointFixtureSaved": "{endpoint} fixture saved",
  "msg.modelUsesLocalUsersChooseThem":
    "{model} uses local users; choose them in Scales → Edit Settings",
  "msg.bleIdentityIsOutsideTheReviewed":
    "BLE identity is outside the reviewed {model} profile",
  "msg.classicIdentityIsOutsideTheReviewed":
    "Classic identity is outside the reviewed {model} profile",
  "msg.invalidDeviceKey": "Invalid device {key}",
  "msg.invalidKey": "Invalid {key}",
  "msg.userNameAddedAsStableScale": "User {name} added as stable scale ID {id}",
  "backup.reviewTitle": "Review Backup Import",
  "backup.merge": "Add Missing Data (Keep Existing Edits)",
  "backup.replace": "Replace Household Data",
  "backup.replaceHint":
    "Replacement removes current users, readings and devices.",
  "backup.exportFirst": "Export Current Data First",
  "backup.restoreAccess":
    "Restore Access Settings (Use The Backup’s Passwords And Sign Out)",
  "backup.confirmed": "I Have Reviewed This Import",
  "backup.importButton": "Import Backup",
  "backup.failedTitle": "Import Not Completed",
  "backup.backToSettings": "Back To Settings",
  "backup.section.users": "users",
  "backup.section.scales": "scales",
  "backup.section.scale_users": "scale users",
  "backup.section.readings": "readings",
  "backup.section.health_sync_receipts": "health sync receipts",
  "backup.section.reviewed_captures": "reviewed captures",
  "backup.section.events": "events",
  "backup.section.sync_audit": "sync audit",
  "backup.section.measure_attempts": "measure attempts",
  "backup.section.measure_rejections": "measure rejections",
  "msg.backupRestoredSignIn":
    "Backup restored. Sign in with the backup’s admin password.",
  "msg.backupImportedPasswords": "Backup imported. Current passwords retained.",
  "msg.backupConfirmationMismatch":
    "Backup confirmation does not match this preview",
  "msg.backupUnknownSection": "Backup contains an unknown section",
  "msg.backupTooLarge": "Backup exceeds 10 MiB",
  "msg.backupTooManyRows": "Backup exceeds 25,000 household rows",
  "msg.backupNoAdmin": "Backup has no admin password to restore",
  "msg.backupExpired": "Backup preview expired; upload it again",
  "msg.invalidAccessSettings": "Invalid access settings",
  "msg.invalidFirmwareObservation": "Invalid firmware observation",
  "msg.invalidScaleIdentity": "Invalid or duplicate scale identity",
  "msg.invalidPasswordHash": "Invalid password hash",
  "msg.invalidDeliveryFlags": "Invalid scale delivery flags",
  "msg.invalidStoredReading": "Invalid stored reading",
  "msg.invalidSyncMode": "Invalid Sync API password mode",
  "msg.invalidUserProfile": "Invalid user profile",
  "msg.missingReading": "Missing referenced reading",
  "msg.missingScale": "Missing referenced scale",
  "msg.missingUser": "Missing referenced user",
  "msg.unknownPreference": "Unknown preference",
  "msg.unknownRestoreMode": "Unknown restore mode",
  "msg.unsupportedBackup": "Unsupported backup format",
  "fw.dismissNotification": "Dismiss Notification",
  "fw.yourLoginExpiredReloadThisPage":
    "Your login expired. Reload this page and sign in.",
  "fw.serverReturnedAnUnexpectedResponse":
    "Server returned an unexpected response",
  "fw.requestFailedStatus": "Request failed ({status})",
  "fw.thisModelRequiresASeparateClient":
    "This Model Requires A Separate Client-Certificate Firmware Lookup",
  "fw.theScaleDidNotProvideThe":
    "The Scale Did Not Provide The Secret Required For This Lookup",
  "fw.connectedModel": "Connected: {model}",
  "fw.identificationRequired": "Identification Required",
  "fw.unrecognisedScale": "Unrecognised Scale",
  "fw.disconnected": "Disconnected",
  "fw.generateFirmwareForModel": "Generate Firmware For {model}",
  "fw.hostnameOrIpv4Address": "Hostname Or IPv4 Address",
  "fw.maximumLimitAsciiBytes": "Maximum {limit} ASCII Bytes",
  "fw.noSchemePathOrPort": "No Scheme, Path Or Port",
  "fw.enterThisComputerSLanAddress": "Enter This Computer’s LAN Address",
  "fw.useHost": "Use {host}",
  "fw.model": "Model",
  "fw.nameUnrecognisedTransport": "{name} (Unrecognised {transport})",
  "fw.unknown": "Unknown",
  "fw.notProvidedByScale": "Not Provided By Scale",
  "fw.checkingDeviceIdentity": "Checking Device Identity…",
  "fw.identityRead": "Identity Read",
  "fw.thisModelIsNotYetSupported": "This Model Is Not Yet Supported",
  "fw.connectedAndReady": "Connected And Ready",
  "fw.device": "Device",
  "fw.address": "Address",
  "fw.presence": "Presence",
  "fw.paired": "Paired",
  "fw.notSeenThisScan": "Not Seen This Scan",
  "fw.connectedToComputer": "Connected To Computer",
  "fw.seenThisScan": "Seen This Scan",
  "fw.connect": "Connect",
  "fw.availableWhenSeenNearbyOrWhen":
    "Available when seen nearby or when this scan finishes",
  "fw.stopScanningAndConnectToThis": "Stop scanning and connect to this scale",
  "fw.connectAndIdentifyThisScale": "Connect and identify this scale",
  "fw.scanning": "Scanning",
  "fw.scanComplete": "Scan Complete",
  "fw.scanStopped": "Scan Stopped",
  "fw.scanInterrupted": "Scan Interrupted",
  "fw.connectTheLocalPythonBridgeFirst":
    "Connect the local Python bridge first",
  "fw.noFinalResponseYetCheckThe":
    "No final response yet. Check the bridge terminal; an active firmware transfer continues locally.",
  "fw.pythonBridgeConnectedFromIp": "Python Bridge Connected From: {ip}",
  "fw.demonstrationNoHardware": "DEMONSTRATION — NO HARDWARE",
  "fw.pythonBridgeNotConnected": "Python Bridge Not Connected",
  "fw.reconnectingToServer": "Reconnecting To Server",
  "fw.browserConnectionInterruptedAnyActiveOta":
    "Browser connection interrupted. Any active OTA continues in the Python bridge; reconnect before issuing another command.",
  "fw.firmwareUpdate": "Firmware Update",
  "fw.reconnecting": "Reconnecting",
  "fw.lastReportedUpdateProgress": "Last Reported Update Progress",
  "fw.firmwareTransferDidNotCompleteCheck":
    "Firmware Transfer Did Not Complete. Check The Bridge Terminal.",
  "fw.firmwareTransferComplete": "Firmware Transfer Complete",
  "fw.reconnectToConfirmTheRunningVersion":
    "Reconnect To Confirm The Running Version",
  "fw.saveThisScaleThenChooseIts":
    "Save this scale, then choose its local users in Scales → Edit Settings. Withings user import is unavailable for this model.",
  "fw.saveThisScaleAndCheckWithings":
    "Save this scale and check Withings for existing users and settings. You choose which new users to import.",
  "fw.unknownFirmware": "Unknown Firmware",
  "fw.knownStockFirmware": "Known Stock Firmware",
  "fw.yowCandidate": "YOW Candidate",
  "fw.awaitingHardwareTest": "Awaiting Hardware Test",
  "fw.knownYowRelease": "Known YOW Release",
  "fw.thisImageDoesNotMatchA":
    "This image does not match a known YOW release or stock firmware in this bridge. Its container checks passed, but its application has not been verified and could leave the scale unable to boot. Only continue if you trust this image and can recover the scale.",
  "fw.serverContactConfirmed": "Server Contact Confirmed",
  "fw.authenticatedWiFiSessionReceived": "Authenticated Wi-Fi Session Received",
  "fw.invitationCopied": "Invitation Copied",
  "fw.selectAndCopyTheInvitation": "Select And Copy The Invitation",
  "fw.noScaleFoundCheckSetupMode":
    "No Scale Found. Check Setup Mode And Terminal Bluetooth Permission.",
  "fw.scaleDisconnected": "Scale Disconnected",
  "fw.setupCompletedTheScaleMayNow":
    "Setup Completed. The Scale May Now Disconnect And Sync Over Wi-Fi.",
  "fw.connectAndIdentifyAnUnrecognisedScale":
    "Connect and identify an unrecognised scale first",
  "fw.thisModelRequiresASeparateClient2":
    "This model requires a separate client-certificate firmware lookup",
  "fw.theScaleDidNotProvideThe2":
    "The scale did not provide the secret required for a firmware lookup",
  "fw.enterTheModelCodePrintedOn":
    "Enter the model code printed on the scale, such as WBS08",
  "fw.enterAFirmwareVersionBetween0":
    "Enter a firmware version between 0 and 65535",
  "fw.enterAValidManufacturerIdOr":
    "Enter a valid manufacturer ID or leave it at 0",
  "fw.checkingWithingsFirmwareOffer": "Checking Withings Firmware Offer…",
  "fw.noUpdateOfferedForTheseRequest":
    "No update offered for these request values",
  "fw.firmwareOfferFound": "Firmware Offer Found",
  "fw.noFirmwareOfferForTheseValues": "No Firmware Offer For These Values",
  "fw.githubIssueDetailsCopied": "GitHub Issue Details Copied",
  "fw.couldNotCopyDetailsUseThe":
    "Could Not Copy Details. Use The Displayed URL And SHA-1.",
  "fw.readingDeviceSettingsAndImportingScale":
    "Reading Device Settings And Importing Scale…",
  "fw.readingDeviceSettingsAndImportingFrom":
    "Reading Device Settings And Importing From Withings…",
  "fw.deviceSavedOnServer": "Device Saved On Server",
  "fw.privateDeviceExportDownloaded": "Private Device Export Downloaded",
  "fw.firmwareGeneratedAndVerified": "Firmware Generated And Verified",
  "fw.firmwareExceedsThe2MibLimit": "Firmware exceeds the 2 MiB limit",
  "fw.sendingImageToLocalBridge": "Sending Image To Local Bridge",
  "fw.unknownFirmwareSelected": "Unknown Firmware Selected",
  "fw.reviewTheWarningBeforeInstalling": "Review The Warning Before Installing",
  "fw.manualImageValidated": "Manual Image Validated",
  "fw.selectTheFirmwareAgainBeforeConfirming":
    "Select the firmware again before confirming",
  "fw.transferCompleteReconnectToConfirmThe":
    "Transfer Complete. Reconnect To Confirm The Running Firmware.",
  "fw.updateOutcomeUnconfirmed": "Update Outcome Unconfirmed",
  "fw.firmwareDownloaded": "Firmware Downloaded",
  "fw.installUnknownFirmware": "Install Unknown Firmware?",
  "fw.installFirmware": "Install Firmware?",
  "fw.typePhrase": "Type {phrase}",
  "fw.serverError": "Server: {error}",
  "fw.readTimedOut": "Read Timed Out",
  "fw.customServerReadNotSupported": "Custom Server Read Not Supported",
  "fw.notConfigured": "Not Configured",
  "fw.customServerNotConfigured": "Custom Server Not Configured",
  "fw.serverSettingsRead": "Server Settings Read",
  "fw.wiFiError": "Wi-Fi: {error}",
  "fw.wiFiReadFailed": "Wi-Fi Read Failed",
  "fw.wiFiReadNotSupported": "Wi-Fi Read Not Supported",
  "fw.aNetworkIsStoredThePassword":
    "A network is stored. The password is not exposed; enter it to save or reconnect.",
  "fw.enterTheNetworkNameAndPassword":
    "Enter the network name and password to configure Wi-Fi.",
  "fw.storedSsidRead": "Stored SSID Read",
  "fw.connectionNotTested": "Connection Not Tested",
  "fw.wiFiNotConfigured": "Wi-Fi Not Configured",
  "fw.wiFiSettingsRead": "Wi-Fi Settings Read",
  "fw.useThisComputerSLanAddress":
    "Use This Computer’s LAN Address For The Scale; localhost Would Point Back To The Scale.",
  "fw.storedServerServer": "Stored Server: {server}",
  "fw.networkChangedEnterItsWiFi":
    "Network changed. Enter its Wi-Fi password before saving.",
  "fw.enterTheWiFiPasswordBefore":
    "Enter the Wi-Fi password before saving this network.",
  "fw.thePasswordIsNotReadBack":
    "The password is not read back, so saving it has not been verified.",
  "fw.wiFiConnected": "Wi-Fi Connected",
  "fw.storedSsidMatches": "Stored SSID Matches",
  "fw.storedSsidNotConfirmed": "Stored SSID Not Confirmed",
  "fw.wiFiConnectionFailed": "Wi-Fi Connection Failed",
  "fw.checkCredentialsAnd24Ghz": "Check Credentials And 2.4 GHz WPA2 Network",
  "fw.wiFiConnectionFailedCheckThe":
    "Wi-Fi Connection Failed. Check The Network Name And Password.",
  "fw.theScaleJoinedWiFiAnd":
    "The scale joined Wi-Fi and its stored SSID matches. Whether the password was saved is unverified.",
  "fw.theScaleJoinedWiFiBut":
    "The scale joined Wi-Fi, but its stored SSID could not be confirmed. Check the server hostname and connectivity before retrying.",
  "fw.scaleClockSet": "Scale Clock Set",
  "fw.timeZoneSavedForFutureSyncs": "Time Zone Saved For Future Syncs",
  "fw.stageStarting": "starting",
  "fw.stageAccepted": "accepted",
  "fw.stageTransferring": "transferring",
  "fw.stageTransferComplete": "transfer complete",
  "fw.settingsReadyNext": "Device settings are ready. {next}",
  "fw.settingsRetryNext": "Settings import needs a retry. {next}",
  "fw.chooseNewUsers": "Choose new users to import.",
  "fw.allKnownImported": "All known users are already imported.",
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
  "common.continue": "Weiter",
  "common.delete": "Löschen",
  "common.edit": "Bearbeiten",
  "common.later": "Später",
  "setup.welcome": "Willkommen bei YourOwnWeigh",
  "setup.tokenIntro":
    "Gib das Bootstrap-Token ein, das der Setup-Befehl angezeigt hat.",
  "setup.token": "Bootstrap-Token",
  "setup.passwordTitle": "Passwort festlegen",
  "setup.passwordIntro":
    "Schützt dein Dashboard und die Sync-API. Passwörter brauchen mindestens acht Zeichen.",
  "auth.adminPassword": "Admin-Passwort",
  "setup.confirmAdmin": "Admin-Passwort bestätigen",
  "sync.alternativePassword": "Eigenes Passwort für die Sync-API festlegen",
  "setup.syncPassword": "Sync-API-Passwort",
  "setup.syncConfirm": "Sync-API-Passwort bestätigen",
  "setup.create": "Haushalt anlegen",
  "auth.signIn": "Anmelden",
  "health.notAcknowledged": "Nicht bestätigt",
  "health.acknowledged": "Bestätigt",
  "readings.user": "Person",
  "readings.healthSync": "Health-Sync",
  "readings.actions": "Aktionen",
  "readings.unassigned": "Nicht zugeordnet",
  "readings.assignTo": "Zuordnen zu",
  "readings.chooseUser": "Person wählen",
  "readings.assign": "Zuordnen",
  "readings.confirmDelete":
    "Diese nicht zugeordnete Messung endgültig löschen?",
  "userReadings.back": "← Dashboard",
  "userReadings.title": "Messungen von {name}",
  "userReadings.attribution": "Zuordnung",
  "userReadings.none": "Für diese Person gibt es noch keine Messungen.",
  "attribution.device": "Waage",
  "attribution.ambiguous": "mehrdeutig",
  "attribution.unassigned": "nicht zugeordnet",
  "attribution.manual": "manuell",
  "users.name": "Name",
  "users.shortName": "Kürzel",
  "users.heightCm": "Größe (cm)",
  "users.height": "Größe",
  "users.birthDate": "Geburtsdatum",
  "users.approxAge": "Ungefähres Alter (falls Geburtsdatum unbekannt)",
  "users.ageDob": "Alter / Geburtsdatum",
  "users.sex": "Geschlecht",
  "users.male": "Männlich",
  "users.female": "Weiblich",
  "users.recognitionWeight": "Erkennungsgewicht (kg)",
  "users.recognitionHint":
    "Wird aus der letzten zugeordneten Messung übernommen und beim nächsten WLAN-Sync an die Waage gesendet.",
  "users.importWithings": "Aus Withings importieren",
  "users.add": "Person hinzufügen",
  "users.importFrom": "Personen von {scale} importieren",
  "users.settingsReady": "Die Geräteeinstellungen sind bereit.",
  "users.settingsIncomplete":
    "Der Import der Geräteeinstellungen ist unvollständig; versuche es unter Waagen mit „Geräteimport abschließen“ erneut.",
  "users.retained": "Vorhandene Personen bleiben erhalten.",
  "users.allPresent": "Alle Personen sind bereits in diesem Haushalt.",
  "users.importSelected": "Ausgewählte Personen importieren",
  "users.status": "Status",
  "users.active": "Aktiv",
  "users.retired": "Inaktiv",
  "users.importIntro":
    "Liest die vorhandenen Personen und Einstellungen der gewählten Waage über geprüftes HTTPS. Neue Personen werden zur Auswahl angezeigt; vorhandene lokale Personen bleiben erhalten.",
  "users.chooseScale": "Waage wählen",
  "users.fetch": "Von Withings abrufen",
  "users.importUnavailable":
    "Der Withings-Import ist auf diesem Server nicht verfügbar.",
  "users.save": "Person speichern",
  "users.edit": "{name} bearbeiten",
  "users.retire": "Person deaktivieren",
  "users.delete": "Person löschen",
  "users.confirmDelete":
    "Diese Person lokal löschen? Ihre Messungen sind danach keiner Person mehr zugeordnet.",
  "setup.pageTitle": "Ersteinrichtung",
  "bridge.notConnected": "Python-Bridge nicht verbunden",
  "bridge.disconnectHint":
    "Trennt die Verbindung zu diesem Server. Eine laufende Firmware-Übertragung läuft lokal weiter.",
  "bridge.disconnect": "Bridge trennen",
  "bridge.connectTitle": "Python-Bridge verbinden",
  "bridge.connectIntro":
    "Starte die Bridge auf deinem Mac oder Linux-Rechner und lass sie laufen, während du eine Waage einrichtest.",
  "bridge.stepInstall": "Installieren: ",
  "bridge.stepRunBefore": "Starte ",
  "bridge.stepRunAfter": " im Terminal.",
  "bridge.stepInvite": "Erzeuge eine Einladung und füge sie im Terminal ein.",
  "bridge.newInvitation": "Verbindungseinladung erzeugen",
  "bridge.copyInvitation": "Einladung kopieren",
  "bridge.invitation": "Verbindungseinladung",
  "bridge.invitationHint":
    "Einladungen gelten zehn Minuten. Erlaube dem Terminal den Bluetooth-Zugriff, wenn macOS danach fragt.",
  "bridge.connect": "Verbinden",
  "bridge.disconnected": "Getrennt",
  "bridge.setupMode":
    "Versetze deine Waage mit ihrer Hardware-Taste in den Einrichtungsmodus.",
  "bridge.scanBleHint":
    "Findet Body, Body+, Body Cardio und Body Smart über Bluetooth Low Energy.",
  "bridge.scanBle": "BLE suchen",
  "bridge.scanClassicHint": "Findet WS-30, WS-50 und Body (WBS06 v551) über Bluetooth Classic.",
  "bridge.scanClassic": "Classic suchen",
  "bridge.identifyTitle": "Hilf, diese Waage zu erkennen",
  "bridge.identifyIntro":
    "Diese Waage hat auf die Identitätsabfrage geantwortet, ihr Modell wird für Einrichtung und Updates aber noch nicht unterstützt. Du kannst Withings fragen, welche Firmware angeboten wird, ohne etwas zu installieren. MAC und Secret des Geräts werden für diese Anfrage verwendet und sind in den kopierten Details nicht enthalten.",
  "bridge.modelCode": "Modellcode vom Typenschild",
  "bridge.reportVersion": "Zu meldende Firmware-Version",
  "bridge.manufacturerId": "Hersteller-ID (falls bekannt)",
  "bridge.reportHint":
    "Meldest du eine Version unter der erkannten, zeigt das oft das aktuelle Original-Image. Kein Angebot heißt nicht, dass es keine Firmware gibt.",
  "bridge.checkOffer": "Firmware-Angebot von Withings prüfen",
  "bridge.offerUrl": "Firmware-URL",
  "bridge.offerHint":
    "Metadaten laut Withings. Das Image wurde weder heruntergeladen noch geprüft.",
  "bridge.copyIssue": "Details für GitHub-Issue kopieren",
  "bridge.completeHint":
    "Beendet die Einrichtung, ohne WLAN, Hostnamen oder andere Einstellungen zu ändern.",
  "bridge.complete": "Einrichtung abschließen",
  "bridge.disconnectScale": "Waage trennen",
  "bridge.probe": "Verbindungsprüfung wiederholen",
  "bridge.revealSecret": "Secret anzeigen",
  "bridge.importDevice": "Gerät importieren",
  "bridge.exportDevice": "Geräte-Export herunterladen",
  "bridge.firmware": "Firmware",
  "bridge.firmwareIntro":
    "Lädt die Original-Firmware und erzeugt daraus die YourOwnWeigh-Firmware. Die Dateien bleiben auf dem Rechner, auf dem die Bridge läuft.",
  "bridge.generateWbs06": "Firmware für WBS06 erzeugen",
  "bridge.selectManually": "Manuell auswählen",
  "bridge.install": "Update an Gerät senden",
  "bridge.downloadFirmware": "Firmware herunterladen",
  "bridge.progress": "Firmware-Fortschritt",
  "bridge.configure": "Konfigurieren",
  "bridge.readConfig": "Von der Waage lesen",
  "bridge.server": "Server",
  "bridge.serverHost": "Server-Hostname",
  "bridge.useThisHost": "Hostnamen dieses Servers verwenden",
  "bridge.transport": "Transport",
  "bridge.setServer": "Server auf der Waage speichern",
  "bridge.wifi": "WLAN",
  "bridge.wifiSsid": "WLAN-Name (SSID)",
  "bridge.wifiPassword": "WLAN-Passwort",
  "bridge.wifiPasswordHint":
    "Gib das Passwort ein, um dieses Netzwerk zu speichern oder neu zu verbinden.",
  "bridge.connectWifi": "WLAN speichern und verbinden",
  "common.timeZone": "Zeitzone",
  "bridge.setTime": "Zeitzone speichern",
  "bridge.timeHint":
    "Bei einer importierten Waage wird eine geänderte Zeitzone auch bei künftigen WLAN-Syncs übertragen.",
  "common.notifications": "Benachrichtigungen",
  "bridge.flashTitle": "Firmware installieren?",
  "bridge.flashIntro":
    "Das ersetzt einen externen Firmware-Slot. Lass die Waage eingeschaltet und die Python-Bridge laufen, bis die Übertragung fertig ist. Bewahre die Sicherung der Original-Firmware und die Anleitung zur Wiederherstellung auf.",
  "bridge.flashPrompt": "FLASH eingeben",
  "bridge.confirmFlash": "Update bestätigen",
  "common.cancel": "Abbrechen",
  "bridge.enrollTitle": "Gerät in den Server importieren?",
  "bridge.enrollIntro":
    "Speichert diese Waage und fragt bei Withings nach vorhandenen Personen und Einstellungen. Du wählst aus, welche neuen Personen importiert werden.",
  "bridge.deviceLabel": "Name der Waage",
  "bridge.rosterTitle": "Personen importieren",
  "bridge.scaleTimeZone": "Zeitzone der Waage",
  "scales.goff": "UTC-Versatz (Sekunden)",
  "scales.dst": "Nächste Zeitumstellung (Unix-Zeit)",
  "scales.ngoff": "Nächster UTC-Versatz (Sekunden)",
  "scales.featureMask": "Feature-Maske",
  "scales.betaWs": "Beta-Dienste (0 oder 1)",
  "scales.tempCode": "Code der Temperatureinheit",
  "scales.weightCode": "Code der Gewichtseinheit",
  "scales.editSettings": "Einstellungen bearbeiten",
  "scales.usersOnScale": "Personen auf dieser Waage",
  "scales.usersOnScaleIntro":
    "Wähle die lokalen Personen, die bei jedem Sync übertragen werden. Das ersetzt die aktuelle Personenliste der Waage; der Withings-Import ist für dieses Modell nicht verfügbar.",
  "scales.addUserFirst": "Lege zuerst {link} an.",
  "scales.addUserLink": "eine Person",
  "scales.advanced": "Erweitert",
  "scales.lastSync": "Letzter Sync",
  "scales.notYetSeen": "Noch nicht gesehen",
  "scales.advancedHint":
    "Interne Protokolleinstellungen. Die gewählte Zeitzone liefert die Zeitversätze automatisch.",
  "scales.classicRetains":
    "Dieses Modell behält seine internen Einstellungen und die Personen auf der Waage.",
  "scales.saveSettings": "Einstellungen speichern",
  "scales.finishImport": "Geräteimport abschließen",
  "scales.importUsers": "Personen aus Withings importieren",
  "scales.firmwareSeenWifi":
    "Zuletzt bestätigt am {time} per WLAN-Sync. Das ist die zuletzt beobachtete laufende Version.",
  "scales.firmwareSeenBle":
    "Zuletzt bestätigt am {time} per Bluetooth. Das ist die zuletzt beobachtete laufende Version.",
  "scales.firmwareUnknown":
    "Noch keine Firmware-Version beobachtet. Verbinde und prüfe die Waage, importiere ihren Geräte-Export oder lass sie per WLAN synchronisieren.",
  "scales.firmwareConfirmation": "Firmware-Bestätigung",
  "scales.notYetConfirmed": "Noch nicht bestätigt",
  "scales.ready": "Bereit",
  "scales.chooseUsers": "Personen wählen",
  "scales.importIncomplete": "Import unvollständig",
  "scales.model": "Modell",
  "scales.secret": "Secret",
  "scales.clickToReveal": "(zum Anzeigen klicken)",
  "scales.none": "Noch keine Waagen.",
  "scales.connectFirst": "Waage verbinden",
  "scales.importFile": "Gerätedatei importieren",
  "scales.nameOptional": "Name (optional)",
  "scales.deviceExport": "Geräte-Export",
  "sync.appleHealth": "Apple Health",
  "sync.shortcutIntro":
    "Lade den signierten Kurzbefehl herunter und fülle seine ersten drei Text-Aktionen aus. Du kannst ihn auf dem Mac installieren und einrichten; iCloud überträgt ihn in die Kurzbefehle-App auf dem iPhone. Führe ihn auf dem iPhone aus, um den Health-Zugriff zu erlauben.",
  "sync.download": "YourOwnWeigh Sync herunterladen",
  "sync.serverUrl": "Server-URL",
  "sync.userId": "Personen-ID oder Kürzel aus drei Buchstaben",
  "sync.addUserFirst": "Lege zuerst eine Person an.",
  "sync.password": "Passwort",
  "sync.passwordHint":
    "Dein Sync-API-Passwort (das Admin-Passwort, sofern du kein eigenes festgelegt hast).",
  "sync.automationHint":
    "Für einen täglichen Sync legst du in der Kurzbefehle-App eine persönliche Automation an: Tageszeit → 09:00 → Täglich → Sofort ausführen → Kurzbefehl ausführen → YourOwnWeigh Sync. Du kannst den Kurzbefehl auch jederzeit von Hand starten.",
  "sync.http": "Per HTTP abrufen",
  "sync.httpIntro":
    "Verwende eine numerische Personen-ID oder ein eindeutiges Kürzel aus drei Buchstaben. Anfragen liefern JSON und markieren Messungen nicht als in Apple Health importiert.",
  "sync.curlHint":
    "curl fragt nach dem Passwort. Nutze HTTPS für entfernte Server. Mit den Haushalts-Zugangsdaten lassen sich alle Personen lesen; die gewählte ID bestimmt nur diese Anfrage, nicht die Zugriffsrechte.",
  "sync.readingsHint":
    "<code>/readings</code> liefert alle Messgruppen, benannte Messwerte und Rohwerte. Zum Blättern folgst du <code>next_cursor</code> über den Parameter <code>cursor</code>. <code>/weights</code> bleibt für Clients verfügbar, die nur das Gewicht brauchen.",
  "sync.healthSyncHint":
    "Der Apple-Kurzbefehl nutzt die eigenen Endpunkte <code>health-sync/next</code> und <code>health-sync/ack</code>, damit er eine Messung erst bestätigt, nachdem sie in Health geschrieben wurde.",
  "settings.backup": "Sicherung und Wiederherstellung",
  "settings.backupIntro":
    "Sichere deinen Haushalt oder stelle einen gespeicherten Export wieder her.",
  "settings.export": "Datenbank exportieren",
  "settings.import": "Datenbank importieren",
  "settings.exportHint":
    "Exporte enthalten Geräte-Secrets und Passwort-Hashes. Bewahre sie privat auf.",
  "common.close": "Schließen",
  "settings.importIntro":
    "Wähle einen gespeicherten Datenbank-Export. Du kannst ihn prüfen, bevor fehlende Daten ergänzt oder der Haushalt ersetzt wird.",
  "settings.backupFile": "Sicherungsdatei",
  "settings.importHint":
    "Deine aktuellen Passwörter bleiben erhalten, außer du stellst die Zugangseinstellungen ausdrücklich wieder her.",
  "settings.reviewImport": "Import prüfen",
  "settings.currentAdmin": "Aktuelles Admin-Passwort",
  "settings.newPassword": "Neues Passwort",
  "settings.confirmPassword": "Passwort bestätigen",
  "settings.changeAdmin": "Admin-Passwort ändern",
  "settings.newSync": "Neues Sync-Passwort",
  "settings.confirmSync": "Sync-Passwort bestätigen",
  "settings.saveSync": "Sync-Passwort speichern",
  "settings.syncSeparate": "Die Sync-API nutzt ein eigenes Passwort.",
  "settings.syncShared":
    "Die Sync-API nutzt dieses Passwort ebenfalls. Passe nach einer Änderung deinen Kurzbefehl an.",
  "bridge.targetModel": "Zielmodell",
  "battery.label": "Akku",
  "battery.notReported": "Noch nicht gemeldet",
  "battery.reported": "Gemeldet am {time}",
  "msg.aScaleCanHaveAtMost": "Eine Waage kann höchstens acht Personen haben",
  "msg.adminPasswordChangedOtherSessionsWere":
    "Admin-Passwort geändert; andere Sitzungen wurden abgemeldet",
  "msg.administrationPasswordSet": "Admin-Passwort festgelegt",
  "msg.captureBelongsToADifferentScale":
    "Der Mitschnitt gehört zu einer anderen Waage",
  "msg.captureContainsAnInvalidUser":
    "Der Mitschnitt enthält eine ungültige Person",
  "msg.captureExceeds128Kb": "Der Mitschnitt ist größer als 128 KB",
  "msg.captureHasNoTimeOrDevice":
    "Der Mitschnitt enthält keine Zeit- oder Geräteeinstellungen",
  "msg.captureHasNoValidRoster":
    "Der Mitschnitt enthält keine gültige Personenliste",
  "msg.captureIsMissingValidScreenIds":
    "Im Mitschnitt fehlen gültige Bildschirm-IDs (cs) für eine Person",
  "msg.captureLacksDisplayResponses": "Im Mitschnitt fehlen Anzeige-Antworten",
  "msg.captureRemovesExistingRosterUsersReview":
    "Der Mitschnitt entfernt vorhandene Personen der Liste; bitte einzeln prüfen",
  "msg.captureStagedReviewUsersBeforeImport":
    "Mitschnitt vorgemerkt. Prüfe die Personen vor dem Import.",
  "msg.capturedFeatureMaskDiffersFromAuthenticated":
    "Die mitgeschnittene Feature-Maske weicht von der authentifizierten Anfrage der Waage ab",
  "msg.capturedFeatureMaskDiffersFromScale":
    "Die mitgeschnittene Feature-Maske weicht von der Waage ab",
  "msg.capturedRoutingSelectorPointsToA":
    "Der mitgeschnittene Routing-Selektor zeigt auf einen Withings-Beta-Host",
  "msg.capturedScaleSettingsImported":
    "Mitgeschnittene Waageneinstellungen importiert",
  "msg.capturedSettingsDoNotMatchThis":
    "Die mitgeschnittenen Einstellungen passen nicht zur gemeldeten Feature-Maske dieser Waage",
  "msg.chooseABackupFileOfAt":
    "Wähle eine Sicherungsdatei mit höchstens 10 MiB",
  "msg.chooseACaptureJsonFile": "Wähle eine Mitschnitt-JSON-Datei",
  "msg.chooseADeviceEnrollmentJsonFile": "Wähle eine Geräte-JSON-Datei",
  "msg.chooseAKnownScale": "Wähle eine bekannte Waage",
  "msg.chooseATimeZone": "Wähle eine Zeitzone",
  "msg.chooseActiveHouseholdUsers": "Wähle aktive Personen des Haushalts",
  "msg.chooseOneToEightUsersFor":
    "Wähle eine bis acht Personen für diese Waage",
  "msg.chooseUsersFromThisImportedProfile":
    "Wähle Personen aus diesem importierten Profil",
  "msg.confirmTheReviewedImportFirst": "Bestätige zuerst den geprüften Import",
  "msg.currentAdminPasswordIsIncorrect":
    "Das aktuelle Admin-Passwort ist falsch",
  "msg.deviceExportIsOlderThanThe":
    "Der Geräte-Export ist älter als der gespeicherte",
  "msg.deviceRecordMustBeAtMost":
    "Der Geräte-Datensatz darf höchstens 4 KB groß sein",
  "msg.deviceSavedTimeZoneChangesApply":
    "Gerät gespeichert. Eine geänderte Zeitzone gilt ab dem nächsten WLAN-Sync.",
  "msg.deviceSettingsImportedChooseAnyNew":
    "Geräteeinstellungen importiert. Wähle die neuen Personen aus, die du hinzufügen willst.",
  "msg.directWithingsCaptureIsUnavailableIn":
    "Direkter Withings-Abruf ist in dieser Installation nicht verfügbar",
  "msg.duplicateScaleSelection": "Waage doppelt ausgewählt",
  "msg.enrolledScaleHasADifferentSecret":
    "Die registrierte Waage hat ein anderes Secret",
  "msg.fixtureExceeds16Kb": "Die Fixture ist größer als 16 KB",
  "msg.fixtureMustHaveStatus0And":
    "Die Fixture braucht status 0 und einen body",
  "msg.importedProfileChangedFetchItAgain":
    "Das importierte Profil hat sich geändert; rufe es erneut ab",
  "msg.invalidIanaTimeZone": "Ungültige IANA-Zeitzone",
  "msg.invalidMacAddress": "Ungültige MAC-Adresse",
  "msg.invalidWiFiSsid": "Ungültige WLAN-SSID",
  "msg.invalidBirthDate": "Ungültiges Geburtsdatum",
  "msg.invalidBootstrapToken": "Ungültiges Bootstrap-Token",
  "msg.invalidDeviceCaptureTime": "Ungültige Mitschnittzeit des Geräts",
  "msg.invalidDeviceSecret": "Ungültiges Geräte-Secret",
  "msg.invalidDisplayLanguage": "Ungültige Anzeigesprache",
  "msg.invalidDisplayUnit": "Ungültige Anzeigeeinheit",
  "msg.invalidFirmwareVersion": "Ungültige Firmware-Version",
  "msg.invalidInternalDeviceSettings": "Ungültige interne Geräteeinstellungen",
  "msg.invalidOwnerTarget": "Ungültiges Owner-Ziel",
  "msg.invalidPassword": "Ungültiges Passwort",
  "msg.invalidProfileFields": "Ungültige Profilfelder",
  "msg.invalidRosterBaseline": "Ungültige Ausgangsliste der Personen",
  "msg.invalidRosterRecord": "Ungültiger Eintrag in der Personenliste",
  "msg.invalidScaleName": "Ungültiger Waagenname",
  "msg.invalidScaleSettings": "Ungültige Waageneinstellungen",
  "msg.invalidSummaryDate": "Ungültiges Zusammenfassungsdatum",
  "msg.invalidWeatherSeries": "Ungültige Wetterreihe",
  "msg.nameAndTimeZoneSavedOther":
    "Name und Zeitzone gespeichert; andere Einstellungen auf der Waage bleiben erhalten",
  "msg.newPasswordsDoNotMatch": "Die neuen Passwörter stimmen nicht überein",
  "msg.noReviewedCaptureForThisScale":
    "Kein geprüfter Mitschnitt für diese Waage",
  "msg.noUserIdsRemain": "Keine freien Personen-IDs mehr",
  "msg.onScaleRosterDeliveryIsNot":
    "Die Übertragung der Personenliste ist für dieses Modell nicht umgesetzt",
  "msg.ownerTransportRequiresAHost": "Der Owner-Transport braucht einen Host",
  "msg.passwordMustContain8To1024":
    "Das Passwort muss 8 bis 1024 Zeichen haben",
  "msg.passwordsDoNotMatch": "Die Passwörter stimmen nicht überein",
  "msg.probeIdentityDoesNotMatchThe":
    "Die geprüfte Identität passt nicht zur registrierten Waage",
  "msg.readingAssigned": "Messung zugeordnet",
  "msg.readingCandidateListIsMalformed":
    "Die Kandidatenliste der Messung ist fehlerhaft",
  "msg.readingIsMissingOrAlreadyAssigned":
    "Die Messung fehlt oder ist schon zugeordnet",
  "msg.readingIsMissingOrAssigned": "Die Messung fehlt oder ist zugeordnet",
  "msg.readingsApiPasswordSet": "Passwort für die Messwert-API festgelegt",
  "msg.reviewedCaptureHasChanged": "Der geprüfte Mitschnitt hat sich geändert",
  "msg.rosterBaselineOrUsersMissing": "Ausgangsliste oder Personen fehlen",
  "msg.rosterBaselineSavedOneShotDelivery":
    "Ausgangsliste gespeichert; die einmalige Übertragung bleibt aus",
  "msg.savedRosterIsMalformed": "Die gespeicherte Personenliste ist fehlerhaft",
  "msg.savedScaleRosterIsMalformed":
    "Die gespeicherte Personenliste der Waage ist fehlerhaft",
  "msg.scaleAddedImportAReviewedCapture":
    "Waage hinzugefügt. Importiere einen geprüften Mitschnitt, um ihre Einstellungen und Personen vorzumerken.",
  "msg.scaleAlreadyHasActiveSettingsOr":
    "Die Waage hat bereits aktive Einstellungen oder Fixtures",
  "msg.scaleConfigurationSaved": "Waagenkonfiguration gespeichert",
  "msg.scaleImportedWithSettingsChooseAny":
    "Waage mit Einstellungen importiert. Wähle die neuen Personen aus, die du hinzufügen willst.",
  "msg.scaleLabelIsTooLong": "Der Name der Waage ist zu lang",
  "msg.scaleOrWithingsImportUnavailable":
    "Waage oder Withings-Import nicht verfügbar",
  "msg.scaleSavedChooseItsUsersIn":
    "Waage gespeichert. Wähle vor dem ersten Sync unter „Einstellungen bearbeiten“ ihre Personen.",
  "msg.scaleSavedWithingsImportIsIncomplete":
    "Waage gespeichert. Der Withings-Import ist unvollständig; versuche es mit „Geräteimport abschließen“ erneut.",
  "msg.scaleSecretReplacedSessionsInvalidated":
    "Secret der Waage ersetzt; Sitzungen wurden ungültig",
  "msg.scaleSettingsAreAlreadyActiveReview":
    "Die Waageneinstellungen sind schon aktiv; prüfe Änderungen in der Gerätekonfiguration",
  "msg.secretMustContain1To256": "Das Secret muss 1 bis 256 Zeichen haben",
  "msg.selectedUsersImportedExistingUsersRetained":
    "Ausgewählte Personen importiert; vorhandene Personen bleiben erhalten",
  "msg.separateSyncApiPasswordSaved": "Eigenes Sync-API-Passwort gespeichert",
  "msg.settingsSavedForTheNextWi":
    "Einstellungen für die nächste WLAN-Verbindung gespeichert",
  "msg.signedIn": "Angemeldet",
  "msg.signedOut": "Abgemeldet",
  "msg.summaryBodyMustBeAnArray":
    "Der Zusammenfassungs-Body muss ein Array sein",
  "msg.supplyALabelAndExactScale":
    "Gib einen Namen und das genaue Secret der Waage an",
  "msg.syncApiNowUsesTheAdmin": "Die Sync-API nutzt jetzt das Admin-Passwort",
  "msg.syncPasswordsDoNotMatch": "Die Sync-Passwörter stimmen nicht überein",
  "msg.tooManyAttemptsTryAgainIn":
    "Zu viele Versuche; versuche es in zehn Minuten erneut",
  "msg.unassignedReadingDeleted": "Nicht zugeordnete Messung gelöscht",
  "msg.unexpectedCaptureFormat": "Unerwartetes Mitschnittformat",
  "msg.unknownFixtureEndpoint": "Unbekannter Fixture-Endpunkt",
  "msg.unknownImportedUser": "Unbekannte importierte Person",
  "msg.unknownScale": "Unbekannte Waage",
  "msg.unknownUser": "Unbekannte Person",
  "msg.unsupportedDeviceEnrollmentRecord":
    "Nicht unterstützter Geräte-Datensatz",
  "msg.userAbsentFromRosterBaseline": "Person fehlt in der Ausgangsliste",
  "msg.userDeletedLocallyTheirReadingsAre":
    "Person lokal gelöscht; ihre Messungen sind jetzt keiner Person zugeordnet",
  "msg.userRetiredHistoricalReadingsRemain":
    "Person deaktiviert; bisherige Messungen bleiben erhalten",
  "msg.userUpdatedRosterEditsWillBe":
    "Person aktualisiert; Änderungen an der Personenliste gehen bei der nächsten Verbindung an unterstützte Waagen",
  "msg.withingsImportIsUnavailable": "Der Withings-Import ist nicht verfügbar",
  "msg.withingsImportUnavailable": "Withings-Import nicht verfügbar",
  "msg.displaySettingsSaved": "Anzeigeeinstellungen gespeichert",
  "msg.requestFailed": "Anfrage fehlgeschlagen",
  "msg.endpointFixtureSaved": "Fixture {endpoint} gespeichert",
  "msg.modelUsesLocalUsersChooseThem":
    "{model} nutzt lokale Personen; wähle sie unter Waagen → Einstellungen bearbeiten",
  "msg.bleIdentityIsOutsideTheReviewed":
    "Die BLE-Identität liegt außerhalb des geprüften Profils für {model}",
  "msg.classicIdentityIsOutsideTheReviewed":
    "Die Classic-Identität liegt außerhalb des geprüften Profils für {model}",
  "msg.invalidDeviceKey": "Ungültiges Gerätefeld {key}",
  "msg.invalidKey": "Ungültiger Wert: {key}",
  "msg.userNameAddedAsStableScale":
    "Person {name} mit fester Waagen-ID {id} angelegt",
  "backup.reviewTitle": "Import der Sicherung prüfen",
  "backup.merge": "Fehlende Daten ergänzen (vorhandene Änderungen behalten)",
  "backup.replace": "Haushaltsdaten ersetzen",
  "backup.replaceHint":
    "Beim Ersetzen werden die aktuellen Personen, Messungen und Geräte entfernt.",
  "backup.exportFirst": "Vorher aktuelle Daten exportieren",
  "backup.restoreAccess":
    "Zugangseinstellungen wiederherstellen (Passwörter der Sicherung verwenden und abmelden)",
  "backup.confirmed": "Ich habe diesen Import geprüft",
  "backup.importButton": "Sicherung importieren",
  "backup.failedTitle": "Import nicht abgeschlossen",
  "backup.backToSettings": "Zurück zu den Einstellungen",
  "backup.section.users": "Personen",
  "backup.section.scales": "Waagen",
  "backup.section.scale_users": "Personen auf Waagen",
  "backup.section.readings": "Messungen",
  "backup.section.health_sync_receipts": "Health-Sync-Bestätigungen",
  "backup.section.reviewed_captures": "geprüfte Mitschnitte",
  "backup.section.events": "Ereignisse",
  "backup.section.sync_audit": "Sync-Protokoll",
  "backup.section.measure_attempts": "Messversuche",
  "backup.section.measure_rejections": "abgelehnte Messungen",
  "msg.backupRestoredSignIn":
    "Sicherung wiederhergestellt. Melde dich mit dem Admin-Passwort der Sicherung an.",
  "msg.backupImportedPasswords":
    "Sicherung importiert. Die aktuellen Passwörter bleiben erhalten.",
  "msg.backupConfirmationMismatch":
    "Die Bestätigung passt nicht zu dieser Vorschau",
  "msg.backupUnknownSection":
    "Die Sicherung enthält einen unbekannten Abschnitt",
  "msg.backupTooLarge": "Die Sicherung ist größer als 10 MiB",
  "msg.backupTooManyRows": "Die Sicherung hat mehr als 25.000 Haushaltszeilen",
  "msg.backupNoAdmin":
    "Die Sicherung enthält kein Admin-Passwort zum Wiederherstellen",
  "msg.backupExpired":
    "Die Vorschau ist abgelaufen; lade die Sicherung erneut hoch",
  "msg.invalidAccessSettings": "Ungültige Zugangseinstellungen",
  "msg.invalidFirmwareObservation": "Ungültige Firmware-Beobachtung",
  "msg.invalidScaleIdentity": "Ungültige oder doppelte Waagenidentität",
  "msg.invalidPasswordHash": "Ungültiger Passwort-Hash",
  "msg.invalidDeliveryFlags": "Ungültige Übertragungs-Flags der Waage",
  "msg.invalidStoredReading": "Ungültige gespeicherte Messung",
  "msg.invalidSyncMode": "Ungültiger Modus für das Sync-API-Passwort",
  "msg.invalidUserProfile": "Ungültiges Personenprofil",
  "msg.missingReading": "Referenzierte Messung fehlt",
  "msg.missingScale": "Referenzierte Waage fehlt",
  "msg.missingUser": "Referenzierte Person fehlt",
  "msg.unknownPreference": "Unbekannte Einstellung",
  "msg.unknownRestoreMode": "Unbekannter Wiederherstellungsmodus",
  "msg.unsupportedBackup": "Nicht unterstütztes Sicherungsformat",
  "fw.dismissNotification": "Benachrichtigung schließen",
  "fw.yourLoginExpiredReloadThisPage":
    "Deine Anmeldung ist abgelaufen. Lade die Seite neu und melde dich an.",
  "fw.serverReturnedAnUnexpectedResponse":
    "Der Server hat unerwartet geantwortet",
  "fw.requestFailedStatus": "Anfrage fehlgeschlagen ({status})",
  "fw.thisModelRequiresASeparateClient":
    "Dieses Modell braucht eine eigene Firmware-Abfrage mit Client-Zertifikat",
  "fw.theScaleDidNotProvideThe":
    "Die Waage hat das für diese Abfrage nötige Secret nicht geliefert",
  "fw.connectedModel": "Verbunden: {model}",
  "fw.identificationRequired": "Identifizierung nötig",
  "fw.unrecognisedScale": "Unbekannte Waage",
  "fw.disconnected": "Getrennt",
  "fw.generateFirmwareForModel": "Firmware für {model} erzeugen",
  "fw.hostnameOrIpv4Address": "Hostname oder IPv4-Adresse",
  "fw.maximumLimitAsciiBytes": "höchstens {limit} ASCII-Bytes",
  "fw.noSchemePathOrPort": "ohne Schema, Pfad oder Port",
  "fw.enterThisComputerSLanAddress": "LAN-Adresse dieses Rechners eingeben",
  "fw.useHost": "{host} verwenden",
  "fw.model": "Modell",
  "fw.nameUnrecognisedTransport": "{name} (nicht erkannt, {transport})",
  "fw.unknown": "Unbekannt",
  "fw.notProvidedByScale": "Von der Waage nicht geliefert",
  "fw.checkingDeviceIdentity": "Geräteidentität wird geprüft…",
  "fw.identityRead": "Identität gelesen",
  "fw.thisModelIsNotYetSupported": "Dieses Modell wird noch nicht unterstützt",
  "fw.connectedAndReady": "Verbunden und bereit",
  "fw.device": "Gerät",
  "fw.address": "Adresse",
  "fw.presence": "Sichtbarkeit",
  "fw.paired": "Gekoppelt",
  "fw.notSeenThisScan": "bei dieser Suche nicht gesehen",
  "fw.connectedToComputer": "Mit dem Rechner verbunden",
  "fw.seenThisScan": "Bei dieser Suche gesehen",
  "fw.connect": "Verbinden",
  "fw.availableWhenSeenNearbyOrWhen":
    "Verfügbar, sobald sie in der Nähe gesehen wird oder die Suche endet",
  "fw.stopScanningAndConnectToThis":
    "Suche beenden und mit dieser Waage verbinden",
  "fw.connectAndIdentifyThisScale":
    "Mit dieser Waage verbinden und sie identifizieren",
  "fw.scanning": "Suche läuft",
  "fw.scanComplete": "Suche abgeschlossen",
  "fw.scanStopped": "Suche gestoppt",
  "fw.scanInterrupted": "Suche unterbrochen",
  "fw.connectTheLocalPythonBridgeFirst":
    "Verbinde zuerst die lokale Python-Bridge",
  "fw.noFinalResponseYetCheckThe":
    "Noch keine abschließende Antwort. Sieh im Bridge-Terminal nach; eine laufende Firmware-Übertragung läuft lokal weiter.",
  "fw.pythonBridgeConnectedFromIp": "Python-Bridge verbunden von: {ip}",
  "fw.demonstrationNoHardware": "DEMO – KEINE HARDWARE",
  "fw.pythonBridgeNotConnected": "Python-Bridge nicht verbunden",
  "fw.reconnectingToServer": "Verbindung zum Server wird wiederhergestellt",
  "fw.browserConnectionInterruptedAnyActiveOta":
    "Die Browser-Verbindung wurde unterbrochen. Ein laufendes OTA-Update läuft in der Python-Bridge weiter; verbinde dich neu, bevor du einen weiteren Befehl sendest.",
  "fw.firmwareUpdate": "Firmware-Update",
  "fw.reconnecting": "Verbindung wird wiederhergestellt",
  "fw.lastReportedUpdateProgress": "zuletzt gemeldeter Fortschritt",
  "fw.firmwareTransferDidNotCompleteCheck":
    "Die Firmware-Übertragung wurde nicht abgeschlossen. Sieh im Bridge-Terminal nach.",
  "fw.firmwareTransferComplete": "Firmware übertragen",
  "fw.reconnectToConfirmTheRunningVersion":
    "verbinde dich neu, um die laufende Version zu bestätigen",
  "fw.saveThisScaleThenChooseIts":
    "Speichere diese Waage und wähle danach unter Waagen → Einstellungen bearbeiten ihre lokalen Personen. Der Withings-Import ist für dieses Modell nicht verfügbar.",
  "fw.saveThisScaleAndCheckWithings":
    "Speichert diese Waage und fragt bei Withings nach vorhandenen Personen und Einstellungen. Du wählst aus, welche neuen Personen importiert werden.",
  "fw.unknownFirmware": "Unbekannte Firmware",
  "fw.knownStockFirmware": "Bekannte Original-Firmware",
  "fw.yowCandidate": "YOW-Kandidat",
  "fw.awaitingHardwareTest": "Hardwaretest steht aus",
  "fw.knownYowRelease": "Bekannte YOW-Version",
  "fw.thisImageDoesNotMatchA":
    "Dieses Image passt zu keiner bekannten YOW-Version und keiner Original-Firmware in dieser Bridge. Die Container-Prüfungen sind bestanden, die Anwendung selbst wurde aber nicht geprüft und könnte die Waage am Starten hindern. Mach nur weiter, wenn du dem Image vertraust und die Waage wiederherstellen kannst.",
  "fw.serverContactConfirmed": "Serverkontakt bestätigt",
  "fw.authenticatedWiFiSessionReceived":
    "Authentifizierte WLAN-Sitzung empfangen",
  "fw.invitationCopied": "Einladung kopiert",
  "fw.selectAndCopyTheInvitation": "Einladung markieren und kopieren",
  "fw.noScaleFoundCheckSetupMode":
    "Keine Waage gefunden. Prüfe den Einrichtungsmodus und die Bluetooth-Berechtigung des Terminals.",
  "fw.scaleDisconnected": "Waage getrennt",
  "fw.setupCompletedTheScaleMayNow":
    "Einrichtung abgeschlossen. Die Waage kann sich jetzt trennen und per WLAN synchronisieren.",
  "fw.connectAndIdentifyAnUnrecognisedScale":
    "Verbinde und identifiziere zuerst eine unbekannte Waage",
  "fw.thisModelRequiresASeparateClient2":
    "Dieses Modell braucht eine eigene Firmware-Abfrage mit Client-Zertifikat",
  "fw.theScaleDidNotProvideThe2":
    "Die Waage hat das für eine Firmware-Abfrage nötige Secret nicht geliefert",
  "fw.enterTheModelCodePrintedOn":
    "Gib den Modellcode vom Typenschild ein, zum Beispiel WBS08",
  "fw.enterAFirmwareVersionBetween0":
    "Gib eine Firmware-Version zwischen 0 und 65535 ein",
  "fw.enterAValidManufacturerIdOr":
    "Gib eine gültige Hersteller-ID ein oder lass 0 stehen",
  "fw.checkingWithingsFirmwareOffer":
    "Firmware-Angebot von Withings wird geprüft…",
  "fw.noUpdateOfferedForTheseRequest":
    "Für diese Angaben wird kein Update angeboten",
  "fw.firmwareOfferFound": "Firmware-Angebot gefunden",
  "fw.noFirmwareOfferForTheseValues": "Kein Firmware-Angebot für diese Werte",
  "fw.githubIssueDetailsCopied": "Details für GitHub-Issue kopiert",
  "fw.couldNotCopyDetailsUseThe":
    "Details konnten nicht kopiert werden. Nutze die angezeigte URL und SHA-1.",
  "fw.readingDeviceSettingsAndImportingScale":
    "Geräteeinstellungen werden gelesen und die Waage importiert…",
  "fw.readingDeviceSettingsAndImportingFrom":
    "Geräteeinstellungen werden gelesen und aus Withings importiert…",
  "fw.deviceSavedOnServer": "Gerät auf dem Server gespeichert",
  "fw.privateDeviceExportDownloaded": "Privater Geräte-Export heruntergeladen",
  "fw.firmwareGeneratedAndVerified": "Firmware erzeugt und geprüft",
  "fw.firmwareExceedsThe2MibLimit":
    "Die Firmware überschreitet die Grenze von 2 MiB",
  "fw.sendingImageToLocalBridge": "Image wird an die lokale Bridge gesendet",
  "fw.unknownFirmwareSelected": "Unbekannte Firmware ausgewählt",
  "fw.reviewTheWarningBeforeInstalling":
    "Lies vor der Installation die Warnung",
  "fw.manualImageValidated": "Manuell gewähltes Image geprüft",
  "fw.selectTheFirmwareAgainBeforeConfirming":
    "Wähle die Firmware vor dem Bestätigen erneut aus",
  "fw.transferCompleteReconnectToConfirmThe":
    "Übertragung abgeschlossen. Verbinde dich neu, um die laufende Firmware zu bestätigen.",
  "fw.updateOutcomeUnconfirmed": "Ergebnis des Updates unbestätigt",
  "fw.firmwareDownloaded": "Firmware heruntergeladen",
  "fw.installUnknownFirmware": "Unbekannte Firmware installieren?",
  "fw.installFirmware": "Firmware installieren?",
  "fw.typePhrase": "{phrase} eingeben",
  "fw.serverError": "Server: {error}",
  "fw.readTimedOut": "Zeitüberschreitung beim Lesen",
  "fw.customServerReadNotSupported":
    "Lesen des eigenen Servers nicht unterstützt",
  "fw.notConfigured": "Nicht eingerichtet",
  "fw.customServerNotConfigured": "Kein eigener Server eingerichtet",
  "fw.serverSettingsRead": "Servereinstellungen gelesen",
  "fw.wiFiError": "WLAN: {error}",
  "fw.wiFiReadFailed": "WLAN konnte nicht gelesen werden",
  "fw.wiFiReadNotSupported": "Lesen des WLANs nicht unterstützt",
  "fw.aNetworkIsStoredThePassword":
    "Ein Netzwerk ist gespeichert. Das Passwort wird nicht angezeigt; gib es ein, um zu speichern oder neu zu verbinden.",
  "fw.enterTheNetworkNameAndPassword":
    "Gib Netzwerkname und Passwort ein, um das WLAN einzurichten.",
  "fw.storedSsidRead": "Gespeicherte SSID gelesen",
  "fw.connectionNotTested": "Verbindung nicht getestet",
  "fw.wiFiNotConfigured": "WLAN nicht eingerichtet",
  "fw.wiFiSettingsRead": "WLAN-Einstellungen gelesen",
  "fw.useThisComputerSLanAddress":
    "Verwende für die Waage die LAN-Adresse dieses Rechners; localhost würde auf die Waage selbst zeigen.",
  "fw.storedServerServer": "Gespeicherter Server: {server}",
  "fw.networkChangedEnterItsWiFi":
    "Das Netzwerk hat sich geändert. Gib vor dem Speichern sein WLAN-Passwort ein.",
  "fw.enterTheWiFiPasswordBefore":
    "Gib vor dem Speichern das WLAN-Passwort ein.",
  "fw.thePasswordIsNotReadBack":
    "Das Passwort wird nicht zurückgelesen, daher ist nicht geprüft, ob es gespeichert wurde.",
  "fw.wiFiConnected": "WLAN verbunden",
  "fw.storedSsidMatches": "gespeicherte SSID stimmt",
  "fw.storedSsidNotConfirmed": "gespeicherte SSID nicht bestätigt",
  "fw.wiFiConnectionFailed": "WLAN-Verbindung fehlgeschlagen",
  "fw.checkCredentialsAnd24Ghz": "prüfe Zugangsdaten und 2,4-GHz-WPA2-Netz",
  "fw.wiFiConnectionFailedCheckThe":
    "WLAN-Verbindung fehlgeschlagen. Prüfe Netzwerkname und Passwort.",
  "fw.theScaleJoinedWiFiAnd":
    "Die Waage ist im WLAN und ihre gespeicherte SSID stimmt. Ob das Passwort gespeichert wurde, ist nicht geprüft.",
  "fw.theScaleJoinedWiFiBut":
    "Die Waage ist im WLAN, ihre gespeicherte SSID ließ sich aber nicht bestätigen. Prüfe Server-Hostname und Verbindung, bevor du es erneut versuchst.",
  "fw.scaleClockSet": "Uhr der Waage gestellt",
  "fw.timeZoneSavedForFutureSyncs": "Zeitzone für künftige Syncs gespeichert",
  "fw.stageStarting": "wird gestartet",
  "fw.stageAccepted": "angenommen",
  "fw.stageTransferring": "wird übertragen",
  "fw.stageTransferComplete": "Übertragung abgeschlossen",
  "fw.settingsReadyNext": "Die Geräteeinstellungen sind bereit. {next}",
  "fw.settingsRetryNext":
    "Der Import der Einstellungen muss wiederholt werden. {next}",
  "fw.chooseNewUsers": "Wähle die neuen Personen für den Import.",
  "fw.allKnownImported": "Alle bekannten Personen sind schon importiert.",
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
    const text = catalog[key] ?? en[key] ?? key;
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

/** Server messages (flash notices and form errors) are produced in English
 * and translated when shown, by matching the exact English catalog text of a
 * `msg.*` key. `{name}` placeholders match any text. Unknown messages are
 * shown unchanged. */
const MESSAGE_PATTERNS = MESSAGE_KEYS.filter((key) => key.startsWith("msg."))
  .map((key) => {
    const names: string[] = [];
    const source = en[key]
      .split(/(\{\w+\})/)
      .map((part) => {
        const placeholder = /^\{(\w+)\}$/.exec(part);
        if (!placeholder) return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        names.push(placeholder[1]);
        return "(.+?)";
      })
      .join("");
    return {
      key,
      names,
      pattern: new RegExp(`^${source}$`),
      size: source.length,
    };
  })
  // Exact messages first, then the most specific patterns.
  .sort((a, b) => a.names.length - b.names.length || b.size - a.size);

export function translateMessage(message: string, language: Language): string {
  if (language === "en" || !message) return message;
  const t = translator(language);
  for (const { key, names, pattern } of MESSAGE_PATTERNS) {
    const match = pattern.exec(message);
    if (match)
      return t(
        key,
        Object.fromEntries(names.map((name, i) => [name, match[i + 1]])),
      );
  }
  return message;
}

/** English → translated pairs for a browser script, most specific first.
 * The script keeps its English text and translates it where it is shown. */
export function clientTranslations(
  language: Language,
  ...prefixes: string[]
): Array<[string, string]> {
  if (language === "en") return [];
  const t = translator(language);
  const literal = (text: string) => text.replace(/\{\w+\}/g, "").length;
  return MESSAGE_KEYS.filter((key) =>
    prefixes.some((prefix) => key.startsWith(prefix)),
  )
    .map((key): [string, string] => [en[key], t(key)])
    .sort(
      (a, b) =>
        Number(a[0].includes("{")) - Number(b[0].includes("{")) ||
        literal(b[0]) - literal(a[0]),
    );
}
