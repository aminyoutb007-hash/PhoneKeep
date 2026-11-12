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

**Done when**
- [ ] A 2,000-message chat with photos produces a PDF in under 30 seconds that opens in Preview / Acrobat and prints correctly.
- [ ] Arabic, French and emoji render correctly.

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
