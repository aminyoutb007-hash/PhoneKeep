# 06. Messages, WhatsApp and WhatsApp Business

All three work the same way: a chat list on the left, the conversation as bubbles on the right, the same date filter, the same Save menu.

## M1. Browse Messages

**Status: Done. Keep it working.**

**What the user sees and does:** the chat list shows the contact's name (from Contacts), the last message and date. Clicking shows the conversation as bubbles (sent on the right, green/blue as on the phone), with photos inline, dates as separators.

**Done when**
- [ ] On a real phone, 5 sampled conversations match the phone exactly (order, senders, text, photos).

## M2. Browse WhatsApp and WhatsApp Business

**Status: Done. Keep it working.**

**Requirements:** same layout as M1; groups show the sender's name above each bubble; polls, calls (missed / answered with duration), locations, contacts and deleted messages show as labelled items, not raw text.

**Done when**
- [ ] Groups, voice notes, polls and calls appear correctly in a real WhatsApp and a real WhatsApp Business account.

## M3. Chats to PDF and print

**What the user sees and does:** tick one or more chats (and optionally a date range) → **Save** → **PDF**. The PDF looks like the phone: bubbles, photos inline, emoji, the chat name and date range at the top of each page, page numbers at the bottom. **Print** makes the same PDF and sends it to the system print dialog, so the printed page is identical to the saved one.

**Requirements**
- One PDF per chat (or one combined PDF, a choice in the Save menu).
- Images are scaled to fit, keeping quality readable; videos show their first frame with a play icon and the file name.
- Voice notes show as "Voice message · 0:42"; with transcription available (Q2), the text appears below.
- Right-to-left text (Arabic) lays out correctly.

**How it's built (5.0):** `chat_pdf.py` (ReportLab + Pillow) with the fonts in `assets/fonts`: DejaVu Sans (Latin, Arabic, symbols) and Noto Color Emoji (each emoji drawn once as a small image). Arabic is shaped (arabic-reshaper; whole-word ligatures off, since fonts rarely have them) and reordered per line (python-bidi) after wrapping in reading order. Characters the font lacks fall back to their standard decomposition (ﷺ → the full phrase). Main window: a **PDF** chip next to Web pages / Excel / CSV (one PDF per chat). Phone window: **Save ticked as PDF** (asks "one PDF with all of them, or one for each chat" when several are ticked) and **Print** (the same combined PDF, then the system print dialog: Preview on a Mac, the default PDF app on Windows). Known gap: videos show a ▶ tile with the file name, not their first frame (needs a video decoder; 5.1).

**Done when**
- [x] A 2,000-message chat with photos produces a PDF in under 30 seconds that opens in Preview / Acrobat and prints correctly. (Test: 2,000 messages with 200 full-size photos in about 3 s, 221 pages, renders with poppler. Mac, 12–13 Nov: real chats saved as PDF open in Preview; Print shows the system print panel and prints only when the owner presses Print.)
- [x] Arabic, French and emoji render correctly. (Test: every drawn character is in the embedded font, Arabic in joined forms and reading order, emoji sequences drawn in colour; looked at on rendered pages. Mac, 12–13 Nov: the owner's real French/emoji chats and an Arabic chat read correctly on the release build.)

## M4. Full detail in Excel and CSV

**Requirements:** add these columns to chat spreadsheets: Reply to (quoted text), Reactions, Edited at, Deleted at, Read at, Service (iMessage / SMS / WhatsApp), Group sender number. Keep existing columns and safety (cells as text).

**How it's built (17 Nov):** the seven columns follow the first seven in every chat sheet and CSV file.
- *Messages:* a reply shows the text of the message it answers (up to 200 characters). Reactions ("Love (Sam)", or the emoji a newer iPhone allows) sit on the message they react to and are not rows of their own; a reaction taken back is gone, and a person's later reaction replaces their earlier one. Edited at, Deleted at (an unsent message, shown as "This message was deleted") and Read at come from the message's own times. Service is per message (iMessage, SMS, RCS). The group sender number is the sender's number or email in group chats.
- *WhatsApp:* only Group sender number (from a member's phone-number ID; a member WhatsApp shows by a hidden-number ID has none) and Service. *Decided: left blank for WhatsApp* Reply to, Reactions, Edited at, Deleted at and Read at: in a WhatsApp backup these are inside undocumented binary fields that change between WhatsApp versions, so PhoneKeep doesn't guess.
- An older Messages database without these columns still saves, with those cells blank. The extra detail isn't searched: the word filter and the search look at a message's own words, not at the text a reply quotes.
- Speed (E7): the detail is read with small separate queries, and the times are kept as Messages stores them until a spreadsheet is written. `tests/make_big.py`'s 300,000 messages now carry M4's detail as a real phone does (most with a read time, 1 in 100 a reply, 1 in 100 edited, 3,000 reactions), and every E7 target still holds.

**Done when**
- [ ] A chat with replies, reactions and an edited message shows all three in Excel. *(17 Nov: `tests/test_m4_full_detail.py` on invented Messages and WhatsApp databases checks every new column in Excel and CSV, a quoted formula staying text, and an older database. On the owner's iPhone, `tools/real_check.py` counts replies, reactions, edits and read times straight from the latest backup's sms.db, then checks that the export reads the same messages and that the saved Excel file holds them: it passes, and the read times are there, but that backup's Messages has no replies, reactions or edits yet (sms.db itself says so), so the real-iPhone part waits for a chat that has them.)*

## M5. Show one person in a group chat

**What the user sees and does:** in a group chat, a "People" button lists participants with message counts; ticking one or more shows only their messages. Save uses the same filter.

**Done when**
- [x] Filtering a group to one person shows only their messages, in preview and in the saved Excel and PDF. *(17 Nov: `tests/test_m5_group_person.py`, in the real phone window on an invented backup, ticks one person in a Messages group and in a WhatsApp group: the preview, the chat's row and the footer show only theirs, and Excel, CSV and Save ticked as PDF keep only their messages, with a date range too. On the owner's iPhone, `tools/real_check.py` takes a real group from the latest backup (Messages, or WhatsApp when Messages has none), sorts its messages by person straight from the database, saves it for the busiest person through the phone window's own save, and checks that the Excel file has exactly their messages and the PDF no one else's name: it passes on a WhatsApp group.)*

**How it's built (17 Nov):** a group chat's preview has a **People** button. It opens a list of the people in the chat with how many messages each sent, most first ("You" for your own). Ticking one or more shows only their messages; nobody ticked, or **Everyone**, shows the whole chat. While some people are ticked, the chat's row says "only <name>" (or "only 3 people") and counts only their messages, with the date range too, and so does the footer. Save, Print and the exports (Excel, CSV, PDF, web page) of the ticked chats keep the same choice; other ticked chats are saved whole.
- A person is who the chat shows as the sender. Group updates (renamed, joined) aren't anyone's, so they're left out while some people are ticked.
- WhatsApp: a first name or contact name that several people in one group share names none of them (on a real phone every member had the same "first name"), so those members are shown by their push name or WhatsApp ID instead, and the People list tells them apart. This also fixes the sender shown in those groups' previews and saves. "Several people" means more than two member IDs, or two of the same kind: one person can be in a group under a phone-number ID and a hidden-number (@lid) ID with one contact name, and that name stays.
- Showing another chat closes the People list; each chat keeps its own choice.
- The choice is kept while the chat list is open; it isn't saved.

## M6. Media viewer for chat attachments

**What the user sees and does:** clicking a photo or video in a chat opens it large; arrow keys move through the chat's other media; a **Media** tab on each chat shows all its photos, videos, voice notes and documents in a grid with **Save all**.

**Done when**
- [x] A chat's Media tab shows every attachment; Save all saves them with their original dates. *(17 Nov: `tests/test_m6_media_viewer.py`, in the real phone window on an invented backup: a Messages chat with a photo, a video, a voice note, a document and one attachment not in the backup, a group, a chat with 3,000 photos, and a WhatsApp chat with a photo, a voice note and a photo never downloaded. The Media tab shows every one; Save all saves each the backup has, byte for byte, named and dated when it was sent, and counts the rest. On the owner's iPhone, `tools/real_check.py` counts a real chat's attachments straight from sms.db and the backup's file list and checks the Media tab and Save all against them: on a real Messages chat with attachments, some of them not in the backup, the Media tab shows every one, Save all saves exactly those the backup has, each dated when it was sent, and a real photo is shown large. Screenshots on the tests' backup after X2 redaction (its photos are blank placeholders): [Media tab](../evidence/m6-media-viewer/media.png), [the chat's links](../evidence/m6-media-viewer/chat.png).)*

**How it's built (17 Nov):**
- **In a chat:** a photo (its thumbnail), a video, a voice note or a document is a link: a click opens it large, in the same viewer as Space everywhere else (Q1). ← and → go through the chat's other attachments, oldest to newest as in the chat; "3 of 40" says where you are. Photos, PDFs and text are shown from memory; a video or a voice note plays in the computer's own player from PhoneKeep's private folder, which goes when PhoneKeep closes. One that isn't in the backup (WhatsApp never downloaded it, or the iPhone left it out) says so.
- **The Media tab:** each chat's preview has **Messages** and **Media**. Media shows every photo, video, voice note and document as tiles, newest first, with a choice of kind (All, Photos, Videos, Voice notes and audio, Documents) and a count of each. Stickers count as photos and GIFs as videos. A tile not in the backup says "Not in the backup". A click on a tile opens it large; the arrows go through the tiles shown. As in the photo grid (E7), only the rows on screen have tiles and only their thumbnails are made, so a chat with thousands of attachments scrolls smoothly.
- **Save all** asks for a folder and saves into a new folder in it named after the chat ("Film club media"; a second save makes "Film club media (2)"). Each file keeps its own bytes and name, with when it was sent in front ("2026-03-01 10.00.00 IMG_0001.JPG"), and its date is when it was sent, so the files sort in the order of the chat in Finder and Explorer. Those not in the backup are counted, not saved. It runs in the background; a **Show folder** button appears when it's done.
- A group shown for some people only (M5): the Media tab and Save all have only their attachments.
- "Original date" is when the message was sent, not when the file was last changed on the iPhone (a photo's own date inside the file, if it has one, is kept as it is).
- In the phone window, every read from the backup (thumbnails, the large view, Save all) goes through the backup's lock, and nothing is read once the window has closed the backup.
