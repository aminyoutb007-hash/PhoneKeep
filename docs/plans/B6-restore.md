# B6 Restore a backup to an iPhone: build plan

Status: **plan only, for the owner to agree before any code is written.** Spec: [03-backup.md#b6](../spec/03-backup.md#b6-restore-a-backup-to-an-iphone).

A restore **replaces everything on the phone**. It is the one PhoneKeep feature that can lose someone's data, so this plan is careful about three things:
- what gets checked before anything is sent;
- what the owner is asked, and when;
- how it is tested. The only real tests are on a spare iPhone, never the owner's own.

## 1. What the owner sees

1. **Starting a restore.** There are two ways in:
   - In the phone window, the snapshot drop-down's **⋯** menu → **Restore to iPhone…**.
   - In Settings → Backups, select a snapshot → **Restore to iPhone…**.
2. **Choose the phone.** The B8 phone cards are shown. Only phones **on the cable** can be picked. Phones on Wi-Fi are greyed out with the line "Restoring needs the cable".
   - If the snapshot is of a *different* iPhone, a line says so: "This backup is of *Test iPhone A*; it will be restored onto *Test iPhone B*".
3. **Checks run.** Each shows as a ticked line. If any fails, the dialog shows the fix, and Restore stays disabled (§2).
4. **Confirmation.** It uses the spec's exact wording: "Restore *Test iPhone B* from 3 Nov? Everything on this iPhone will be replaced with the data from that day."
   - The buttons are **Restore** (red) and **Cancel**. There is never an OK button.
   - Cancel changes nothing, so the second Done-when line holds by construction.
5. **Progress.** It shows as a percentage, with a time left (`ui.Eta`).
   - If the phone asks for its passcode, the existing big notice is reused (PKPASSCODE, as in backups).
   - **Cancel** is available only until the phone starts receiving data. After that it is disabled, with the line "Stopping now would leave the iPhone half-restored". §5 explains why.
6. **When it finishes.** "Restore finished. Your iPhone will restart." Then "Apps download again from the App Store once you sign in with your Apple ID". The restore is logged in the activity log as "Restored *Test iPhone B* from the 3 Nov snapshot".

## 2. Checks before anything is written (all read-only)

| Check | How | If it fails |
|---|---|---|
| Phone on the cable | `ConnectionType == "USB"` from the device list | "Plug the iPhone in with a cable." |
| Find My is off | lockdown `get_value("com.apple.fmip", "IsAssociated")`. *To verify on the spare phone: the domain and key name.* If it can't be read, the restore attempt itself fails cleanly with a Find My error, and we show the same help | Steps: Settings → [your name] → Find My → Find My iPhone → off (needs the Apple ID password). |
| iOS on the phone ≥ iOS in the backup | `ProductVersion` vs the snapshot's `snapshot.json` "ios" | "This backup is from iOS 26.1; the iPhone has 18.6. Update the iPhone first (Settings → General → Software Update)." |
| The backup password opens it (encrypted backups) | Keychain password (S1), then `iphone_backup_decrypt` `test_decryption()`. If the keychain has none, ask (never generate one) | The usual password dialog, with the reset help. |
| Space on the computer for the staging folder (§3) | `shutil.disk_usage` on the backup drive vs the snapshot size. On a drive with hard links this needs only a few MB | "Needs about 38 GB free on <drive>." |
| Battery | `battery_state()`: level ≥ 20% or charging | "Charge the iPhone to at least 20% or leave it on the charger." |
| No backup running | The B8 global `backup-running.lock` | "Waiting for the backup of … to finish" (the same wait as B8). |
| Helper paused | The helper (E2) must not start an automatic backup during a restore: the restore holds the same lock file | none |

## 3. Turning a snapshot into a folder the phone accepts

A PhoneKeep snapshot isn't an iTunes-style folder. It is `files.json` plus blobs in `store/`, keyed by SHA-256 (see `snapshots.py`). `Mobilebackup2Service.restore()` needs `<dir>/<source UDID>/` with `Manifest.db`, `Manifest.plist`, `Info.plist`, `Status.plist` and each file at `xx/<fileID>`.

New function `snapshots.materialise(backup_dir, udid, sid, dest) -> Path`:
1. **Hard-link** each blob to `dest/<udid>/<id[:2]>/<id>`, on the same drive as the store. Hard links cost no space and are instant.
2. **Copy instead** where hard links aren't possible: exFAT, network drives, or a different drive. Before copying, check there is enough space.
3. Copy the four manifest files.
4. Verify every file ID in `Manifest.db` exists and that the sizes match `hashes.json`, the same verify step as `make_snapshot`.
5. Delete the staging folder afterwards, in a `finally` and at next start, like the Q1 preview folder.

The **latest** snapshot can also be restored straight from `current/` (`live_root`). The plan still materialises it, so one code path is tested.

## 4. Running it

- **Launcher:** a new `launcher --pk-restore --udid <target> --source <backup UDID> <staging dir>`. The password comes on **stdin** (as `--pk-encryption` does), never on the command line. It prints the same machine-readable lines as `--pk-backup`:
  - `PKPCT`,
  - `PKPASSCODE shown/done`,
  - `PKERR`,
  - a final `PKRESTORED`.
- **Call:** `Mobilebackup2Service.restore(dir, system=?, reboot=True, copy=False, settings=True, remove=False, password=…, source=…)`.
  - `copy=False`: we already made the staging copy, so the service needn't copy the folder again.
  - `remove=False` (iOS's own default): items not in the backup are not deleted separately. The restore already replaces the user data.
  - **`system`: owner to confirm after the spare-phone test.** Finder's full restore sets it. Messages and photos are in HomeDomain and CameraRollDomain, which restore either way. The plan is to start with `system=True` to match Finder, then check the result.
- **App side:** `phonekeep.restore_backup(...)` in `phonekeep.py`, mirroring `make_backup`. It handles the attention/passcode callback, the activity log line and the lock file. It uses no new dependencies (pymobiledevice3 already has `restore`).

## 5. Things that can go wrong, and what PhoneKeep says

- **Cable pulled or computer asleep mid-restore.** iOS shows "Restore in progress" and is unusable until a restore finishes.
  - PhoneKeep prevents sleep during the restore (`caffeinate -i` on Mac, `SetThreadExecutionState` on Windows).
  - On the next connection, it offers **Restore again** from the same snapshot. The phone window detects the state from lockdown `CloudBackupEnabled`/restore status. *To verify on the spare phone: what lockdown reports during a broken restore.*
- **Wrong password.** Caught by the check in §2 before anything is sent.
- **Restoring a newer iOS backup onto an older iOS.** Caught by the check in §2, because the phone would refuse.
- **Apps.** The restore holds app data, not the apps. iOS re-downloads the apps after sign-in. The finished screen says so.
- **Health/Keychain data.** This is only in encrypted backups. The confirmation says "Passwords and Health data come back only from encrypted backups" when the snapshot is not encrypted.

## 6. Tests

**Automatic** (in `tests/test_b6_restore.py`, with a stub launcher as in S1/B1):
- `materialise` builds the right layout with hard links. With hard links disabled, it copies. It refuses when there isn't enough space. Its verify step catches a missing blob.
- Each check in §2 blocks Restore with its message, using stand-in values.
- Cancel at the confirmation means the stub launcher is never run, and nothing is staged or logged.
- The password reaches the launcher on stdin only, never in `argv`.
- Progress and passcode lines drive the window. After the first `PKPCT`, Cancel is disabled.
- There is exactly one activity log line. No backup or helper runs at the same time (lock file).

**Real: spare iPhone only, done by the owner.** It must never be the owner's own phone, and I won't run it.
1. Back up the spare phone with PhoneKeep (snapshot A).
2. Send it a few new messages and take two photos.
3. Restore snapshot A. The new messages and photos are gone, and snapshot A's are there. This ticks Done-when 1.
4. Start a restore and press Cancel at the confirmation. Nothing on the phone changes. This ticks Done-when 2.
5. Repeat step 3 with an encrypted snapshot.
6. Repeat step 3 with Find My on: the check blocks it with the steps.

## 7. Pull requests

1. **B6a: staging and checks.** `snapshots.materialise`, the §2 checks and `launcher --pk-restore`, all tested with stubs. Nothing user-facing.
2. **B6b: the restore window.** Menu entries, the phone choice, confirmation, progress, the finished screen, the activity log line, and help text. It includes the spare-phone evidence for both Done-when lines.

## 8. Questions for the owner (before B6a starts)

1. **Is a spare iPhone available for the real test?** Without one, B6 can be built and stub-tested, but its Done-when lines can't be ticked.
2. **Should restoring one phone's backup onto another phone (A → B) be in B6, or wait for the P3 migration feature?** The plan allows it, with the warning line in §1 step 2. It is one extra parameter (`source=`).
3. Should `system=True` (Finder's behaviour) be the default? I'll confirm it on the spare phone.
4. Should Restore also be offered for **Finder/iTunes backup folders** opened with B5, not just PhoneKeep snapshots? Those are already in the right layout, so it's cheap, but their password isn't in the keychain.
