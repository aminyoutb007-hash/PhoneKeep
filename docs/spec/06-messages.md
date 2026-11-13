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

**Done when**
- [ ] A chat with replies, reactions and an edited message shows all three in Excel.

## M5. Show one person in a group chat

**What the user sees and does:** in a group chat, a "People" button lists participants with message counts; ticking one or more shows only their messages. Save uses the same filter.

**Done when**
- [ ] Filtering a group to one person shows only their messages, in preview and in the saved Excel and PDF.

## M6. Media viewer for chat attachments

**What the user sees and does:** clicking a photo or video in a chat opens it large; arrow keys move through the chat's other media; a **Media** tab on each chat shows all its photos, videos, voice notes and documents in a grid with **Save all**.

**Done when**
- [ ] A chat's Media tab shows every attachment; Save all saves them with their original dates.
