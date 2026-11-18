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

**How it's built:**
- **Voice notes** (`voicenote.py`): the length and waveform come from the file alone, without decoding any sound.
  - A voice note is compressed with a variable bit rate (Opus, AAC), so each packet takes more bytes when there's more sound. The packet sizes every container lists draw the recording's shape.
  - Read from CAF (Messages' "Audio Message.caf": 'desc' and 'pakt'), Ogg Opus (WhatsApp: segment tables, the last granule position less the pre-skip) and MP4/M4A (AAC: 'mdhd' and 'stsz').
  - 36 bars, from the quiet level (10th percentile) to the loud one (95th).
  - Bounded: at most 64 MB and 2 million packets; a cut-off page or table, or a box past its end, gives nothing.
  - Read from the backup in memory (Q1's way), once per note, on the chat's worker thread. A canvas in the bubble shows ▶, the bars and the length, and a click plays the note in M6's viewer. A note that can't be read keeps its "🎤 Voice note" label.
- **Replies and reactions:** Messages' replies and reactions as M4 reads them.
  - The quoted message is drawn above the reply in a small, muted line (cut at 140 characters).
  - The reactions follow the message's time as the phone's marks (Loved ❤️, Liked 👍…, or the emoji itself), a mark given by several people counted ("❤️ 2").
  - WhatsApp's replies and reactions aren't read (M4's decision: the backup doesn't say them reliably).
- **Link previews:**
  - Messages: the archived LPLinkMetadata (title, site name, summary, URL) in a link balloon's payload_data.
  - WhatsApp: ZWAMESSAGEDATAITEM (title, summary, the matched link; the first link of the message).
  - The card is drawn under the text: title in bold, then the summary and site, muted. It's never fetched and **opens nothing**: opening a link would go online, which PhoneKeep doesn't do without the owner's OK.

**Done when**
- [ ] A chat with each of these looks recognisably like the phone side by side.
  - Each part is checked on the owner's real backup by `tools/real_check.py` (Q2 step, counts only): every link preview Messages and WhatsApp kept makes a card, and the voice notes give a waveform and the length WhatsApp shows.
  - The side-by-side look with the phone is the owner's check.

## Q3. Contact cards

**What the user sees and does:** clicking a person anywhere (chat, call, contact) opens their card: photo, numbers, emails, and tabs for every Message / WhatsApp chat, call and voicemail with them, newest first.

**Done when**
- [ ] A person's card lists their chats in all three messaging apps, their calls and voicemails.

## Q4. Storage map

**What the user sees and does:** a colourful map of what fills the phone (V3) that can be clicked into: Photos → Videos → the largest videos.

## Q5. Backup timeline

**What the user sees and does:** a slider of snapshot dates under the phone picture (B3). Dragging it changes the whole phone window to that date; a small badge shows "Viewing 3 Nov".

**Done when**
- [ ] Moving the slider updates the open screen within 2 seconds.

## Q6. Photo extras

**P3.** A map of where photos were taken; "On this day" photos from past years on the Photos home. (The duplicate finder is now part of Photo clean-up, C1 in [13-phone-health.md](13-phone-health.md#c1-photo-clean-up-find-and-save).)

## Already done (keep them)

- The phone picture shows the phone's real wallpaper and the current time.
- The home screen of app icons with live counts.
- Chat previews as bubbles with inline photo thumbnails.
