# 03. Backup

## B1. Back up by cable and Wi-Fi

**Status: Done. Keep it working.**

**What the user sees and does:** clicks **Back up now**. A progress card shows the percentage, time left and amount copied. Before copying starts it says "Your iPhone is getting the backup ready, keep it unlocked". When done: "Your iPhone is safely backed up".

**Requirements**
- Works over a cable and over Wi-Fi (Wi-Fi sync enabled on the phone).
- The first backup is full; later ones copy only changes.
- Progress comes from the phone's own percentage; time left is estimated from the last 5 minutes.
- A **Cancel** button is there while a backup runs (main window and first-run guide; principle 6). Cancelling stops the helper; the half-copied backup is left as "didn't finish" (amber, not red: "Backup cancelled. Back up again whenever you like; it carries on from here.") and the next backup completes it. The helper records no failed day for a cancel.
- An interrupted backup resumes next time without losing what was copied.

**Done when**
- [ ] A full and an incremental backup complete over cable and over Wi-Fi.
- [ ] Unplugging mid-backup shows "Backup paused: your iPhone disconnected. Reconnect it to continue." and the next run continues.

## B2. Scheduled automatic backups

**What the user sees and does:** after the first backup, "Back up automatically every day? **Yes** / Not now". In Settings → Backups: Daily / Weekly / Off, a time ("around 9 pm"), "Only when charging" switch. Backups then happen by themselves; a quiet notification reports each one.

**Requirements**
- Runs from the menu bar / tray helper (E2), so the main window can be closed.
- Starts when the phone is reachable (same Wi-Fi or cable) at or after the chosen time; tries again every 30 minutes until midnight.
- Skips if a backup less than 20 hours old exists.
- Never runs two backups of the same phone at once.
- Notifications: success ("iPhone backed up · 2 min · 140 MB of changes"); failure only after 3 failed days in a row, with the reason and the fix.
- Survives a computer restart (helper starts at login if the user agreed during setup).
- **Backup health on the phone card** (home window and E2 menu): "Last backup: 2 hours ago · next tonight around 9 pm". After one missed day the card turns amber and explains itself in one line with the fix, e.g. "Last backup 2 days ago. Connect your iPhone to the same Wi-Fi, or plug it in." A colour change alone is never the whole message.

**Done when**
- [ ] With "Daily, 9 pm", a backup starts by itself after 9 pm when the phone joins the Wi-Fi.
- [ ] Closing the main window does not stop scheduled backups.
- [ ] After restarting the computer, the next scheduled backup still runs.
- [ ] A second backup the same day is skipped.
- [ ] The phone card shows the next backup time, and after a missed day shows the amber line with its fix.

## B3. Snapshots over time

**What the user sees and does:** in the phone window, a **timeline** under the phone picture: "Today · Yesterday · 3 Nov · 27 Oct …". Picking a date shows the phone as it was then. Right-click a snapshot: **Keep forever** (lock), **Rename**, **Delete**.

**Requirements**
- Each backup creates a snapshot; unchanged files are shared between snapshots through a **content store** (see below) so 10 snapshots don't take 10× the space.
- Keeps the last 10 by default (Settings: 3 to 100, or "keep everything until the disk is 90% full").
- Locked snapshots are never deleted automatically; the oldest unlocked one goes first.
- Each snapshot shows date, size, iOS version and whether it's encrypted.
- **Upgrading:** on first launch, the single existing backup of each phone becomes snapshot 1. It is converted into the store, verified (file count and checksums), and only then is the old copy removed. If anything fails, the old backup is left exactly as it was.

**The content store (on-disk format)**
- Every backup file is stored once, named by the SHA-256 of its content, under `store/` in the phone's backup folder. A snapshot is a small list mapping the backup's file IDs to those hashes, plus the backup's own `Manifest.db`, `Manifest.plist`, `Info.plist` and `Status.plist`. Deleting a snapshot removes its list; files no one references any more are removed afterwards.
- Hashes, not hard links, so the store works the same on an internal disk, an external drive, exFAT and network drives (B4). **FAT32 is refused** with a plain message: "This drive uses an old format (FAT32) that can't hold files over 4 GB. Format it as exFAT or APFS, or choose another drive."
- The folder carries a **format version** (`format.json`: `{"format": 1}`). PhoneKeep refuses to touch a folder with a newer format than it knows, and migrates an older one in place after verifying, the same way as the upgrade above. Any change to the layout raises the number and adds a migration.
- Next to each snapshot sits a small unencrypted **sidecar** (`snapshot.json`) with exactly five fields: snapshot date, size, iOS version, phone name and model. Nothing else, so the timeline and phone cards draw instantly without decrypting anything (see [04-security.md](04-security.md#what-is-stored-unencrypted)).
- The owner's own choices about snapshots live in one small `snapshots.json` in the phone folder (agreed 11 Nov). Format, which later features may rely on:

  ```json
  {"20261103-210000": {"locked": true, "label": "Before the holiday"}}
  ```

  One entry per snapshot id, each with `locked` (bool, "Keep forever"; default false) and `label` (string, the name given with Rename, at most 80 characters; default "" = unnamed, shown by date). A snapshot with no entry is unnamed and not kept. These are the owner's words, not data from the phone; nothing from inside a backup goes there.
- The live backup the phone updates incrementally sits in `current/`; the snapshots share their files through the store. The newest backup therefore exists twice (live copy + store); every older snapshot costs only what changed.

**Done when**
- [ ] 5 backups on different days → 5 snapshots, total size well under 5 full copies.
- [ ] Opening an older snapshot shows a message deleted on the phone since then.
- [ ] A locked snapshot survives automatic clean-up.
- [ ] An existing 4.x backup becomes snapshot 1, opens, and the old copy is gone only after verification; a simulated failure leaves it untouched.
- [ ] A FAT32 drive is refused with the message above; an exFAT drive works.

## B4. Backup location and moving backups

**What the user sees and does:** Settings → Backups → **Location**: shows the folder, the free space and how much backups use; **Change…** opens a folder picker (any disk, external drive or network drive). When changing, PhoneKeep offers **Move my existing backups there**.

**Requirements**
- Moving copies everything, verifies it (file count and checksums), then removes the old copy; the old copy is kept if anything fails.
- Before a backup, warns if free space is below the estimated need: "Not enough space on *Backup Drive*: 12 GB needed, 4 GB free."
- If the location is unavailable (drive unplugged), backups wait and say so: "Connect *Backup Drive* to back up."
- FAT32 drives are refused (see B3); exFAT, APFS, NTFS and network drives are fine.
- The Location screen also answers "where is my data?": the folder, a **Show in Finder** / **Show folder** button, and the line "Encrypted · stays on this computer" (or "on *Backup Drive*").
- When the location changes, or backups are moved, the password warning from S1 is shown once more: the password lives in this computer's keychain; on another computer the backup needs the password typed.

**Done when**
- [ ] Backups move to an external drive and still open afterwards.
- [ ] Unplugging the drive gives the "Connect…" message, not an error.
- [ ] The Location screen shows the folder, the Show button and the "where is my data" line.

## B5. Open any backup and browse its files

**What the user sees and does:** File → **Open backup…** (also drag a backup folder onto the window). It opens in the phone window like a connected phone. An **All files** screen shows the backup as folders (by app), with preview and save.

**Requirements**
- Opens PhoneKeep backups and backups made by Finder or iTunes (default locations listed automatically; Full Disk Access guidance on macOS).
- Asks for the password of encrypted backups once and offers to store it in the keychain.
- All files: tree by app/area, size and date per file; Save keeps the folder structure.

**Done when**
- [ ] A Finder-made encrypted backup opens and its Messages appear.
- [ ] A single file can be previewed and saved from All files.

## B8. Choose which iPhone when several are reachable

**Why (owner, 13 Nov):** with two iPhones nearby, PhoneKeep takes the one on the cable, or else the first one the computer reports over Wi-Fi, without saying so. Unplugging one phone silently switched the window to the other phone over Wi-Fi.

**What the user sees and does:** when more than one iPhone is reachable, the main window says "2 iPhones nearby" and lists them: name, model, **cable** or **Wi-Fi**, last backup. One click picks the phone; the window shows that phone until the owner picks another or it disappears. The phone in the window never changes by itself: if the chosen phone goes away, the window says "*iPhone Amin* is no longer connected" and lists the others to pick from. Settings → Automatic backups has a tick box per phone ("Back up automatically"); the menu bar helper backs up each ticked phone in turn and names the phone in its notifications.

**Requirements**
- A phone reachable over both cable and Wi-Fi is listed once, as **cable**.
- With one phone reachable, nothing changes from today (no list, no extra click).
- The choice is remembered by the phone's ID; a phone seen for the first time is never backed up automatically until it is ticked.
- A backup always names its phone at the start ("Backing up *iPhone Amin* (cable)…").
- Two backups never run at once; the second waits for the first and says so.

**Done when**
- [ ] Two real iPhones, one on the cable and one on Wi-Fi: both listed with the right connection; picking either backs up that one.
- [ ] Unplugging the chosen phone does not switch the window to the other phone.
- [ ] With both ticked for automatic backups, the helper backs up both, one after the other, each named in its notification.

Related: [E5](05-ease-of-use.md#e5-all-phones-and-backups-in-one-list) (a card per phone ever backed up, P2) builds on this list.

## B6. Restore a backup to an iPhone

**What the user sees and does:** in the snapshot list, **Restore to iPhone…** → choose the phone → a confirmation: "Restore *Amin's iPhone* from 3 Nov? Everything on this iPhone will be replaced with the data from that day." The main button says **Restore**. Progress, then "Restore finished. Your iPhone will restart."

**Requirements**
- Checks Find My is off first and explains how to turn it off if not.
- Encrypted backups restore with their password (from the keychain).
- Logged in the activity log.
- Writes to the phone, so it follows the standing rule: nothing is written to an iPhone without the owner confirming first, every time. The confirmation names the phone and the snapshot date, and its button says **Restore**, never OK.
- Tested on a spare iPhone only (a restore replaces everything on the phone), never on the owner's own.

**Done when**
- [ ] A test phone restored from a snapshot shows that snapshot's messages and photos.
- [ ] Cancelling the confirmation changes nothing.

## B7. Restore while leaving some data out

**P3.** In the restore confirmation, a "Leave out" list (Contacts, Messages, Photos…). Done when the left-out data on the phone is unchanged after restore.
