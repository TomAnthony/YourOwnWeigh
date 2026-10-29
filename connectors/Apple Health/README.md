# YourOwnWeigh Sync — Apple Health

Import one selected user's weight readings into that person's Apple Health account. The server and Python setup bridge remain independent of Apple Health; other clients can use the same readings API.

## Install And Configure

**You can install and configure the Shortcut on your Mac**, then let Shortcuts' iCloud sync copy it to your iPhone. Enable iCloud Sync for Shortcuts on both devices using the same Apple Account. Alternatively, open the file directly on the iPhone.

1. Open [YourOwnWeigh Sync.shortcut](YourOwnWeigh%20Sync.shortcut) and add it to Shortcuts.
2. Edit the first three Text actions: the full server URL **including `https://`** (no trailing slash), the **Sync API password** from Settings, and a numeric user ID or unique three-letter display name. By default this is your admin password; use the separate Sync password if you set one. Never use the device secret.
3. Run it **on the iPhone** and grant permission to reach the server and write Weight samples to Health. The Health action should show Type **Weight**, a **Weight kg** variable and a **Date** variable. The Mac is useful for editing and syncing the Shortcut, not for running the Health import.
4. Check a reading's value and date in Health. Tap the Shortcut whenever you want to sync manually.

Do not share your configured copy: its password is saved in the Shortcut and syncs through your Apple Account. The supplied distributable contains placeholders only.

## Daily Sync

On the iPhone, create a personal automation for **Time of Day → 9:00 → Daily**, choose **Run Immediately** (or disable Ask Before Running on older versions), and select **YourOwnWeigh Sync**. Grant the initial permissions manually first. The downloadable Shortcut does not include a schedule. Configure and enable the automation on each phone; do not rely on a Mac automation to write iPhone Health data.

Apple documents [Shortcuts iCloud sync](https://support.apple.com/guide/shortcuts/sync-shortcuts-apdb3a4240b0/ios) and [personal automations](https://support.apple.com/guide/shortcuts/intro-to-personal-automation-apd690170742/ios).

## Import Behavior

The fixed starting date is **2026-01-01**. Each run fetches up to 100 unacknowledged readings, oldest first, writes kilograms with the reading's date, and acknowledges after the Health action succeeds. Run again for larger backlogs. No new reading means a quiet exit. Progress belongs to the selected user on the server; avoid concurrent runs for that user.

If a network failure occurs after Health saves a sample but before acknowledgment, retrying may duplicate it. Requeue readings in the web app only after reviewing the existing Health entries. There is no cross-service atomic transaction or automatic Health deduplication.

If the Shortcut reports a response error, check the full HTTPS URL, API password and user identifier. A hostname without `https://`, a login page, a proxy challenge or a non-JSON error cannot be imported. Do not acknowledge a reading by hand to hide an import failure.

## Icon And Rebuilding

The Shortcuts library uses a built-in glyph and colour; it may show the Health action's heart. For the YourOwnWeigh artwork on the iPhone Home Screen, use Add to Home Screen → Choose Photo/File and select [YourOwnWeigh Home Screen Icon.png](YourOwnWeigh%20Home%20Screen%20Icon.png).

`build_health_sync_shortcut.py` generates the editable `.unsigned.plist` and signs the distributable with Apple's `shortcuts sign --mode anyone`. Run it from a Mac with Shortcuts installed:

```sh
python3 'connectors/Apple Health/build_health_sync_shortcut.py'
```

The generator uses placeholders, not your installed Shortcut or account credentials. Review the unsigned plist before distributing. Do not run the Health Shortcut as an automated repository test—it writes Health data and acknowledges server records.
