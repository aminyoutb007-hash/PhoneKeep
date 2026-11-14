# 13. Phone health and clean-up

Two areas that help the owner keep the iPhone fast, roomy and safe: **Photo clean-up** (C) and the **Phone check-up** (H). They come after all of P1 (see [02-roadmap.md](02-roadmap.md)).

## Ground rules for this area

These add to [01-principles.md](01-principles.md); they never relax it.

- **Save before removing.** Nothing is removed from the phone until a verified copy is on the computer (checked by size and checksum) and the owner has confirmed the removal. The confirmation names the number of items and the space freed. Removals go through `phone_write.py` and the activity log (S7).
- **Only promise what iOS allows.** A computer cannot change most iPhone settings or remove most data. Where PhoneKeep can't make a change itself, it shows the exact steps on the phone ("Settings → General → iPhone Storage → Offload Unused Apps") with the space or benefit it brings. That counts as a finished feature, not a gap.
- **No fake boosters.** No "RAM cleaner", "speed booster", "battery saver" or "junk cleaner" that runs on the computer. iOS manages memory and background activity itself; claiming otherwise is dishonest (see the out-of-scope list in [12-engineering.md](12-engineering.md#out-of-scope-do-not-build-without-written-agreement)).
- **Honest wording.** Results say what was checked and what was found, never more: "No signs of known spyware found", not "Your phone is safe"; "about 6 GB", not "6.21 GB", when the figure is PhoneKeep's own estimate.
- **Everything is worked out on the computer, offline.** Photo analysis, scores and history stay on the computer next to the backups. No network use beyond the opt-in actions in S3.

## H1. Check-up screen

**What the user sees and does:** in the phone window, a **Check-up** icon (it replaces the separate "Battery & storage" and "Security check" icons in the screen map). It opens four cards side by side: **Storage**, **Battery**, **Stability**, **Security**. Each card is green, amber or red with one line saying why ("Amber: 91% full. Free about 14 GB below") and a **See details** button. At the top, a single line sums it up: "2 things need attention".

A **Why is my phone slow?** button gives one plain answer drawn from all four cards, most likely cause first ("Your storage is 96% full and your battery is at 78%. Both slow an iPhone down. Start with Storage").

The check-up runs by itself after every backup (it reads data the backup already collected, so it adds no waiting). When a card turns red, the menu bar helper (E2) shows a small dot and one notification ("Amin's iPhone: storage almost full"), at most once per problem.

**Requirements**
- Thresholds (tunable in one table in the code, not scattered):

| Card | Amber | Red |
| --- | --- | --- |
| Storage | 85% full or more | 95% full or more |
| Battery | Health below 85%, or dropped 5 points in 3 months | Health below 80%, or the phone reports the battery needs service |
| Stability | An app crashed 3+ times in 7 days | An app crashed 10+ times in 7 days, or the phone restarted unexpectedly |
| Security | iOS out of date; an app from outside the App Store | No passcode; an unknown configuration profile or device management; signs of a jailbreak; a spyware indicator matched |

- Works offline from the latest snapshot when the phone isn't connected, with "As of last backup, 3 Nov" on each card.

**Done when**
- [x] With the test fixtures, each card shows green, amber and red at the thresholds above, with the matching one-line reason. *(14 Nov, `tests/test_h1_checkup.py`: every boundary. On a real iPhone Storage and Battery come from the phone; Stability and Security say "Not checked yet" until H4 and H5 read their data.)*
- [x] "Why is my phone slow?" names the red and amber causes in order of impact. *(14 Nov, `tests/test_h1_checkup.py`: reds before ambers, then Storage, Battery, Stability; Security is named separately.)*
- [x] A red card produces exactly one helper notification, and none again until it changes. *(14 Nov, `tests/test_h1_checkup.py`: the helper backs up a stub iPhone six times; storage turning red notifies once, staying red doesn't, red again after it was fixed does.)*
- [x] Opening the check-up adds less than 1 second to the phone window. *(14 Nov, `tools/real_check.py` on a real iPhone: 3 ms. The read after each backup takes about 0.3 s.)*

## H2. Storage card and clean-up suggestions

Builds on V3 (storage usage) and Q4 (storage map).

**What the user sees and does:** the Storage card's details show the V3 bar, then a list of **suggestions, biggest saving first**, each with the space it frees and one action:

| Suggestion | Action |
| --- | --- |
| "Videos already saved on this computer: 12 GB" | **Review** (opens C1 on Large videos) |
| "Photo clean-up: about 4 GB" | **Review** (opens C1) |
| "WhatsApp media: 6 GB in 3 chats" | Steps on the phone: WhatsApp → Settings → Storage and Data → Manage Storage. Lists the 5 chats with most media, and confirms they are saved in the archive |
| "Message attachments: 3 GB" | Steps on the phone: Settings → General → iPhone Storage → Messages → Review Large Attachments |
| "Large apps: 20 largest with sizes" | Steps: Offload or delete in Settings → General → iPhone Storage |
| "Downloaded music: 3 GB" | Steps in the Music app |

A **storage forecast** sits under the bar when there are at least 4 snapshots: "At this rate the iPhone will be full in about 3 months".

**Requirements**
- App sizes come from the phone's app list (app plus its data). Chat media and attachment sizes come from the backup. All estimates say "about".
- A suggestion appears only when it frees at least 500 MB.
- The forecast uses used-space figures from past snapshots (B3) and is hidden when the trend is flat or falling.

**Done when**
- [x] Suggestions are listed largest first, each with a size and either a working button or exact steps. *(14 Nov, `tests/test_h2_storage.py`, and `tools/real_check.py` on a real iPhone. The two suggestions that open C1 come with C1.)*
- [ ] On a real iPhone, following the WhatsApp and Messages steps frees roughly the space shown (within 20%). *(Owner's check, still to do. It needs a phone with 500 MB or more of WhatsApp media or Messages attachments; below that the suggestions don't appear.)*
- [x] The forecast appears with 4+ snapshots of rising use, and not otherwise. *(14 Nov, `tests/test_h2_storage.py`: 3 backups, flat, falling and years away show none. It uses the used space each backup records since H1.)*

## H3. Battery card and battery history

Builds on V2 (battery health).

**What the user sees and does:** the Battery card shows today's health, cycles and charge (V2), plus a **chart of battery health over time**: one point per backup. The iPhone itself only shows today's figure, so this is something new. Plain-language notes under the chart: "Health dropped 4 points in 3 months, normal for 300 cycles" or "Below 80%: Apple usually recommends a battery replacement at this point".

A short **Tips for this iPhone** list, only the ones that apply: turn on Optimised Charging; use the 80% charge limit (on models that have it); avoid charging in heat (shown when the phone reported a high temperature at a backup); which apps to limit in Background App Refresh (the largest background users, where the phone reports them).

**Requirements**
- Each backup records date, health %, cycle count, full-charge and design capacity, and temperature (when reported) in a small local history file per phone. This is not personal data, but it stays on the computer like everything else.
- The chart needs 2+ points; with fewer it says "The chart fills in as PhoneKeep backs up".
- **Save details** exports the history as CSV, as well as V2's JSON.

**Done when**
- [ ] After three backups, the chart shows three points that match the phone's Settings → Battery at each time (within 1%).
- [ ] Tips that don't apply to the model or situation are not shown.

## H4. Stability card

**What the user sees and does:** the Stability card lists apps that crashed in the last 7 days, most crashes first: "Instagram crashed 14 times this week. Update it in the App Store; if it keeps crashing, delete and reinstall it." It also notes unexpected restarts of the phone. When there's nothing to report: "No app crashes in the last 7 days".

**Requirements**
- Reads the phone's crash reports (read-only: PhoneKeep never deletes them from the phone), groups them by app and day, and shows app names, not bundle IDs.
- Raw reports stay on the computer; **Save reports** zips them for anyone helping the owner (Apple Support, the app's maker).
- No memory or "RAM" figures: iOS manages memory itself and a figure would invite the owner to act on something they can't change.

**Done when**
- [ ] With seeded crash reports, the card lists the right apps and counts, and a seeded unexpected restart shows as red.
- [ ] After a check, the crash reports are still on the phone.

## H5. Security card

Includes S5 (spyware check), which becomes one part of this card. It is a **security check**, not antivirus: it says exactly what it looked at.

**What the user sees and does:** the Security card lists each check with a tick or a warning, and what to do about any warning:

| Check | Warning and advice |
| --- | --- |
| Passcode | "No passcode set. Anyone holding the phone can open it. Set one in Settings → Face ID & Passcode." |
| iOS version | "iOS is out of date. Updates fix security problems. Settings → General → Software Update." |
| Configuration profiles and device management | Names each profile or management server and who installed it, with "If you don't recognise this, remove it in Settings → General → VPN & Device Management". |
| Apps from outside the App Store | Names each app and how it was installed |
| Signs of a jailbreak | Names what was found and what a jailbreak means for security |
| Spyware check (S5) | As in [04-security.md](04-security.md#s5-spyware-check): run on request with **Check now** |

When anything serious is found, the card also explains Lockdown Mode (what it is, who it's for, where to turn it on) and links to help organisations.

**Requirements**
- Every check is read-only. PhoneKeep never removes profiles or apps (company device management stays out of scope); it only reports them.
- "Out of date" compares the phone's iOS with a small list shipped with each PhoneKeep release, labelled with its date ("Latest iOS known to PhoneKeep: 27.2, 1 Nov 2026"). The opt-in update check in S3 may refresh this list in the same request; nothing else goes online.
- The overall result never says "safe": green means "No problems found in these checks".

**Done when**
- [ ] With test fixtures, each check produces its warning: no passcode, an unknown profile, an app from outside the App Store, jailbreak signs, an old iOS version.
- [ ] A clean fixture shows all ticks and the wording "No problems found in these checks".
- [ ] No check writes anything to the phone (verified by the phone-write gate's log).

## C1. Photo clean-up: find and save

**What the user sees and does:** in Photos, a **Clean up** button opens one screen of cards, each with a count and the space it would free:

| Card | Finds | Suggested |
| --- | --- | --- |
| **Duplicates** | Exact copies, including the same photo saved twice from a chat | Keep one (the original with the most information kept) |
| **Similar shots** | Bursts and runs of near-identical photos taken seconds apart | Keep the sharpest; owner ticks which others go |
| **Poor quality** | Blurry, very dark or overexposed photos, accidental pocket shots, finger over the lens | Review one by one |
| **Old screenshots** | Screenshots and screen recordings older than 30 days (the age is adjustable) | Remove in bulk |
| **Large videos** | Biggest videos first, with size and length | Save to the computer, then remove |
| **Chat clutter** | Images saved into the camera roll from WhatsApp and other chat apps (memes, forwards) | Remove in bulk |

Inside a card, items are shown in groups (for Duplicates and Similar shots: the group side by side, the suggested keeper marked **Keep**). Every pick can be changed with one click. Space previews (Q1).

The final button reads **Save to computer and remove (412 items, 8.4 GB)**. While C2 isn't available, or iCloud Photos is on, it reads **Save to computer**, followed by the steps to remove them on the phone (C2).

A summary follows: "Saved 1,212 items to your archive. Freed 8.4 GB."

**Requirements**
- All analysis runs on the computer from the photos PhoneKeep already copies (live or from the backup), and is cached so a second visit is instant. Nothing is sent anywhere.
- Exact duplicates by checksum; similar shots by a visual fingerprint plus time taken; quality by sharpness and exposure scores. Screenshots, screen recordings, bursts and the app that saved an image come from the iPhone's own Photos library data in the backup where it records them; otherwise from file details.
- Suggested keepers prefer: the sharpest, then the largest, then the one with location and date intact, then favourites. Favourites and photos in any album are never suggested for removal.
- Live Photos and edited photos are handled as one item (photo, video part and edits together).
- Every item is in the archive, verified, before it can be offered for removal.

**Done when**
- [ ] On the rich photo fixture extended with seeded duplicates, near-duplicates, blurred, dark, screenshot and chat-saved images, each card finds what was seeded and nothing else (no favourites, no album photos).
- [ ] 10,000 photos are analysed in under 5 minutes on an Apple Silicon Mac; a second visit opens in under 2 seconds.
- [ ] Every item offered for removal is present in the archive with a matching checksum.

## C2. Remove cleaned-up photos from the iPhone

**Start with a spike.** Apple gives computers only a limited way to delete photos: its own Image Capture app can delete photos from an iPhone when **iCloud Photos is off**. Before building, the developer tests whether PhoneKeep can use the same route safely (the photo disappears cleanly from the Photos app, with no blank thumbnails, and Live Photos and edits go together), and reports back. C2 is built only after the owner agrees on the result.

**What the user sees and does (if the spike succeeds):** after **Save to computer and remove**, a confirmation: "Remove 412 items (8.4 GB) from Amin's iPhone? They are saved in your archive. They go to Recently Deleted on the iPhone if it supports that; otherwise they are removed straight away." **Remove** / **Cancel**.

**When iCloud Photos is on, or the route isn't safe:** PhoneKeep doesn't delete. It shows the steps instead, matched to the card: Duplicates → "Photos → Utilities → Duplicates → Merge"; Screenshots → "Photos → Media Types → Screenshots"; and for everything else a list of dates to find them. It warns clearly that with iCloud Photos on, deleting on the phone also deletes from iCloud and every other device.

**Requirements**
- Goes through `phone_write.py`, with the confirmation and an activity log entry (S7) per removal batch.
- Removes only items that were verified in the archive in the same session.

**Done when**
- [ ] (After the spike) Removed items disappear from the iPhone's Photos app with no leftovers, and every one is present in the archive.
- [ ] With iCloud Photos on, PhoneKeep offers only the on-phone steps and the warning.

## Later ideas (P3, only when asked)

- **C3. Duplicate contacts.** Find duplicates in the backup's contacts and point to the iPhone's own merge (Contacts → Duplicates Found). Read-only.
- **H6. Family check-ups.** With several phones (E5), one line per phone on the home screen: "Mum's iPhone: no backup for 9 days · storage 97% full".
- **H7. Selling or passing on an iPhone.** A guided checklist: final verified backup, then the steps on the phone to sign out, turn off Find My, move the eSIM and erase. PhoneKeep ticks what it can check.
- **H8. Monthly health summary.** A one-page PDF saved in the archive each month: backups made, storage and battery trends, problems found and fixed.
