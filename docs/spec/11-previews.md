# 11. Previews and nice touches

These make PhoneKeep pleasant. They never come before security or ease of use, and they must never slow the app down (see speed targets in [00-user-experience.md](00-user-experience.md)).

## Q1. Quick preview everywhere

**What the user sees and does:** select anything (photo, video, PDF, note, voice memo, song, file, attachment) and press **Space**: a preview opens over the window, large and centred; arrows move to the next item; Space or Esc closes. Videos and audio play with a simple scrubber.

**Requirements**
- On Mac use Quick Look where possible; elsewhere a built-in viewer for images, video, audio, PDF and text.
- Images, text and PDFs are previewed from memory; nothing decrypted is written to disk for them.
- Video and audio need a file to play: they are copied to a private temporary folder (readable only by the user) and deleted when PhoneKeep closes, and again at the next launch in case it crashed.

**Done when**
- [ ] Space previews every kind of item listed above on Mac and Windows.

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

**Done when**
- [ ] Moving the slider updates the open screen within 2 seconds.

## Q6. Photo extras

**P3.** A map of where photos were taken; "On this day" photos from past years on the Photos home. (The duplicate finder is now part of Photo clean-up, C1 in [13-phone-health.md](13-phone-health.md#c1-photo-clean-up-find-and-save).)

## Already done (keep them)

- The phone picture shows the phone's real wallpaper and the current time.
- The home screen of app icons with live counts.
- Chat previews as bubbles with inline photo thumbnails.
