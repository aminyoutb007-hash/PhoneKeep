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
- [x] A person's card lists their chats in all three messaging apps, their calls and voicemails. *(19 Nov: tested on
  an invented backup, and on the owner's iPhone `tools/real_check.py`'s Q3 step found the same one-to-one chats, calls
  and voicemails for every contact as its own count, and the card's click opened the newest chat; #117.)*
- [x] In a group chat, the People window opens the chosen person's card. *(19 Nov, the owner's iPhone: in a WhatsApp
  group whose members all have hidden-number ids, the People window found the same contact as `tools/real_check.py`'s own
  count for everyone whose number it had, and Contact card opened that person's card.)*

**How it's built (people.py):** the card's foot has Chats, Calls and Voicemail tabs, found in the background from what
the phone window loads anyway. A number matches by its last nine digits, so the same number written differently is one
person; an email address matches as written (FaceTime and iMessage use them); a WhatsApp id gives its number. A
one-to-one chat matches by its number or address; a group chat is listed when the person wrote in it, with their own
messages counted. A click opens the chat, call or voicemail in its own view. The other way round: a one-to-one chat's
header, Calls and Voicemail have *Contact card*. A number two contacts share opens neither card (whose it is can't be
told), and PhoneKeep says that, not "isn't in Contacts". In a group chat, the People window has *Contact card* for the chosen person, found by the number their
messages came from. Newer WhatsApp hides group members' numbers behind ids of its own (…@lid); WhatsApp's own
LID.sqlite in the backup says which number each belongs to, and PhoneKeep reads it. The main window's "Choose the chats to export"
has no phone window behind it, so its People window has no *Contact card*.

## Q4. Storage map

**What the user sees and does:** a colourful map of what fills the phone (V3) that can be clicked into: Photos → Videos → the largest videos.

**How it's built** (5.2.5): Storage → **Storage map ›**. The whole iPhone as blocks, each as big as the space it takes (a squarified treemap), in the Storage colours: Apps, Photos, Messages, System, Other and Free. Blocks with › open what's inside, and the path at the top goes back up:
- **Photos** → Videos, Photos, and edits and other files, from the newest backup's file list. **Videos** → the 30 largest videos with their dates, the rest as one block; a click opens Photo clean-up on Large videos (C1), where they can be saved to the computer.
- **Apps** → the 20 largest apps (with their data, as the iPhone reports them), the rest as one block.
- **Messages** → its videos, photos and other attachments, and the messages themselves.

A block too small for its name is named under the map; pointing at a block shows its name, size and share. Read-only: the figures are the Storage screen's (V3) and the backup's file list, read once per backup in the background; nothing is asked of the phone. While the app sizes are still coming in, the map's top and Apps levels are drawn again as they arrive (at most every 2 seconds) and say so; the map and its path always use the phone's newest figures (5.2.6 follow-up).

**Done when**
- [x] On a real iPhone, the map adds up to the whole iPhone, Photos' blocks add up to the backup's photo files, and Photos › Videos lists its largest videos biggest first (`tools/real_check.py`, Q4 step). *(19 Nov, the owner's iPhone: passed three times, with System left off and said, as it can't be estimated there; #118.)*

## Q5. Backup timeline

**What the user sees and does:** a slider of snapshot dates under the phone picture (B3). Dragging it changes the whole phone window to that date; a small badge shows "Viewing 3 Nov".

**How it's built:**
- **Where:** in the Snapshot card under the phone picture, below B3's drop-down, once a phone has two snapshots or more. The oldest is on the left, the latest on the right, with a dot for each snapshot. It's a canvas drawn in the theme's colours: a Tk scale paints its handle in its background colour, which on the card is invisible.
- **Moving it:** dragging, a click or the arrow keys move the handle one snapshot at a time. The date under the handle shows at once in the drop-down above.
- **Opening a snapshot:** happens when the mouse is let go (a drag that pauses doesn't open anything yet), or 250 ms after the last arrow key. It goes through B3's `open_snapshot`, so the screen that's open (Messages, Calls, All files…) opens again from that snapshot. A quick move past several snapshots opens only the one it stops on.
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
