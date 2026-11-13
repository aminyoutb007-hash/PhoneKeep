# 00. User experience

**This is the most important file.** PhoneKeep wins on how it feels to use: calm, obvious, fast, safe. Every feature in the other files must fit the experience described here. If a requirement elsewhere makes the experience worse, stop and ask.

## Who we design for

- **Everyday iPhone owners** who want their phone safely copied and want to find things in it: a photo from last summer, a message from a supplier, a voicemail from a relative. Not technical. They should never see a technical word.
- **Small business owners** who keep customer conversations on WhatsApp Business and need them in Excel or PDF.
- **Careful people** who chose PhoneKeep because it is private: they want to see that their data stays with them.

## How it should feel

| Feeling | What creates it |
| --- | --- |
| **"I know what to do"** | One primary button per screen; plain words; the next step always visible |
| **"It's my phone, on my computer"** | The phone window looks like the phone: its wallpaper, its apps, its photos, its chats as bubbles |
| **"It's safe"** | A visible lock badge ("Encrypted · stays on this computer"); confirmations before anything changes the phone; nothing leaves the computer |
| **"It's quick"** | Instant feedback on every click; long work in the background with honest progress |
| **"It just happened"** | Automatic backups with a quiet notification; no need to open the app |

## The five journeys

Each journey has a target: clicks and time measured from a fresh install on a real Mac with a real iPhone. **A release may not make any of these slower or longer.**

### J1. First backup

1. Open PhoneKeep → a welcome screen: picture of an iPhone and a cable, "Connect your iPhone".
2. Phone connects → the phone's name and wallpaper appear; "Tap **Trust** on your iPhone" with a picture of the Trust prompt, if needed.
3. "Choose a backup password" (one field, shown strength, "Saved in your Keychain, you won't need to type it again").
4. **Back up now** → progress with time left. The user can close the window; a notification says when it's done.
5. Done screen: "Your iPhone is safely backed up" + **Open iPhone** + "Back up automatically every day? Yes / Not now".

**Target:** 3 clicks and 1 password to start; no other questions.

### J2. Everyday backups

- Nothing to do. When the phone is nearby (same Wi-Fi or cable), PhoneKeep backs up on the chosen schedule from the menu bar helper.
- A notification: "iPhone backed up · 2 min · 140 MB of changes". Clicking it opens the phone window.
- If a backup fails three days in a row: one clear notification with the fix.

**Target:** zero clicks.

### J3. Find something

1. Click the PhoneKeep menu bar icon → **Open iPhone**, or open the app → **Open iPhone**.
2. The phone window shows the home screen of apps with counts. A search box at the top searches everything.
3. Type "invoice" → results grouped by app (Messages, WhatsApp, Notes, Files), each with a preview line and date.
4. Click a result → the conversation or note opens at that spot, highlighted.

**Target:** under 10 seconds from opening the window to seeing the item.

### J4. Save or share something

1. In any app screen, tick items (or a date range) → the footer shows the count and size.
2. **Save** → choose a format (PDF, Excel, CSV, original files) with the most likely one pre-selected.
3. Saved → banner "Saved 12 photos" with **Show in Finder** / **Show in folder**.

**Target:** 3 clicks after selecting.

### J5. New phone or lost phone

1. Open PhoneKeep → pick the old phone's latest snapshot.
2. Browse it like the phone itself (works with no phone connected).
3. Restore it to the new iPhone (with a clear confirmation), or save what's needed.

**Target:** everything browsable without any phone connected.

## Screen map

```
Main window
├── Welcome / first-run guide (first launch only)
├── Home: my phones (cards: wallpaper thumbnail, name, last backup, lock badge)
│   ├── Back up now · Open iPhone · Settings
│   └── Backup progress (inline card) → Done card
├── Phone window (one per phone)
│   ├── Left: phone picture with wallpaper · device facts · snapshot picker (timeline)
│   ├── Top: search everything
│   ├── Home: app grid with counts
│   └── App screens: Photos · Messages · WhatsApp · WhatsApp Business · Calls · Contacts
│       · Voicemail · Notes · Calendar · Voice Memos · Safari · Music · Books · Files · Apps
│       · Check-up (storage, battery, stability, security)
├── Settings: backups (schedule, location, snapshots) · security (password, app lock) · appearance · advanced
└── Menu bar / tray helper: status · Back up now · Open iPhone · Quit
```

## Interaction patterns (use these everywhere)

| Pattern | Rule |
| --- | --- |
| **Selecting** | Click toggles a tick; Shift-click selects a range; Cmd/Ctrl-A all; a footer always shows "N selected · size" |
| **Previewing** | Space or double-click opens a quick preview of the selected item; arrows move to the next; Esc closes |
| **Saving** | One **Save** button in the footer; format choice in a small menu; remember the last choice per app |
| **Dates** | Every list with dates has the same date filter: All · Today · 7 days · 30 days · 3 months · 12 months · This year · Custom |
| **Search** | A search box at the top of every list; filters as you type; Esc clears |
| **Loading** | Skeleton rows or placeholder tiles immediately, filled in as data arrives; never a blank area |
| **Empty states** | Never just empty: say why ("No voicemails on this iPhone") and what to do, if anything |
| **Errors** | Inline banner at the top of the screen, red only for real failures: what happened + one button to fix or retry |
| **Confirmations** | Only for actions that delete or change the phone. Title = the action ("Restore Amin's iPhone?"); the main button repeats the verb ("Restore"), never "OK" |
| **Progress** | Percentage + time left + what is happening now ("Copying photos · 1.2 GB of 4.8 GB") + Cancel |
| **Undo** | Settings changes apply instantly and can be changed back; deletions go to the Trash first |

## Speed targets

| Moment | Target |
| --- | --- |
| Click to visible response | under 100 ms (button state, spinner, or content) |
| Open the phone window | home grid visible in under 1 s; counts fill in within 5 s |
| Open a chat with 10,000 messages | first screen of messages in under 1 s |
| Photo grid scroll | smooth (no visible stutter) with 50,000 photos |
| Search results | first results in under 1 s for a phone with 200,000 messages |

## Visual language

- Calm and light: white cards on a soft grey background, one green accent for primary actions and selection.
- Phone content looks like the phone: bubbles, real wallpaper, square photo grid, app-style icons.
- Status colours mean one thing each: green = done/safe, amber = needs attention, red = failed.
- A small lock badge wherever data is shown: "Encrypted · on this computer".
- Motion only to explain: a gentle fade when content loads, a slide when opening an app screen (under 200 ms). No decorative animation.

## Usability test (required before each release)

Five people who have never used PhoneKeep, each with their own iPhone. Watch, don't help. Each task passes when 4 of 5 complete it without help.

1. Make a first backup.
2. Find a photo from a given month and save it to the desktop.
3. Find a message containing a given word and save that chat as a PDF.
4. Turn on daily automatic backups.
5. Explain, in their own words, where their data is stored and whether it's protected.

Record the time for each task and any moment of hesitation, and attach the notes to the release pull request.
