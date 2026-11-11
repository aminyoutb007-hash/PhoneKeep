# 07. Photos and media

## P1. Photos

**What the user sees and does:** a sidebar like the Photos app: **Library** (by month), **Favourites**, **Albums**, **Videos**, **Screenshots**, **Live Photos**, **Hidden** (asks for confirmation / app lock first). The grid shows square thumbnails; Space previews full size with arrows to move; Save asks "Original (HEIC) / Most compatible (JPG)".

**Requirements**
- Albums, favourites and media types read from the phone's Photos library database (live) or the backup.
- "Most compatible" converts HEIC to JPG and HEVC to H.264 MP4, keeping the date taken and location in the file, and the file date set to the date taken.
- Live Photos save as the photo plus its short video, same name.
- Thumbnails appear immediately as placeholders, then fill in; the grid stays smooth with 50,000 items.
- Never draw selection with see-through/stippled overlays (they render solid on macOS); use a frame and tick.

**Done when**
- [ ] Albums and favourites match the phone.
- [ ] A saved JPG shows the original date and location in Finder/Explorer and Photos.
- [ ] Usability test task 2 passes.

## P2. Music

**What the user sees and does:** songs stored on the phone listed by title, artist, album, length, with artwork; Play (Space); **Save** writes files into Artist/Album folders with tags and artwork.

**Done when**
- [ ] Saved songs show correct title, artist, album and artwork in Music / Windows Media Player.
- [ ] Songs that only stream (not on the phone) are not listed, and a note says why.

## P3. Books and PDFs

**Status: Done.** Add a filter: Books · PDFs · Audiobooks · All. EPUBs stored unpacked on the phone are saved as proper .epub files (already done; keep it).

## P4. Copy photos and music to the iPhone

**P3. Writes to the phone.** Drag photos or songs onto the phone window → confirmation "Add 24 photos to Photos on Amin's iPhone?" → they appear in the Photos / Music app with original dates and tags. Logged in the activity log.

## P6. Ringtones

**P3.** List and play ringtones on the phone; save them; make one from a song or voice memo (trim to 30 seconds, preview, then copy to the phone after confirmation).

## P7. Voice Memos

**Status: Done (play and save).** Add the standard date filter and a waveform preview (Q2).
