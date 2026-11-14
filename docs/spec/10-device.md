# 10. The phone itself

## V1. Device overview

**What the user sees and does:** under the phone picture in the phone window: model name ("iPhone 17 Pro Max"), colour, iOS version, capacity and free space (a bar), serial number (click to copy), battery health (V2), last backup and the lock badge.

**Done when**
- [ ] Every value matches the iPhone's Settings → General → About. *(14 Nov, owner's iPhone 14 Pro Max: model, iOS, capacity and serial match. Colour: the phone reports a code (DeviceEnclosureColor); codes are named once checked on a real phone, starting with this one.)*

## V2. Battery health

**What the user sees and does:** a battery card: health % with a short explanation ("Good: holds 91% of its original charge"), charge cycles, current charge, and temperature when the iPhone reports it (the row is hidden when it doesn't). **Save details** saves the diagnostics as JSON.

Battery history over time and tips: H3 in [13-phone-health.md](13-phone-health.md#h3-battery-card-and-battery-history).

**Done when**
- [x] Health % matches Settings → Battery on the phone (within 1%). *(14 Nov, owner's iPhone: matches.)*

## V3. Storage usage

**What the user sees and does:** a ring or bar showing space used by Photos, Apps, Messages, System and Free, and a list of the 20 largest apps with sizes. Clicking Photos or Messages opens those screens sorted by size, with tips ("Large videos: 12 GB, save them to your computer to free space").

**Requirements**
- Total, used and free come from the phone itself and are exact.
- The per-category figures (Photos, Apps, Messages, System) are PhoneKeep's own sums from the backup and the app list; the phone doesn't share its own accounting. They are labelled "about" ("Photos · about 48 GB").

Clean-up suggestions and the storage forecast: H2 in [13-phone-health.md](13-phone-health.md#h2-storage-card-and-clean-up-suggestions).

**Done when**
- [x] Total, used and free are within 1% of Settings → General → iPhone Storage. *(14 Nov, owner's iPhone: match.)*
- [ ] Each category is shown with "about" and the 20 largest apps match the phone's list in order.

## V4. Move to a new iPhone

**P3.** Pick the old phone's snapshot and the new phone, choose what to bring (all, or by kind), confirm, restore (uses B6).

## V5. Screenshots

**P3.** **Take screenshot** in the phone window saves a PNG of the phone's screen (needs Developer Mode on the phone; explain how to turn it on if it's off).
