# 08. Personal data

## D1. Contacts

**What the user sees and does:** a contacts list with photos and initials; groups in a sidebar with counts; clicking shows a contact card (Q3) with clickable phone, email and address. Save as vCard, Excel or CSV.

**Requirements:** when saving vCards into a folder that already has one with the same name: "Keep both / Replace / Skip".

**Done when**
- [ ] Contact photos and groups match the phone; a saved .vcf imports into Contacts / Outlook with photos. *(17 Nov: built and checked on invented data and on the owner's real backup; the import into Contacts on a Mac and into Outlook is the owner's to try: PhoneKeep never drives another app. `tests/test_d1_contacts.py` checks it all on an invented backup. On the owner's real backup, `tools/real_check.py` counts the contacts, the Lists and the pictures straight from the phone's own address book databases. The Contacts screen matches all three, and a vCard of everything has every contact and every photo as a JPEG. The owner's phone has no groups, so its Lists are its accounts.)*

**How it's built (17 Nov):**
- The phone keeps one person who's in two accounts (say iCloud and Gmail) as two linked cards. PhoneKeep shows them as one contact, as the phone does: the name and photo are the ones the phone prefers, and a number, email or address in both cards shows once. Before D1 such a person was listed twice.
- **Lists** in the sidebar are the phone's: All contacts, then every account (when there's more than one) as "All <account>", then every group, each with its count. A click shows only that list.
- **Photos** are the phone's own pictures in the backup (AddressBookImages): the biggest thumbnail up to 640 px, which the phone has already cropped, or the full-size picture cropped where the phone crops it when there's no thumbnail. They're read once, when Contacts is first opened, not when the backup opens. A contact without one shows their initials.
- **Decided: a photo kept only as a link on the internet is never fetched.** Nothing leaves the computer.
- **Decided: a click on a number, email, address or website copies it, nothing more.** No call, no email, no map: a map would send the address to the internet.
- **Save as vCard** (3.0, what Contacts on a Mac, Outlook, Google and Android import) saves the selected contacts, or everything shown. It's one file, named after the contact, the list shown, or "Contacts". Each card has its photo (a JPEG up to 512 px), addresses, websites, birthday, note and groups (CATEGORIES). A label the owner typed is kept the way Apple's own vCards keep it (X-ABLabel), and lines are folded at 75 bytes. **Excel** and **CSV** have Name, Phone, Email, Address, Website, Company, Lists, Birthday and Note, as text that can't become a formula. The web export's contacts.vcf and contacts.csv are the same.
- The whole-phone search (E4) also finds a contact by their address or website.

## D2. Copy contacts to the iPhone

**P3. Writes to the phone.** Import a .vcf onto the phone after confirmation; duplicates detected by name + phone number and offered as "Merge / Keep both / Skip".

## D3. Calendars

**Status: Done (table, Excel, CSV, .ics).** Keep working. Add the standard date filter and a calendar picker.

## D4. Notes

**What the user sees and does:** a sidebar of folders (with Pinned and Recently Deleted), a list of notes, and the note shown as on the phone: headings, lists, checklists, tables, images and attachments. Locked notes show a lock and "Locked on your iPhone". Save one or many as PDF (with images) or text.

**Done when**
- [ ] A note with a table, a checklist and two images looks the same as on the phone and in its PDF. *(17 Nov: built; on invented data, `tests/test_d4_notes.py` checks a note with a table, a checklist and two images in the Notes screen, in its PDF and as text, against a NoteStore.sqlite written the way iOS writes it. On the owner's real backup, `tools/real_check.py` reads every note's body, finds every attachment in the Notes database with its file, draws every picture in the Notes screen and makes a PDF of every note with the same pictures. The owner's notes have checklists and pictures but no table, so a real table, and a look side by side with the phone, are still to do.)*

**How it's built (17 Nov):**
- **The body** is the phone's own: Notes keeps it as gzipped protobuf, the text with "runs" over it, each with a length (in UTF-16 units, so an emoji counts as two) and its style. PhoneKeep reads the paragraph styles (title, heading, subheading, monospaced, bulleted, dashed and numbered lists, checklists with their ticks, indents) and the text styles (bold, italic, underline, strikethrough, links). `notes_doc.py`, field numbers as in the published layout the open-source apple_cloud_notes_parser uses. A body it can't read is shown as plain text, as before.
- **Attachments** are found by identifier in NoteStore.sqlite and their files under the Notes folder of the backup: a photo's file (Media), a drawing's picture (FallbackImages), a scanned document's PDF (FallbackPDFs) and its preview picture (Previews). A gallery of scanned pages shows its pages in the gallery's own order. One whose file isn't in the backup says so.
- **Tables** are Apple's "mergeable data" (a CRDT): the rows and columns in the table's own order, each cell's text. Cells moved by an edit on the phone stay in their place.
- **The Notes screen:** the phone's folders on the left (All notes, Pinned, each folder, a folder inside a folder as "Home › Garden", Recently Deleted last), the notes of the one chosen (pinned first), and the note drawn as on the phone: headings, checkboxes (☐ ☑), list marks, images, drawings and scanned pages in the note, tables as a grid, and audio, video, PDFs and other files as a line that opens them in the viewer (Q1). A locked note shows a lock and "Locked on your iPhone": its body is encrypted with the owner's Notes password, which PhoneKeep never asks for.
- **Decided: a link in a note is shown, never opened.** Nothing leaves the computer.
- **Save:** this note as PDF or as text, the notes shown as one PDF (each note on its own page; a locked note left out), and Save all notes (the web export, now with checklists and tables in its text, plus one PDF of every note when PDF is chosen). The PDF has the same fonts, colour emoji, right-to-left Arabic and "Page N of M" as the chat PDFs (M3). Images are scaled in PhoneKeep's private temp folder, removed as soon as the PDF is made, and a PDF is written next to its name and then renamed, so a stopped save leaves nothing half-written.
- **Pictures load in the background:** a note's images, drawings and scanned pages are read and decoded on the window's backup reader, never on the screen's own thread, and each goes into the note when it's ready; one for a note no longer shown is dropped.
- **Damaged notes:** a body that can't be read (cut short, wrong field types, a far too deep indent, a varint over 10 bytes, or a blob that would unpack to more than 32 MB) shows as plain text, or as the phone's snippet; the other notes load as usual. Tables and galleries are read in one pass however big they are (UUIDs and pages looked up by dictionary, each table object and each column's cells read once, at most 100,000 cells; an attachment named twice in a note, or a page or gallery listed twice in the database, counts once), so a hostile one can't hold the backup.

## D5. Call history

**Status: Done.** Add total call time in the header, a SIM column on dual-SIM phones, and the standard date filter.

## D6. Call recordings

**What the user sees and does:** a **Call recordings** list (iOS 18 and later): who, when, length; Play; the transcript beside it when the phone made one; Save audio and transcript.

**Done when**
- [ ] A recorded call on a real phone appears with its audio and transcript.

## D7. Voicemail

**Status: Done.** Audio always saved as .m4a; details (from, number, date, length) saved to Excel alongside.

## D8. Safari

**Status: Done.** Bookmarks, history, open in the browser. Keep working.

## D9. Export everything

**What the user sees and does:** **Save everything…** in the phone window: one sheet with checkboxes for each kind of data, one date range, one optional search ("only things mentioning *Karim*"), the formats, and an estimated size. Saves into one folder with a contents page.

**Requirements**
- The date range and search apply to every kind of data that has dates or text.
- The contents page (web) links to every saved section and states the phone, snapshot date and filters used.

**Done when**
- [x] "Last 30 days, mentioning *invoice*" saves only matching messages, notes and files from those 30 days. *(Stand-in backup: `tests/test_d9_save_everything.py`. Real Mac, 15 Nov 2026: `tools/real_check.py` on the owner's latest backup saves exactly what it works out from the backup on its own, and every saved file and message mentions the word and is from the range. The literal run (last 30 days, *invoice*) kept matching files and left others out by date and by word; that backup had too little recent in messages and notes, so for those two the same check also runs over the fullest 30 days in the backup with a common word, and there too items were kept, others left out by the dates and others by the word.)*
