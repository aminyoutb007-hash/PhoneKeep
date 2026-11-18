# 11. Previews and nice touches

These make PhoneKeep pleasant. They never come before security or ease of use, and they must never slow the app down (see speed targets in [00-user-experience.md](00-user-experience.md)).

## Q1. Quick preview everywhere

**What the user sees and does:** select anything (photo, video, PDF, note, voice memo, song, file, attachment) and press **Space**: a preview opens over the window, large and centred; arrows move to the next item; Space or Esc closes. Videos and audio play with a simple scrubber.

**Requirements**
- On Mac use Quick Look where possible; elsewhere a built-in viewer for images, video, audio, PDF and text.
- Images, text and PDFs are previewed from memory; nothing decrypted is written to disk for them.
- Video and audio need a file to play: they are copied to a private temporary folder (readable only by the user) and deleted when PhoneKeep closes, and again at the next launch in case it crashed.

**Done when**
- [ ] Space previews every kind of item listed above on Mac and Windows. *(Mac: 14 Nov, `tools/real_check.py` on a real iPhone: a photo, a video, an iCloud-only photo and a PDF from an encrypted backup. Windows: 15 Nov, PDFs are now drawn in memory there too (PDFium), like photos and text: before, a PDF was copied to the private folder and opened in another app. The Windows test run (stand-in items) previews a photo, text, a PDF, a video and a memo. A real iPhone on a Windows PC: deferred.)*

## Q2. Chats as on the phone

**What the user sees and does:** voice notes show a waveform with a play button and length; links show a small preview card (from data already in the backup, never fetched online); reactions sit on the bubble's corner; replies show the quoted message above.

**Done when**
- [ ] A chat with each of these looks recognisably like the phone side by side.

## Q3. Contact cards

**What the user sees and does:** clicking a person anywhere (chat, call, contact) opens their card: photo, numbers, emails, and tabs for every Message / WhatsApp chat, call and voicemail with them, newest first.

**Done when**
- [ ] A person's card lists their chats in all three messaging apps, their calls and voicemails.

## Q4. Storage map

**What the user sees and does:** a colourful map of what fills the phone (V3) that can be clicked into: Photos → Videos → the largest videos.

## Q5. Backup timeline

**What the user sees and does:** a slider of snapshot dates under the phone picture (B3). Dragging it changes the whole phone window to that date; a small badge shows "Viewing 3 Nov".

**How it's built:**
- **Where:** in the Snapshot card under the phone picture, below B3's drop-down, once a phone has two snapshots or more. The oldest is on the left, the latest on the right, with a dot for each snapshot. It's a canvas drawn in the theme's colours: a Tk scale paints its handle in its background colour, which on the card is invisible.
- **Moving it:** dragging, a click or the arrow keys move the handle one snapshot at a time. The date under the handle shows at once in the drop-down above.
- **Opening a snapshot:** happens when the handle stops for 400 ms, or at once when the mouse is let go. It goes through B3's `open_snapshot`, so the screen that's open (Messages, Calls, All files…) opens again from that snapshot. A quick move past several snapshots opens only the one it stops on.
- **The badge:** "Viewing 3 Nov" is now a pill on the phone picture's screen, so it takes no room from the card. On a 1220×800 window (the default) the card still fits with the slider.
- **Speed:** on the owner's encrypted backups a switch first took about 2 s. Three things made it about half that:
  - **The derived key:** the key made from the backup password (two PBKDF2 rounds, half a second) is kept in memory for the next snapshot. It's keyed by a hash of the password and the keybag's salts and iteration counts, never written anywhere, and holds nothing the password itself (already kept in memory until PhoneKeep closes) doesn't give. A key that doesn't fit falls back to the password.
  - **`backup_info`:** kept while the backup's Info.plist, Manifest.plist and Manifest.db stay the same size and age. A real Info.plist takes a quarter of a second to read, and it was read three times per switch.
  - **The snapshot list:** the Snapshot card rebuilt on a switch reuses the list it already has.
- **When a switch opens:** the mouse opens the snapshot on letting go; the arrow keys after a 250 ms pause.

**Done when**
- [x] Moving the slider updates the open screen within 2 seconds.
  - Invented snapshots: `tests/test_q5_timeline.py`.
  - The owner's real encrypted snapshots: `tools/real_check.py`, Q5 step (seconds only).
  - Pictures with invented data, the chats left out: `docs/evidence/q5-timeline/`.

## Q6. Photo extras

**P3.** A map of where photos were taken; "On this day" photos from past years on the Photos home. (The duplicate finder is now part of Photo clean-up, C1 in [13-phone-health.md](13-phone-health.md#c1-photo-clean-up-find-and-save).)

## Already done (keep them)

- The phone picture shows the phone's real wallpaper and the current time.
- The home screen of app icons with live counts.
- Chat previews as bubbles with inline photo thumbnails.
