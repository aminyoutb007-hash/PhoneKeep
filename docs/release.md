# Release checklist

Copy this list into the release pull request ("Release 5.0") and tick each line. A release ships only when every line is ticked. The rules behind each line are in [spec/README.md](spec/README.md) (definition of done) and [spec/12-engineering.md](spec/12-engineering.md) (build and release).

## Before the release pull request

- [ ] Every feature planned for this release is **Done** in [spec/02-roadmap.md](spec/02-roadmap.md); nothing is partly done.
- [ ] `tests/run_all.py` passes on Mac and Windows in GitHub Actions on the release branch.
- [ ] **Usability test** ([spec/00-user-experience.md](spec/00-user-experience.md)): five people, five tasks, 4 of 5 pass each task without help. Times and hesitations noted; notes attached to the pull request.
- [ ] **Five journeys** timed on a fresh install with a real iPhone; none slower or longer than the last release (table attached).
- [ ] **Speed targets** checked with the large test backup (300,000 messages / 50,000 photos) on a base-model Mac.
- [ ] **Network check on a real Mac:** a full backup, an export and a phone-window session under an OS-level network monitor (e.g. Little Snitch or `nettop`) show zero outbound internet connections (S3).
- [ ] **Visual check on a real Mac:** screenshots of every screen in light and dark mode, at 100% and 200% scaling, attached; nothing drawn wrong (see [spec/01-principles.md](spec/01-principles.md), Design).
- [ ] Windows: every screen checked once at 100% and 200% scaling.
- [ ] The README's user section describes every new feature in one or two plain sentences.

## The release pull request

- [ ] Version bumped in all three places: `phonekeep.py` (`VERSION`), `packaging/PhoneKeep.spec`, `packaging/PhoneKeep.iss`.
- [ ] `packaging/next-release.txt` set to the release after this one.
- [ ] Release notes written in plain words: what's new, what to do after updating, known limits.
- [ ] If the certificates exist (S4): the run summary says `signing: developer-id · notarised: yes` and `signed: yes`; a fresh Mac opens the app with no Gatekeeper warning; Windows shows the publisher name.
- [ ] If they don't yet: the release notes say the installers are unsigned and how to open them.

## After merging

- [ ] Tag `vX.Y.Z` pushed; the "Build installers" run publishes the GitHub Release with installers and SHA-256 checksums.
- [ ] Each installer downloaded from the Release page, its checksum compared with the notes, installed on a clean Mac and a clean Windows PC, and a first backup made.
- [ ] The About box shows the release version with no build label.
