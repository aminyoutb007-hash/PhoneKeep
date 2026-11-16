# 14. Direction A layouts (5.2)

The owner approved the Direction A ("Calm") mockups on 15 Nov 2026: [docs/design/direction-a/](../design/direction-a/README.md). They are a target, not pixel-exact: match the structure, spacing and colours in Tk with `theme.py`. Each layout keeps every function the screen has today; nothing is removed without the owner's word, and nothing new that writes to the iPhone or sends data off the computer is added.

Common rules for L1-L3 and the E1 refresh:
- Colours, fonts and spacing come from `theme.py` tokens (the mockup README lists them); no hard-coded colours.
- Icons are PhoneKeep's own simple line drawings. The mockups' WhatsApp tile uses a speech bubble with a handset; PhoneKeep draws a plain speech bubble there instead, so nothing looks like WhatsApp's logo.
- Slow work stays off the Tk thread, as today.
- Every screenshot for a PR uses the invented test phone only.

## L1. Phone window layout

**What the user sees and does:** as in `Phone.png`. The header has the phone's name, iOS and connection, the "Encrypted · never sent online" line, and Refresh from iPhone, Saved files and Save everything (the main button). The left column has the phone picture and a Snapshot card (the snapshot picker, how many snapshots and how much space they use on this computer). On the right are three summary cards (This iPhone, Battery, Storage, each opening its details), then "What's on this iPhone": a 4-column grid of tiles, each with an icon, a name and a count. Under the grid is one line saying what comes from the backup and what is read live.

**Requirements**
- Every section reachable today stays reachable from the tiles or the cards.
- Counts fill in as they arrive, as today; a tile without a count yet shows nothing rather than 0.
- The search box in the mockup ("Search everything") is E4; it isn't part of L1.

**Done when**
- [x] Side by side with `Phone.png` (invented test phone): the same structure, in the same order. *(15 Nov: [screenshot](../evidence/l1-phone-window/phone-window.png).)*
- [x] Every section opens from its tile, and the Battery and Storage cards open their details (`tests/test_l1_phone_window.py`; the This iPhone card has no details screen, as today).

## L2. Backup progress screen

**What the user sees and does:** as in `Backup.png`. One centred card shows the phone, "Backing up", its name and model, a large percentage, a bar, the time left, and what is being copied. When the phone needs the user ("Unlock it and enter its passcode"), an amber "Look at your iPhone" notice appears. Below are a list of steps (done, now, next) and Cancel. Under the card: "You can close this window. You'll get a notification when it's done."

**Requirements**
- Uses the progress the backup already reports; no new questions to the phone.
- The steps come from the phases the backup reports; a phase it can't tell apart isn't shown as its own step.
- Cancel works as it does today.

**Done when**
- [x] Side by side with `Backup.png` (invented test phone, stand-in backup): the same structure. *(16 Nov: [waiting for the passcode](../evidence/l2-backup-progress/waiting.png), [copying](../evidence/l2-backup-progress/copying.png). Two differences, on purpose: the steps are the phases the backup reports (it can't tell chats from photos while it copies), and the line under the card says "Keep PhoneKeep open until it's done": closing the main window quits PhoneKeep, and the window sends no notification when it's done.)*
- [x] With a stand-in backup: the percentage, the steps and the "Look at your iPhone" notice follow what the backup reports, and Cancel stops it (`tests/test_l2_backup_progress.py`).

## L3. Settings layout

**What the user sees and does:** as in `Settings.png`. A left list (Backups, Automatic backups, Security, Saving, Activity, About) and, on the right, the sections as white cards. Clicking an item in the list scrolls to its card.

**Requirements**
- Every setting there today is kept, in the card it belongs to.
- The mockup README calls "Lock PhoneKeep with Touch ID" and "Only while the iPhone is charging" ideas. Both already exist (S2, B2), so they stay as they are; nothing new is added.

**Done when**
- [x] Side by side with `Settings.png` (test home folder): the same structure. *(16 Nov: [screenshot](../evidence/l3-settings/settings.png). The Location card is now called "Where backups are kept", as in the mockup. Activity shows the newest lines of the record PhoneKeep already keeps on this computer (S7); About shows the version and opens the About box. Internet (S3) sits under Security; "Use an existing backup", which the mockup doesn't show, sits under Backups.)*
- [x] Every setting from before can still be found and changed, and the left list reaches each card (`tests/test_l3_settings.py`).

## E1 refresh: first-run guide layout

E1 (in [05-ease-of-use.md](05-ease-of-use.md#e1-first-run-guide)) gets the layout in `Welcome.png`: the steps on the left (done, now, next) and the current step on the right, with "Skip for now", Back and the main button. The left list has four steps: Connect your iPhone, Tap Trust, Choose a backup password, Back up now. Step 3 is the backup password the user types (strength shown, "Saved in your Keychain"); PhoneKeep never makes one up.

Where today's fifth step goes: when the first backup finishes, step 4's side shows "Done" with the two questions that are left from today's step 5, "Back up automatically every day?" (B2) and, on a Mac without Touch ID, "Lock PhoneKeep with your computer password?" (S2). They work as they do today. The Wi-Fi question moves out of step 5 into the step below, so it's asked once.

The "Use over Wi-Fi" step (owner, 15 Nov): after the first cable connection and Trust, the guide asks "Use this iPhone over Wi-Fi from now on?" with a switch that is off by default. It replaces today's step-5 Wi-Fi question. Turning the switch on shows the same named confirmation as today, "Turn on Wi-Fi backups for *<the phone's name>*?", and only after OK does PhoneKeep turn on the iPhone's Wi-Fi connections setting for this pairing, through `phone_write.py`. That writes to the phone, so it needs the user's choice every time and is never done silently. Cancel turns the switch back off and writes nothing; leaving the switch off, or turning it off, writes nothing. The step explains that phones never paired by cable can't appear over Wi-Fi (Apple's design). PhoneKeep never searches the network for other phones.

**Done when**
- [ ] Side by side with `Welcome.png` (test home folder): the same structure.
- [ ] The Wi-Fi switch is off by default; with it off, nothing is written to the phone. Turning it on shows the named confirmation first: Cancel turns it back off with nothing written; OK makes exactly one write (the Wi-Fi setting for this phone) through `phone_write.py` (test with a fake phone).
- [ ] After the first backup, the daily-backup question (B2) and, without Touch ID, the computer-password question (S2) are still asked, and the Wi-Fi question is asked only once in the whole guide (test).
