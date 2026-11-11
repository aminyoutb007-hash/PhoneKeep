# 03. Backup

## B1. Back up by cable and Wi-Fi

**Status: Done. Keep it working.**

**What the user sees and does:** clicks **Back up now**. A progress card shows the percentage, time left and amount copied. Before copying starts it says "Your iPhone is getting the backup ready, keep it unlocked". When done: "Your iPhone is safely backed up".

**Requirements**
- Works over a cable and over Wi-Fi (Wi-Fi sync enabled on the phone).
- The first backup is full; later ones copy only changes.
- Progress comes from the phone's own percentage; time left is estimated from the last 5 minutes.
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

**Done when**
- [ ] With "Daily, 9 pm", a backup starts by itself after 9 pm when the phone joins the Wi-Fi.
- [ ] Closing the main window does not stop scheduled backups.
- [ ] After restarting the computer, the next scheduled backup still runs.
- [ ] A second backup the same day is skipped.

## B3. Snapshots over time

**What the user sees and does:** in the phone window, a **timeline** under the phone picture: "Today · Yesterday · 3 Nov · 27 Oct …". Picking a date shows the phone as it was then. Right-click a snapshot: **Keep forever** (lock), **Rename**, **Delete**.

**Requirements**
- Each backup creates a snapshot; unchanged files are shared between snapshots (hard links or a content store) so 10 snapshots don't take 10× the space.
- Keeps the last 10 by default (Settings: 3 to 100, or "keep everything until the disk is 90% full").
- Locked snapshots are never deleted automatically; the oldest unlocked one goes first.
- Each snapshot shows date, size, iOS version and whether it's encrypted.

**Done when**
- [ ] 5 backups on different days → 5 snapshots, total size well under 5 full copies.
- [ ] Opening an older snapshot shows a message deleted on the phone since then.
- [ ] A locked snapshot survives automatic clean-up.

## B4. Backup location and moving backups

**What the user sees and does:** Settings → Backups → **Location**: shows the folder, the free space and how much backups use; **Change…** opens a folder picker (any disk, external drive or network drive). When changing, PhoneKeep offers **Move my existing backups there**.

**Requirements**
- Moving copies everything, verifies it (file count and checksums), then removes the old copy; the old copy is kept if anything fails.
- Before a backup, warns if free space is below the estimated need: "Not enough space on *Backup Drive*: 12 GB needed, 4 GB free."
- If the location is unavailable (drive unplugged), backups wait and say so: "Connect *Backup Drive* to back up."

**Done when**
- [ ] Backups move to an external drive and still open afterwards.
- [ ] Unplugging the drive gives the "Connect…" message, not an error.

## B5. Open any backup and browse its files

**What the user sees and does:** File → **Open backup…** (also drag a backup folder onto the window). It opens in the phone window like a connected phone. An **All files** screen shows the backup as folders (by app), with preview and save.

**Requirements**
- Opens PhoneKeep backups and backups made by Finder or iTunes (default locations listed automatically; Full Disk Access guidance on macOS).
- Asks for the password of encrypted backups once and offers to store it in the keychain.
- All files: tree by app/area, size and date per file; Save keeps the folder structure.

**Done when**
- [ ] A Finder-made encrypted backup opens and its Messages appear.
- [ ] A single file can be previewed and saved from All files.

## B6. Restore a backup to an iPhone

**What the user sees and does:** in the snapshot list, **Restore to iPhone…** → choose the phone → a confirmation: "Restore *Amin's iPhone* from 3 Nov? Everything on this iPhone will be replaced with the data from that day." The main button says **Restore**. Progress, then "Restore finished. Your iPhone will restart."

**Requirements**
- Checks Find My is off first and explains how to turn it off if not.
- Encrypted backups restore with their password (from the keychain).
- Logged in the activity log.

**Done when**
- [ ] A test phone restored from a snapshot shows that snapshot's messages and photos.
- [ ] Cancelling the confirmation changes nothing.

## B7. Restore while leaving some data out

**P3.** In the restore confirmation, a "Leave out" list (Contacts, Messages, Photos…). Done when the left-out data on the phone is unchanged after restore.
