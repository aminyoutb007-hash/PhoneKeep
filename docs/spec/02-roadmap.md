# 02. Roadmap

Every feature in one list. **Work P1 first, top to bottom, then P2. P3 only when asked.** Update the Status column in the same pull request that changes it.

Status: **Done** (works, keep it working) · **Partial** (some of it exists; finish the rest) · **To build** · **Out of scope** (see [12-engineering.md](12-engineering.md)).

P1 ships as two releases so features can be tested in batches: **5.0** then **5.1**. Within each release, work top to bottom. The version number stays at the last release until the release pull request; test builds carry a label such as `5.0-dev+B3` (see [12-engineering.md](12-engineering.md#build-and-release)).

## P1: must have

### Release 5.0

| ID | Feature | Today | Status | Details |
| --- | --- | --- | --- | --- |
| X0 | Tests in CI, test builds from every pull request, agreed spec changes | Tests not in the repo; installers built by hand | Done | [12-engineering.md](12-engineering.md#tests) |
| S1 | Encrypted backups by default, password in the keychain | Encrypted by default; password in the keychain, never typed twice | Done | [04-security.md](04-security.md#s1-encryption-by-default-and-the-keychain) |
| S3 | No network connections | Refused by the app itself; shown in Settings; opt-in update check only | Done | [04-security.md](04-security.md#s3-no-network) |
| E3 | Plain-language errors | One table; inline banner with a button; Show details | Done | [05-ease-of-use.md](05-ease-of-use.md#e3-plain-language-errors) |
| E1 | First-run guide | Five steps in the main window; 2 clicks + password to a backup | Done | [05-ease-of-use.md](05-ease-of-use.md#e1-first-run-guide) |
| B1 | Back up by cable and Wi-Fi | Works; only changes after the first run | Done | [03-backup.md](03-backup.md#b1-back-up-by-cable-and-wi-fi) |
| E2 | Menu bar / system tray helper | Menu, Back up now, notifications, progress ring, start at login | Done | [05-ease-of-use.md](05-ease-of-use.md#e2-menu-bar-and-system-tray-helper) |
| B2 | Scheduled automatic backups (needs E2) | Daily / Weekly at a time, only when charging; from the helper | Done | [03-backup.md](03-backup.md#b2-scheduled-automatic-backups) |
| B3 | Snapshots over time | Content store; timeline; keep forever / rename / delete; keep N or until 90% full | Done | [03-backup.md](03-backup.md#b3-snapshots-over-time) |
| B4 | Backups on any drive or NAS; move backups | Location screen; verified move; space warning; waits for an unplugged drive | Done | [03-backup.md](03-backup.md#b4-backup-location-and-moving-backups) |
| X2 | Backup redaction tool (for the regression library; before B5) | tools/redact_backup.py with a report | Done | [12-engineering.md](12-engineering.md#x2-backup-redaction-tool) |
| B5 | Open any backup and browse its files | File → Open backup…, drop a folder, Finder/iTunes backups listed, All files screen | Done | [03-backup.md](03-backup.md#b5-open-any-backup-and-browse-its-files) |
| M1 | Browse Messages (iMessage, SMS) | Works | Done | [06-messages.md](06-messages.md#m1-browse-messages) |
| M2 | Browse WhatsApp and WhatsApp Business | Works | Done | [06-messages.md](06-messages.md#m2-browse-whatsapp-and-whatsapp-business) |
| M3 | Chats to PDF and print (moved from 5.1 on 12 Nov: usability task 3 asks for a PDF) | PDF per chat or combined, phone-like bubbles, photos, emoji, Arabic; Print opens the system dialog | Done | [06-messages.md](06-messages.md#m3-chats-to-pdf-and-print) |

### Release 5.1

| ID | Feature | Today | Status | Details |
| --- | --- | --- | --- | --- |
| S2 | App lock (Touch ID / password) | Not available | To build | [04-security.md](04-security.md#s2-app-lock) |
| P1 | Photos: albums, preview, HEIC to JPG | By month, live, originals | Partial | [07-photos-media.md](07-photos-media.md#p1-photos) |
| D9 | Export everything with one date range and search | Everything preset; dates for chats only | Partial | [08-personal-data.md](08-personal-data.md#d9-export-everything) |
| V1 | Device overview | Name, iOS, connection | Partial | [10-device.md](10-device.md#v1-device-overview) |
| V2 | Battery health | Not available | To build | [10-device.md](10-device.md#v2-battery-health) |
| V3 | Storage usage | Not available | To build | [10-device.md](10-device.md#v3-storage-usage) |
| Q1 | Quick previews (Space key) everywhere | Partly (double-click opens) | Partial | [11-previews.md](11-previews.md#q1-quick-preview-everywhere) |
| S4 | Signed and notarised installers (last: needs the certificates) | Ad-hoc signed; users must click Open Anyway. Workflow signs when the secrets exist | Partial | [04-security.md](04-security.md#s4-signed-and-notarised-installers) |

## P2: should have

| ID | Feature | Today | Status | Details |
| --- | --- | --- | --- | --- |
| S5 | Spyware check (moved from P1 pending the MVT licence check) | Not available | To build | [04-security.md](04-security.md#s5-spyware-check) |
| S6 | Encrypted exports | Not available | To build | [04-security.md](04-security.md#s6-encrypted-exports) |
| S7 | Activity log | Not available | To build | [04-security.md](04-security.md#s7-activity-log) |
| S8 | Tamper check for backups | Not available | To build | [04-security.md](04-security.md#s8-tamper-check) |
| B6 | Restore a backup to an iPhone | Not available | To build | [03-backup.md](03-backup.md#b6-restore-a-backup-to-an-iphone) |
| E4 | One search across the whole phone | Per-screen search only | Partial | [05-ease-of-use.md](05-ease-of-use.md#e4-one-search-across-the-phone) |
| E5 | All phones and backups in one list | One phone at a time | Partial | [05-ease-of-use.md](05-ease-of-use.md#e5-all-phones-and-backups-in-one-list) |
| E6 | Dark mode | Light only | To build | [05-ease-of-use.md](05-ease-of-use.md#e6-dark-mode) |
| E7 | Fast with very large phones | Lists slow above ~20,000 items | Partial | [05-ease-of-use.md](05-ease-of-use.md#e7-fast-with-very-large-phones) |
| M4 | Full detail in Excel and CSV | Basic columns | Partial | [06-messages.md](06-messages.md#m4-full-detail-in-excel-and-csv) |
| M5 | Show one person in a group chat | Not available | To build | [06-messages.md](06-messages.md#m5-show-one-person-in-a-group-chat) |
| M6 | Media viewer for chat attachments | Thumbnails only | Partial | [06-messages.md](06-messages.md#m6-media-viewer-for-chat-attachments) |
| P2 | Music export with tags and artwork | Files saved without tags | Partial | [07-photos-media.md](07-photos-media.md#p2-music) |
| P8 | Video conversion HEVC to H.264 when saving "Most compatible" (moved from P1) | Videos saved as originals | To build | [07-photos-media.md](07-photos-media.md#p8-video-conversion) |
| P3 | Books: filter books and PDFs | Open and save | Done | [07-photos-media.md](07-photos-media.md#p3-books-and-pdfs) |
| D1 | Contacts: groups, photos, links | Table and exports | Partial | [08-personal-data.md](08-personal-data.md#d1-contacts) |
| D4 | Notes: folders, attachments, PDF | Text only | Partial | [08-personal-data.md](08-personal-data.md#d4-notes) |
| D6 | Call recordings | Not available | To build | [08-personal-data.md](08-personal-data.md#d6-call-recordings) |
| F1 | App documents: browse and save | Works | Done | [09-files-apps.md](09-files-apps.md#f1-app-documents) |
| F2 | Drag files into iPhone apps | Not available | To build | [09-files-apps.md](09-files-apps.md#f2-drag-files-into-iphone-apps) |
| F3 | File search with wildcards | Not available | To build | [09-files-apps.md](09-files-apps.md#f3-file-search) |
| F4 | App list with names, icons and data export | App IDs only | Partial | [09-files-apps.md](09-files-apps.md#f4-apps-and-their-data) |
| Q2 | Chats with voice-note waveforms | Not available | To build | [11-previews.md](11-previews.md#q2-chats-as-on-the-phone) |
| Q3 | Contact cards with everything about a person | Not available | To build | [11-previews.md](11-previews.md#q3-contact-cards) |
| Q4 | Storage map | Not available | To build | [11-previews.md](11-previews.md#q4-storage-map) |
| Q5 | Backup timeline slider | Not available | To build | [11-previews.md](11-previews.md#q5-backup-timeline) |

## P3: later, only when asked

| ID | Feature | Today | Status | Details |
| --- | --- | --- | --- | --- |
| B7 | Restore while leaving some data out | Not available | To build | [03-backup.md](03-backup.md#b7-restore-while-leaving-some-data-out) |
| S9 | Secure delete | Not available | To build | [04-security.md](04-security.md#s9-secure-delete) |
| E8 | Languages: French and Arabic | English only | To build | [05-ease-of-use.md](05-ease-of-use.md#e8-languages-and-accessibility) |
| P4 | Copy photos to the iPhone | Not available | To build | [07-photos-media.md](07-photos-media.md#p4-copy-photos-and-music-to-the-iphone) |
| P5 | Copy music to the iPhone | Not available | To build | [07-photos-media.md](07-photos-media.md#p4-copy-photos-and-music-to-the-iphone) |
| P6 | Ringtones | Not available | To build | [07-photos-media.md](07-photos-media.md#p6-ringtones) |
| P7 | Voice Memos date filter | Play and save work | Done | [07-photos-media.md](07-photos-media.md#p7-voice-memos) |
| D2 | Copy contacts to the iPhone | Not available | To build | [08-personal-data.md](08-personal-data.md#d2-copy-contacts-to-the-iphone) |
| D3 | Calendars | Works | Done | [08-personal-data.md](08-personal-data.md#d3-calendars) |
| D5 | Call history: total time, SIM | Works | Done | [08-personal-data.md](08-personal-data.md#d5-call-history) |
| D7 | Voicemail | Works | Done | [08-personal-data.md](08-personal-data.md#d7-voicemail) |
| D8 | Safari | Works | Done | [08-personal-data.md](08-personal-data.md#d8-safari) |
| V4 | Move data to a new iPhone | Not available | To build | [10-device.md](10-device.md#v4-move-to-a-new-iphone) |
| V5 | Screenshots of the phone | Not available | To build | [10-device.md](10-device.md#v5-screenshots) |
| Q6 | Photo map and "on this day" | Not available | To build | [11-previews.md](11-previews.md#q6-photo-extras) |
| X1 | Command line for every feature | Main features only | Partial | [12-engineering.md](12-engineering.md#command-line) |
