# PhoneKeep · Direction A ("Calm") mockups

Approved by Amin, 15 Nov 2026. All names and numbers in these mockups are invented ("Sam's iPhone", "Jordan Lee", sizes, counts).
They are a target, not pixel-exact: match the structure, spacing and colours in Tk using theme.py.

| File | Screen |
| --- | --- |
| Main.png / .html | Main window: phone card on the left (picture, name, Back up now, Open iPhone), "What do you want to keep?" on the right |
| Phone.png | Phone window: phone picture + snapshot picker on the left; three summary cards (This iPhone, Battery, Storage); app tiles in a 4-column grid with counts; search box |
| Photos.png | Photos: library/albums/years sidebar with counts, month heading, photo grid (cloud badge = only in iCloud, faded), selection bar at the bottom |
| Checkup.png | Check-up: one summary banner, four status cards (Storage, Battery, Stability, Security), "Why is my phone slow?" card |
| Chat.png | Chats: list with tick boxes and search on the left, conversation on the right, "Save as" + main button in the footer |
| Settings.png | Settings: left nav (Backups, Automatic backups, Security, Saving, Activity, About), sections as white cards |
| Backup.png | Backing up: one centred card with phone, big %, progress bar, time left, amber "Look at your iPhone" notice, step list, Cancel; "You can close this window" below |
| Welcome.png | First-run guide: steps 1–4 on the left (done / now / next), current step on the right; step 3 = backup password with strength and "Saved in your Keychain"; Skip for now / Back / main button |

## Tokens (already in theme.py)
Background #F5F5F7 · card #FFFFFF with 1px #E5E5EA border, radius 14–16 · text #1D1D1F · secondary #6E6E73 ·
accent #0F766E (hover #0B5A54) · pale accent #E8F5F2 (selected rows) · warning #9A5B00 on #FFF7E6 ·
main button = accent fill, white text, radius 10–12 · secondary button = white, #E5E5EA border.
Icons are simple line drawings; no emoji, no copies of Apple's or WhatsApp's icons.

## Notes
- Settings shows a "Lock PhoneKeep with Touch ID" switch and "Only while the iPhone is charging": these are design ideas, not built features. Ask Amin before adding them.
- The first-run guide's step 3 must not generate a password: the user types their own.
- Some mockup features (search box in the phone window, "Why is my phone slow?") may need small new code; keep them read-only.
