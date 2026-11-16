# 05. Ease of use

See also the journeys and patterns in [00-user-experience.md](00-user-experience.md).

## E1. First-run guide

*5.2: laid out as in [14-layouts.md](14-layouts.md#e1-refresh-first-run-guide-layout): four steps on the left; the Wi-Fi question moved to the Trust step; "done" is step 4's other side.*

**What the user sees and does:** on first launch, a short guide in the main window (not a separate wizard window), one step at a time, each with a picture:

1. **Connect your iPhone** with a cable (Wi-Fi can be set up later). Picture of a phone and cable.
2. **Tap Trust on your iPhone and enter your passcode.** Picture of the Trust prompt. Advances by itself when trusted.
3. **Choose a backup password** (S1).
4. **Back up now.** Progress, with "You can close this window; we'll tell you when it's done."
5. **Done.** "Back up automatically every day?" (B2) and "Back up over Wi-Fi from now on?" (turns on Wi-Fi sync on the phone, through `phone_write.py` with a named confirmation: "Turn on Wi-Fi backups for *Sam's iPhone*?"). On a Mac without Touch ID, also "Lock PhoneKeep with your computer password?" (S2).

**Requirements**
- Each step detects completion itself; no Next button where detection is possible.
- "Skip" is available but never the highlighted button.
- If no phone is detected after 20 seconds: three likely fixes (different cable or port, unlock the phone, on Windows "install the Apple Devices app (from the Microsoft Store) or iTunes").

**Done when**
- [ ] Usability test task 1 ([00-user-experience.md](00-user-experience.md)) passes with 4 of 5 people.
- [ ] A fresh install reaches "Back up now" in 3 clicks plus the password.

## E2. Menu bar and system tray helper

**What the user sees and does:** a small PhoneKeep icon in the Mac menu bar / Windows tray. Its menu: "Sam's iPhone · backed up 2 hours ago 🔒 · next tonight ~9 pm", **Back up now**, **Open iPhone**, **Open PhoneKeep**, **Pause automatic backups**, **Quit**. The icon shows a subtle progress ring during a backup. After a missed day the first line turns amber and carries the same one-line fix as the phone card (B2).

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
| Wi-Fi not set up (Windows) | Wi-Fi backups need the Apple Devices app (from the Microsoft Store) or iTunes, and one backup by cable first. | Install Apple Devices |
| Disk full | Not enough space on *Disk*: 12 GB needed, 4 GB free. | Change location |
| Wrong backup password | That password doesn't open this backup. | Try again |
| Unknown | Something went wrong. Your existing backups are safe. | Show details |

**Done when**
- [ ] Each situation above, reproduced on purpose, shows its message; none shows a raw error.

## E4. One search across the phone

**What the user sees and does:** a search box at the top of the phone window. Typing shows results grouped by app (Messages, WhatsApp, WhatsApp Business, Notes, Contacts, Calls, Files, Safari) with the matching words highlighted and dates. Clicking opens the item at that spot.

**Requirements**
- ~~A local search index per snapshot, built in the background after each backup, stored encrypted with the backup.~~ **Decided (owner, 16 Nov): in-memory only, by design (nothing decrypted outlives the app).** No index is saved.
- Finds partial words, ignores accents and case, supports Arabic and French text.

**How it's built (16 Nov):** "Search everything" sits on the phone window's home screen, beside "What's on this iPhone", as in the L1 mockup. Typing two letters or more shows the results in place of the tiles. They are grouped by app (Messages, WhatsApp, WhatsApp Business, Notes, Contacts, Calls, Safari), five per app with "Show all N in …", each with its chat, note or name, its date, and the matching words highlighted. A click opens that app with the item chosen and the same words in its own search box; a chat opens at the message that was clicked. The screens' own searches now match the same way. Files isn't searched: in PhoneKeep it lists the iPhone's apps live, and there is no text in it to search.

The first search reads each app from the open backup once (a few seconds on a large phone, "Getting everything ready to search…"). After that everything stays in memory while the window is open. **Nothing is written to disk**, by the owner's decision (16 Nov): no index file exists, so no copy of the chats sits next to the backup, encrypted or not, and nothing decrypted outlives the app. The in-memory search meets the speed target.

**Done when**
- [x] On a backup with 200,000 messages, first results show in under 1 second. *(16 Nov: 200,000 invented messages, French and Arabic among them; once the search is ready, every query answers in well under 1 second; getting ready took under a second on the owner's Mac (`tests/test_e4_search.py`). Screenshots on the tests' backup after X2 redaction: [home](../evidence/e4-search/home.png), [results](../evidence/e4-search/results.png).)*
- [ ] Usability test task 3 passes. *(The owner's usability test, moved to 5.3.)*

## E5. All phones and backups in one list

**What the user sees and does:** the main window's home shows a card for each phone ever backed up: wallpaper thumbnail, name, model, last backup, size, lock badge, "connected" dot. Click a card to open it; **Add another iPhone** at the end.

**How it's built:** "Your iPhones" sits under the phone card when PhoneKeep knows more than one phone: every phone connected now and every phone with a backup in the backup folder, connected ones first. Each card is a small phone picture (the saved home screen or wallpaper), the name, model and size of its newest snapshot, when it was last backed up, a green dot with Cable or Wi-Fi while it's connected, and the lock badge. A click opens that phone's own window: live when it's connected, else its newest backup on this computer, as Open a backup does (B5). An open window is brought back rather than opened twice. Opening a phone doesn't change which phone Back up now is for (B8). "Add another iPhone" sits at the end of the list's title line: it says to plug the phone in and tap Trust, then looks for phones. The list reads only files on this computer and writes nothing to any phone.

**Done when**
- [x] Two phones show as two cards; each opens its own phone window, even when not connected. *(16 Nov: two invented phones backed up, none connected: two cards, each opening a window for its own backup (`tests/test_e5_all_phones.py`); [screenshot](../evidence/e5-all-phones/main-window.png) with invented phones, one on the cable.)*

## E6. Dark mode

**What the user sees and does:** PhoneKeep follows the computer's light/dark setting (or a choice in Settings → Appearance).

**Done when**
- [x] Every screen is readable in dark mode; no white flashes; screenshots of all screens in both modes are attached to the pull request. *`tests/test_e6_dark_mode.py`:*
  - *text on every dark background is at least 4.5:1;*
  - *every widget of the main window, a phone window (home, Messages, Check-up, Notes, Storage) and Settings has no light background left, and every label is readable;*
  - *a new window is dark from the moment it's made.*

  *Screenshots of 15 screens in both modes (every phone-window screen, the main window, the first-run guide, the backup progress card, Settings and its Appearance card), invented test phone, chats and contacts from the X2-redacted copy: `docs/evidence/e6-dark-mode/`. The About box is the system's own and follows the system.*

**How it's built (16 Nov):** `theme.py` keeps one set of names with two sets of values. Light is Direction A exactly as agreed. Dark is the same calm teal, lifted so it reads on dark grey, with dark text on the main buttons.
- *When the mode is chosen:* once, as PhoneKeep opens (every window takes its colours as it's built). Settings → Appearance: "Same as this computer" (the default), Light or Dark.
  - With "Same as this computer", PhoneKeep follows the computer's setting each time it opens. Changing it, or the computer's setting, while PhoneKeep is open shows the next time it opens, and Settings says so.
- *The system's own controls:* on a Mac they follow the app's appearance (dark aqua). On Windows and Linux, Tk draws them, so they get PhoneKeep's dark colours. The About box and file dialogs are the system's own.
- *Saved files* (the web archive, chat PDFs) keep their own light look.

## E7. Fast with very large phones

**Requirements:** lists and grids show only what's visible (virtual scrolling); data loads in pages; nothing loads all messages or photos into memory at once. Meets the speed targets in [00-user-experience.md](00-user-experience.md).

**Done when**
- [ ] With a test backup of 300,000 messages and 50,000 photos, all speed targets are met on a base-model Mac.

## E8. Languages and accessibility

**P3.** French and Arabic (right-to-left layout) alongside English; every control has a VoiceOver / Narrator label; keyboard-only use works; text scales with the system setting.
