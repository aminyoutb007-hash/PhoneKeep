# 01. Principles

Every feature must follow these rules. When a feature and a rule disagree, the rule wins; raise it before building.

## Security

1. **Data stays on the computer.** PhoneKeep makes no network connections except an opt-in update check (see [04-security.md](04-security.md), S3). No analytics, no cloud, no account.
2. **Encrypted by default.** New backups are encrypted. Turning encryption off is possible but needs a confirmation that explains what is lost.
3. **Passwords never touch disk in plain text.** They live in the system keychain (Mac Keychain, Windows Credential Manager), and are never passed on a command line or written to logs.
4. **Read-only by default.** PhoneKeep only reads from the phone. Any action that writes to the phone (copying files, photos, music, contacts, restoring a backup) is:
   - started by an explicit button, never automatically;
   - confirmed in a dialog that names the phone and says exactly what will change;
   - logged in the activity log ([04-security.md](04-security.md), S7).
5. **Treat backups and phone files as untrusted input.** File paths are checked so nothing is written outside the chosen folder; text is escaped in web pages; spreadsheet cells are stored as plain text, never formulas. These guards already exist; keep them and use them in new code (see [12-engineering.md](12-engineering.md)).
6. **Least surprise.** Nothing is deleted without a confirmation. Deleted backups go to the system Trash/Recycle Bin unless secure delete is chosen.

## Ease of use

1. **One obvious next step on every screen.** One primary button, clearly labelled.
2. **No setup to start.** Defaults are safe and sensible; Settings are for changing them, never needed for a first backup.
3. **Plain words.** Say "your iPhone", "backup", "save"; never "UDID", "domain", "manifest", "AFC", "lockdown". Technical detail goes behind "Show details".
4. **Every error says what to do.** One sentence on what happened, one action to fix it ("Unlock your iPhone and tap Trust").
5. **Long jobs show progress.** Percentage, time left, and what is happening now. They can run in the background and notify when done.
6a. **Every transfer shows progress and a realistic time left.** A backup, an export, a save, a move, the redaction tool: each shows the percentage and "about N min left" worked out from the speed over the last few minutes (never from the first second), or "working out time left…" until there is enough to go on. (Owner's rule, 12 Nov 2026.)
6. **Nothing blocks the window.** Loading happens in the background; the window stays responsive; a cancel button is always available for long jobs.
7. **Remember choices.** Last folder, chosen formats, selected options persist between runs.

## Wording

- Buttons are verbs: "Back up now", "Save selected", "Open iPhone".
- Counts use correct plurals: "1 photo", "2 photos".
- Dates are shown in the computer's local format; times in its 12/24-hour setting.
- Sizes in KB/MB/GB with one decimal for MB and above.

## Design

- Keep the current look (green header, white cards, rounded buttons) unless a feature says otherwise.
- Must look right on **macOS and Windows**, in **light and dark mode**, at **100% and 200% scaling**.
- Tested visually **on a real Mac**: some drawing effects (e.g. stippled or see-through fills) work on Linux but not on macOS.
- Minimum window size 980 × 640; everything must still fit.
- Keyboard: every action reachable by keyboard; Space previews the selected item; Cmd/Ctrl-A selects all in lists and grids.
