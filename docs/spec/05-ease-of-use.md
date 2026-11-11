# 05. Ease of use

See also the journeys and patterns in [00-user-experience.md](00-user-experience.md).

## E1. First-run guide

**What the user sees and does:** on first launch, a short guide in the main window (not a separate wizard window), one step at a time, each with a picture:

1. **Connect your iPhone** with a cable (Wi-Fi can be set up later). Picture of a phone and cable.
2. **Tap Trust on your iPhone and enter your passcode.** Picture of the Trust prompt. Advances by itself when trusted.
3. **Choose a backup password** (S1).
4. **Back up now.** Progress, with "You can close this window; we'll tell you when it's done."
5. **Done.** "Back up automatically every day?" (B2) and "Back up over Wi-Fi from now on?" (turns on Wi-Fi sync on the phone).

**Requirements**
- Each step detects completion itself; no Next button where detection is possible.
- "Skip" is available but never the highlighted button.
- If no phone is detected after 20 seconds: three likely fixes (different cable or port, unlock the phone, on Windows install Apple Devices).

**Done when**
- [ ] Usability test task 1 ([00-user-experience.md](00-user-experience.md)) passes with 4 of 5 people.
- [ ] A fresh install reaches "Back up now" in 3 clicks plus the password.

## E2. Menu bar and system tray helper

**What the user sees and does:** a small PhoneKeep icon in the Mac menu bar / Windows tray. Its menu: "Amin's iPhone · backed up 2 hours ago 🔒", **Back up now**, **Open iPhone**, **Open PhoneKeep**, **Pause automatic backups**, **Quit**. The icon shows a subtle progress ring during a backup.

**Requirements**
- Starts at login if the user agreed (asked once, in E1 step 5).
- Runs scheduled backups (B2) and sends notifications.
- Uses very little memory and CPU when idle.

**Done when**
- [ ] With the main window closed, Back up now from the menu runs a backup and notifies when done.

## E3. Plain-language errors

**What the user sees and does:** problems appear as a banner with one sentence on what happened and one button to fix it. "Show details" reveals the technical text for support.

**Requirements:** a single table in code maps each known technical error to a message and action. At least:

| Situation | Message | Button |
| --- | --- | --- |
| Phone locked | Unlock your iPhone to continue. | Try again |
| Not trusted | Tap Trust on your iPhone and enter your passcode. | Try again |
| Wi-Fi unreachable | Can't reach your iPhone over Wi-Fi. Make sure it's on the same network, or use a cable. | Try again |
| Disk full | Not enough space on *Disk*: 12 GB needed, 4 GB free. | Change location |
| Wrong backup password | That password doesn't open this backup. | Try again |
| Unknown | Something went wrong. Your existing backups are safe. | Show details |

**Done when**
- [ ] Each situation above, reproduced on purpose, shows its message; none shows a raw error.

## E4. One search across the phone

**What the user sees and does:** a search box at the top of the phone window. Typing shows results grouped by app (Messages, WhatsApp, WhatsApp Business, Notes, Contacts, Calls, Files, Safari) with the matching words highlighted and dates. Clicking opens the item at that spot.

**Requirements**
- A local search index per snapshot, built in the background after each backup, stored encrypted with the backup.
- Finds partial words, ignores accents and case, supports Arabic and French text.

**Done when**
- [ ] On a backup with 200,000 messages, first results show in under 1 second.
- [ ] Usability test task 3 passes.

## E5. All phones and backups in one list

**What the user sees and does:** the main window's home shows a card for each phone ever backed up: wallpaper thumbnail, name, model, last backup, size, lock badge, "connected" dot. Click a card to open it; **Add another iPhone** at the end.

**Done when**
- [ ] Two phones show as two cards; each opens its own phone window, even when not connected.

## E6. Dark mode

**What the user sees and does:** PhoneKeep follows the computer's light/dark setting (or a choice in Settings → Appearance).

**Done when**
- [ ] Every screen is readable in dark mode; no white flashes; screenshots of all screens in both modes are attached to the pull request.

## E7. Fast with very large phones

**Requirements:** lists and grids show only what's visible (virtual scrolling); data loads in pages; nothing loads all messages or photos into memory at once. Meets the speed targets in [00-user-experience.md](00-user-experience.md).

**Done when**
- [ ] With a test backup of 300,000 messages and 50,000 photos, all speed targets are met on a base-model Mac.

## E8. Languages and accessibility

**P3.** French and Arabic (right-to-left layout) alongside English; every control has a VoiceOver / Narrator label; keyboard-only use works; text scales with the system setting.
