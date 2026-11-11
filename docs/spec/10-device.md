# 10. The phone itself

## V1. Device overview

**What the user sees and does:** under the phone picture in the phone window: model name ("iPhone 17 Pro Max"), colour, iOS version, capacity and free space (a bar), serial number (click to copy), battery health (V2), last backup and the lock badge.

**Done when**
- [ ] Every value matches the iPhone's Settings → General → About.

## V2. Battery health

**What the user sees and does:** a battery card: health % with a short explanation ("Good: holds 91% of its original charge"), charge cycles, current charge, temperature. **Save details** saves the diagnostics as JSON.

**Done when**
- [ ] Health % matches Settings → Battery on the phone (within 1%).

## V3. Storage usage

**What the user sees and does:** a ring or bar showing space used by Photos, Apps, Messages, System and Free, and a list of the 20 largest apps with sizes. Clicking Photos or Messages opens those screens sorted by size, with tips ("Large videos: 12 GB, save them to your computer to free space").

**Done when**
- [ ] Totals are within 5% of Settings → General → iPhone Storage.

## V4. Move to a new iPhone

**P3.** Pick the old phone's snapshot and the new phone, choose what to bring (all, or by kind), confirm, restore (uses B6).

## V5. Screenshots

**P3.** **Take screenshot** in the phone window saves a PNG of the phone's screen (needs Developer Mode on the phone; explain how to turn it on if it's off).
