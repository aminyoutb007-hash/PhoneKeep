# 04. Security

Security must be **felt** by the user, not just present: a calm lock badge, clear wording, no scary jargon.

## S1. Encryption by default and the keychain

**What the user sees and does:** during the first backup, one screen: "Choose a backup password". One field (with show/hide), a strength hint, and the line "Saved in your Keychain. You won't need to type it again. If you forget it, the backup can't be opened." The badge "🔒 Encrypted · on this computer" then appears on the phone card and in the phone window.

**Requirements**
- Encryption is on for every new phone. Turning it off: Settings → Security → a confirmation that lists what an unencrypted backup leaves out (saved passwords, Health, Wi-Fi networks, call history) and that anyone with the computer can read it.
- The password is stored in the Mac Keychain / Windows Credential Manager (one entry per phone), read silently when needed.
- If the phone already has a backup password the user doesn't know: explain the iPhone's own "Reset All Settings" path in plain steps (it keeps data, removes the backup password).
- Change password: old + new, done on the phone through the backup service.
- The password never appears on a command line, in logs or in crash reports.
- PhoneKeep never removes the stored password by itself. A backup that won't open with it asks for one to be typed; the stored password is replaced only by a typed one that opens the backup. (Lesson of 12 Nov: a failed open seconds after a snapshot wiped the owner's only copy.)
- The "if you forget it" warning is shown once more at the moments when the keychain and the backup may part ways: when the backup location changes, when backups are moved (B4), and when a backup is opened on another computer (B5).
- Turning encryption on, and changing the password, write to the phone and go through `phone_write.py` ([12-engineering.md](12-engineering.md#architecture-rules)). In the first-run guide, clicking **Turn on encryption** is itself the confirmation; no second dialog. Changing the password later gets a named confirmation ("Change the backup password on *Amin's iPhone*?").

**Done when**
- [ ] A new phone's first backup is encrypted with no extra click beyond choosing the password.
- [ ] The second backup and opening the phone window need no password.
- [ ] `ps`/Task Manager and the log files never show the password.

## S2. App lock

**What the user sees and does:** Settings → Security → "Lock PhoneKeep". On by default where the computer has Touch ID or Windows Hello. On a Mac without Touch ID it is off by default, and the first-run guide (E1) offers to turn it on using the computer password. Opening the phone window or a backup asks for Touch ID or the computer password. After 10 idle minutes (choosable) the window blurs and shows **Unlock**.

**Requirements**
- Uses the system authentication (LocalAuthentication on Mac, Windows Hello); no PhoneKeep-specific password.
- Scheduled backups still run while locked; browsing doesn't.

**Done when**
- [ ] Opening the phone window asks for Touch ID; cancelling keeps it closed.
- [ ] After the idle time the content is hidden until unlocked.

## S3. No network

**What the user sees and does:** Settings → Security shows "PhoneKeep never sends your data anywhere. Internet use: **Off**". Two things, and only two, can switch it on, each only when the user clicks: "Check for updates" and, if the spyware check (S5) ships, "Update indicators".

**Requirements**
- The app makes no internet connections. The only exceptions are the two opt-in actions above: the update check (one HTTPS request to the release page, no identifiers; it may also refresh the list of current iOS versions used by H5) and the indicator download for S5 (one HTTPS request to the indicator files, no identifiers), each made only when the user clicks its button.
- An automated test (in `tests/`, run in CI) guards every socket connection made while running a full backup, an export and a phone-window session, and fails if any goes anywhere other than the phone over USB / local Wi-Fi. An OS-level check on a real Mac is part of each release ([docs/release.md](../release.md)).

**Done when**
- [ ] A full backup + export + phone-window session shows zero outbound internet connections (socket guard in CI; OS-level monitor at release).

## S4. Signed and notarised installers

**What the user sees and does:** downloads, opens, and the app starts. No "can't be opened" warning, no Privacy & Security detour.

**Requirements**
- Mac: Developer ID signed, hardened runtime, notarised and stapled, for both Apple Silicon and Intel builds, in the GitHub Actions workflow (secrets for the certificate and notary credentials).
- Windows: installer and app signed with a code-signing certificate.
- Release notes list the checksum (SHA-256) of each installer.
- The workflow signs when the certificate secrets exist and falls back to an ad-hoc (Mac) / unsigned (Windows) build when they don't, so test builds keep working before the certificates arrive. The run summary says which it did. S4 is the last P1 feature because it waits for the certificates.

**Done when**
- [ ] A fresh Mac opens the downloaded app with no Gatekeeper warning.
- [ ] Windows shows the publisher name, not "Unknown publisher".

## S5. Spyware check

**P2 (moved from P1 until the MVT licence has been checked).** Shown as one part of the Security card (H5, [13-phone-health.md](13-phone-health.md#h5-security-card)).

**What the user sees and does:** in the phone window, a **Security check** icon. Click **Check now** → progress → a result card: green "No signs of known spyware found (checked against 2,340 indicators, updated 1 Nov 2026)" or amber with what was found, in plain words, and what to do next (with a link to help organisations).

**Requirements**
- Uses Amnesty International's open-source Mobile Verification Toolkit (MVT) checks on the latest (encrypted) backup, run locally.
- Indicator files are downloaded only when the user clicks **Update indicators** (the second allowed network use in S3), and can be imported from a file.
- Never says "your phone is safe": only "no signs of known spyware found".

**Done when**
- [ ] A clean backup gives the green result; a backup seeded with a test indicator gives the amber result naming it.

## S6. Encrypted exports

**What the user sees and does:** in every Save menu, a switch "Protect with a password". Saved as an encrypted ZIP (AES-256) or a password-protected PDF.

**Done when**
- [ ] The saved file can't be opened without the password on a stock Mac and Windows PC.

## S7. Activity log

**What the user sees and does:** Settings → Security → **Activity**: a simple list, "3 Nov 21:04 · Backed up Amin's iPhone (encrypted)", "3 Nov 21:10 · Saved 12 photos to Desktop", "Restored…", "Copied 2 files to VLC on the iPhone".

**Requirements:** kept locally, never contains message text or passwords; can be exported as CSV; kept 12 months.

**Done when**
- [ ] Each backup, save, restore and write-to-phone action appears once with date and summary.

## S8. Tamper check

**What the user sees and does:** nothing, normally. If a backup's files changed after it was made, an amber banner: "This backup was changed after it was made on 3 Nov. It may not be reliable."

**Requirements:** a checksum list is stored (and signed with a key in the keychain) at the end of each backup; verified when opening a snapshot (fast mode: sizes + dates; full check on demand).

**Done when**
- [ ] Editing one byte of a backup file triggers the banner on the full check.

## S9. Secure delete

**P3.** Deleting a backup offers "Erase securely" (overwrite before removal where the disk allows; on SSDs, explain that encryption is what protects deleted data).

## What is stored unencrypted

Everything from inside a backup is encrypted. Two small things next to it are not, so the app can draw its cards and timeline instantly without a password:

| File | Fields | Why |
| --- | --- | --- |
| `snapshot.json` per snapshot (B3) | snapshot date, size, iOS version, phone name, phone model | The timeline, phone cards and menu bar need them before any decryption |
| `format.json` per phone folder (B3) | format version number | So an older or newer PhoneKeep knows whether it can open the folder |

Nothing else: no phone number, no contact names, no thumbnails, no file names, nothing from inside the backup. Adding a field to either file needs written agreement.

## Existing guards (keep them)

| Risk | Guard in the code today |
| --- | --- |
| A tampered backup writes files outside the target folder | `safe_join` / `safe_local` refuse such paths; file IDs must be 40 hex characters |
| Message text runs as script in web exports | All text is HTML-escaped |
| Message text runs as a formula in Excel / CSV | Cells stored as text; CSV values starting with = + - @ get a leading apostrophe |
| Password visible in the process list | Passed through stdin to the helper |
