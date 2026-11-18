# 09. Files and apps

## F1. App documents

**Status: Done.** Apps that share files (Files, Pages, VLC…) are listed first with a folder icon; their Documents can be browsed, previewed (Space) and saved. Keep it working.

## F2. Drag files into iPhone apps

**Writes to the phone.**

**What the user sees and does:** drag files from the computer onto an app in the App Files screen (or onto the menu bar icon, then pick the app). A confirmation "Copy 3 files (48 MB) to VLC on Sam's iPhone?" → progress → "Copied. Open VLC on your iPhone to see them."

**Done when**
- [ ] Files dropped on VLC and Files appear in those apps on the phone.
- [ ] Cancelling the confirmation copies nothing; the copy is logged in the activity log.

## F3. File search

**What the user sees and does:** in App Files and All files (B5), a search box; `*` matches anything (`*.pdf`, `invoice*`). Results show app, path, size, date; open or save.

**Done when**
- [x] `*.pdf` finds PDFs across all sharing apps on the phone and in the chosen snapshot. *(18 Nov: on the owner's real phone and its latest backup, `tools/real_check.py` checks that "*.pdf" finds every PDF in the backup's file list, and every PDF in the apps that share files (each app's files listed in one go, which match going folder by folder); counts only. On invented data, `tests/test_f3_file_search.py`: the backup's JPEGs, and PDFs in folders inside folders in two apps of a simulated iPhone, one app that can't be read named.)*

**How it's built (18 Nov):**
- **The pattern** (`filesearch.py`): a name or part of one ("invoice"), or `*` for anything and `?` for one character ("*.pdf", "invoice*"). Case and accents don't matter (the same folding as Search everything, E4). A pattern with a "/" is matched against the path ("*/Scans/*.pdf"). An empty search, or `*` alone, isn't a search.
- **All files (the backup, or the snapshot open):** the box searches every area's file list on the backup reader's thread a moment after the typing stops; a newer search replaces an older one. The results replace the folders while there's a search: Area, Path, Size, Modified; at most 5,000 shown, the count says how many in all. Space or a double-click previews (Q1), the arrows go through the results; Save selected saves them as before. Clearing the box shows the folders again. (Before F3, a word selected matching names in the tree, reading every area's list on the screen's own thread.)
- **App Files (the phone):** a box above the apps, then Return: every app that shares files has its Documents listed, folders inside folders too (30 deep, at most 20,000 entries an app), through one connection an app (`LiveDevice.app_walk`, read-only), on the phone's own thread with "app 3 of 12" as it goes. Results: "App › path", size, date; an app that couldn't be read is named. Opening, Space and Save selected work on them, each from its own app; Save puts each into its app's folder. Choosing an app on the left goes back to browsing.

## F4. Apps and their data

**What the user sees and does:** the Apps screen lists installed apps with real names and icons, version and space used. Select one → **Save app data** saves that app's data from the backup as a folder.

**Done when**
- [ ] Names and icons match the phone's home screen; saved app data opens as normal folders and files.
