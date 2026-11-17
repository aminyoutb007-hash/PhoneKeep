# 07. Photos and media

## P1. Photos

**What the user sees and does:** a sidebar like the Photos app: **Library** (by month), **Favourites**, **Albums**, **Videos**, **Screenshots**, **Live Photos**, **Hidden** (asks for confirmation / app lock first). The grid shows square thumbnails; Space previews full size with arrows to move; Save asks "Original (HEIC) / Most compatible (JPG)".

**Requirements**
- Albums, favourites and media types read from the phone's Photos library database (live) or the backup.
- "Most compatible" converts HEIC photos to JPG, keeping the date taken and location in the file, and the file date set to the date taken. Videos are always saved as originals in P1 (on a Mac, P8 now converts HEVC videos to H.264 MP4).
- Live Photos save as the photo plus its short video, same name.
- Thumbnails appear immediately as placeholders, then fill in; the grid stays smooth with 50,000 items.
- Never draw selection with see-through/stippled overlays (they render solid on macOS); use a frame and tick.

**How it's built (5.1):** `library.py` reads the phone's Photos.sqlite (live over AFC, or from the backup), finding the tables and columns of each iOS version (ZASSET / ZGENERICASSET; the numbered album link table): favourite, hidden, Recently Deleted, photo/video, Live Photo, screenshot, date taken, location, user albums. The photo list (`ui.PhotoPanel`) shows **Favourites, Videos, Screenshots, Live Photos, Albums, 🔒 Hidden**, then the **Library** by year and month; each row can be ticked as a whole. Hidden photos are left out of everything else and **Hidden asks every time** (Touch ID / the computer's password when the app lock is on, otherwise a confirmation). Items in Recently Deleted aren't listed. `photoconv.py`: **Save** asks Original (HEIC) / Most compatible (JPG), remembered; the JPG keeps the EXIF (date taken, location, orientation, colour profile), fills date and location from the library when the photo lacks them, and its file date is the date taken; a Live Photo saves as the photo and its short video with the same name. Space-to-preview is Q1.

**Done when**
- [x] Albums and favourites match the phone. *(14 Nov, owner's check on a real iPhone with iCloud Photos.)*
- [x] A saved JPG shows the original date and location in Finder/Explorer and Photos. *(14 Nov, owner's check in Finder.)*
- [ ] Usability test task 2 passes.

## P8. Video conversion

**P2 (moved from P1).** "Most compatible" also converts HEVC videos to H.264 MP4, keeping date and location. (The plan was ffmpeg bundled in the installers, size and licence to be agreed first; the Mac needs none, see below.)

**How it's built (17 Nov, Mac):** no ffmpeg. On a Mac, `videoconv.py` runs `avconvert`, the command-line tool macOS ships in /usr/bin (Apple's own video encoder, run as a subprocess; no app is scripted and nothing is added to the installer), with its 4K H.264 preset, which never upscales: a 1080p or portrait video keeps its size. Only videos that are HEVC (read from the file: `hvc1`, `hev1`, and Dolby Vision HDR on HEVC) are converted; an H.264 video already plays everywhere and is saved as it is. `avconvert` doesn't keep the date taken or the location, so PhoneKeep writes them back into the new file: the date taken into the movie, track and media headers (what Windows shows as "Media created"), Apple's QuickTime keys for the date and the location (what macOS and Apple's Photos read; other keys already there are kept), and the location again as `©xyz` (ISO 6709). The file's own dates (and its "created" date on a Mac) are the date taken, as for photos. A Live Photo's short video is converted too and keeps the photo's name. The work happens on copies in PhoneKeep's private temp folder, one video at a time; the saved folder only ever gets a finished file, and a conversion that fails saves the original. The Save dialog says what happens to videos on this computer.

**Windows (decided by the owner later):** there is no encoder PhoneKeep can count on: Windows can only read these videos with Microsoft's paid HEVC extension, and bundling ffmpeg brings size and licence questions (H.264/HEVC patents, LGPL/GPL). Until the owner decides, Windows saves videos as they are and the Save dialog says so.

**Done when**
- [ ] A converted video plays in Windows Media Player and QuickTime with the original date. *(17 Nov: `tests/test_p8_video.py` converts a generated HEVC clip on a Mac and checks the H.264 MP4's date taken (in the movie, track and media headers, Apple's date key, and the file's dates), its location, that the picture data is still where the index points, and that macOS's own video framework reads the whole file back; `tools/real_check.py` does the same with one HEVC video with a location from the owner's iPhone, read-only. Still to do by hand: open a converted video in QuickTime Player and in Windows Media Player and look at the date. Windows itself doesn't convert yet: see above.)*

## P2. Music

**What the user sees and does:** songs stored on the phone listed by title, artist, album, length, with artwork; Play (Space); **Save** writes files into Artist/Album folders with tags and artwork.

**How it's built (17 Nov):** the Music screen lists what the phone's Music library (`MediaLibrary.sqlitedb`) says is stored on it, plus any song file the library doesn't describe; a library entry with no file on the phone (it streams from Apple Music or iCloud) is counted, not listed, and a note on the right says how many and why. Choosing a song shows its artwork (the library's own for the song, else its album's, from `iTunes_Control/iTunes/Artwork/Originals`) and its details. **Save selected** puts each song in `Artist/Album/NN Title.ext` (the album artist's folder when there is one) and writes the library's title, artist, album, album artist, genre, year, track, disc and artwork into the file (m4a, MP3, AIFF/WAV, FLAC) with mutagen. Tags go into a copy first: a file mutagen can't read is saved untouched, and a copy that stops half-way (cable pulled) leaves nothing behind. Folder and file names never hold characters a disk refuses or a name Windows keeps for itself (CON, AUX...), and a song's place stays within 160 characters; a song the disk still refuses is skipped, the others are saved, and the banner says which. Songs Apple protects (FairPlay) are saved as they are. Play and Space copy the song untouched. Read-only on the phone.

**Done when**
- [ ] Saved songs show correct title, artist, album and artwork in Music / Windows Media Player. *(17 Nov: `tests/test_p2_music.py` saves m4a, MP3 and WAV songs from an invented iPhone through the real LiveDevice code and reads back every tag and the artwork with mutagen, the library Music and Windows Media Player read the same tags from. On the owner's iPhone no song is stored (its library only streams), so this waits for a phone with songs on it, then a look in Music and Windows Media Player.)*
- [x] Songs that only stream (not on the phone) are not listed, and a note says why. *(17 Nov: `tests/test_p2_music.py`, and `tools/real_check.py` on the owner's iPhone: the library's streaming songs aren't listed and the Music screen says how many and why.)*

## P3. Books and PDFs

**Status: Done.** Add a filter: Books · PDFs · Audiobooks · All. EPUBs stored unpacked on the phone are saved as proper .epub files (already done; keep it).

## P4. Copy photos and music to the iPhone

**P3. Writes to the phone.** Drag photos or songs onto the phone window → confirmation "Add 24 photos to Photos on Sam's iPhone?" → they appear in the Photos / Music app with original dates and tags. Logged in the activity log.

## P6. Ringtones

**P3.** List and play ringtones on the phone; save them; make one from a song or voice memo (trim to 30 seconds, preview, then copy to the phone after confirmation).

## P7. Voice Memos

**Status: Done (play and save).** Add the standard date filter and a waveform preview (Q2).
