# PhoneKeep: instructions for the developer

PhoneKeep is a desktop app (Mac and Windows) that backs up an iPhone to the computer and lets the owner look through everything on it, safely and without effort. This folder is the full brief: what to build, in what order, and how we will know each piece is finished.

**Build exactly what these files describe.** If something is unclear, or you think a requirement is wrong, ask before building, not after.

## The two priorities

1. **Security.** The phone's data is private: it stays on the owner's computer, it is encrypted, and nothing touches the phone without the owner saying so.
2. **Ease of use.** Someone who has never used a backup app gets their first backup in two clicks and never needs a manual.

Previews and nice touches come third. A feature that weakens either priority does not ship.

## Files in this folder

| File | What it covers |
| --- | --- |
| [00-user-experience.md](00-user-experience.md) | **Read first.** Who it's for, how it should feel, the five journeys with targets, screen map, interaction patterns, speed targets, usability test |
| [01-principles.md](01-principles.md) | Rules every feature must follow (security, ease of use, wording, design) |
| [02-roadmap.md](02-roadmap.md) | Every feature with its ID, current status and priority. **Start here when choosing work.** |
| [03-backup.md](03-backup.md) | Backups, encryption, snapshots, storage, restore |
| [04-security.md](04-security.md) | App lock, keychain, no network, encrypted exports, tamper check, signing, spyware check |
| [05-ease-of-use.md](05-ease-of-use.md) | First-run guide, automatic backups, menu bar helper, errors, search, dark mode, languages |
| [06-messages.md](06-messages.md) | Messages (iMessage, SMS), WhatsApp, WhatsApp Business: browse, PDF, print, Excel, CSV |
| [07-photos-media.md](07-photos-media.md) | Photos, videos, music, books, ringtones, voice memos |
| [08-personal-data.md](08-personal-data.md) | Contacts, calendars, notes, call history, call recordings, voicemail, Safari, Export All |
| [09-files-apps.md](09-files-apps.md) | App documents, drag-and-drop transfer, file search, app data |
| [10-device.md](10-device.md) | Device overview, battery, storage, moving to a new iPhone, screenshots |
| [11-previews.md](11-previews.md) | Previews and nice touches |
| [12-engineering.md](12-engineering.md) | Code map, architecture, tests, pull requests, build and release, what is out of scope |
| [../release.md](../release.md) | The release checklist (copied into each release pull request) |

## How to work

1. Take features from [02-roadmap.md](02-roadmap.md) in priority order: all **P1** first, top to bottom, then **P2**. **P3** only when asked.
2. Read the feature's section in its area file. Every section has **What the user sees and does** (the experience, which comes first), **Requirements** (what it must do) and **Done when** (the checks that prove it).
3. One feature per pull request, named with its ID, e.g. `B3 Scheduled automatic backups`.
4. Update the Status column in [02-roadmap.md](02-roadmap.md) in the same pull request.

## Definition of done (applies to every feature)

A feature is done only when **all** of these are true:

- Every point under its **Done when** passes on a real iPhone running the current iOS, connected **by cable and by Wi-Fi**. On Mac, Wi-Fi is required. On Windows, Wi-Fi must either work or show the plain-language error from E3 saying why and what to do ("Connect once with a cable first", "Install the Apple Devices app"); a Wi-Fi failure on Windows doesn't block a feature, but a silent failure or an unexplained error does.
- It works on **macOS (Apple Silicon and Intel) and Windows**, unless the feature says one platform only.
- It has **automated tests** in the repository (see [12-engineering.md](12-engineering.md)), and all existing tests still pass.
- It follows every rule in [01-principles.md](01-principles.md) and the interaction patterns in [00-user-experience.md](00-user-experience.md).
- None of the five journeys in [00-user-experience.md](00-user-experience.md) got slower or longer.
- The installers build on GitHub Actions without errors, and the pull request links to that run and quotes the installer sizes.
- The README's user section describes it in one or two plain sentences.
- The pull request follows the layout in [12-engineering.md](12-engineering.md#pull-requests) (hardware it needs, on-device checklist, status block).

## Not to build

Some things are deliberately out of scope; the list is at the end of [12-engineering.md](12-engineering.md). Do not build them, or anything not in the roadmap, without written agreement.
