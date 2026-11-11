# PhoneKeep

Back up your **whole iPhone** over USB and get a browsable, searchable offline archive of everything on it. Runs on Windows and Mac, 100% locally: nothing is uploaded anywhere.

## What's in the archive

Open `index.html` in the archive folder and you get a home page for your iPhone with a card for each section:

| Section | What you get |
|---|---|
| **WhatsApp** and **WhatsApp Business** | Each app in its own folder. Every chat with photos, videos, voice notes, locations, group sender names, starred messages; search across all chats; media gallery per chat |
| **Messages** | iMessage, SMS and RCS conversations in the same chat view, with attachments (HEIC photos converted so browsers show them). iMessage and SMS threads with the same person are merged |
| **Photos & videos** | Full-size originals in `Photos/Originals`, plus a gallery by year and month with thumbnails. Live Photos are recognised |
| **Contacts** | Searchable list, plus a **.vcf** file you can import into a new iPhone, Android, Google or Outlook, plus CSV |
| **Calls** | Phone, FaceTime and WhatsApp calls: incoming, outgoing and missed, with duration |
| **Notes** | Every note with its folder, plus a plain-text copy of each one in `Notes/text` |
| **Calendar** | All events, plus an **.ics** file you can import into any calendar |
| **Voicemail** | Visual voicemail list with the audio files |
| **Voice Memos** | Recordings named by title and date, playable in the browser |
| **Safari** | Bookmarks, Reading List and browsing history |
| **Apps** | The installed apps |
| **All files (raw)** | Optional: every file in the backup, organised by app/area, for anything not covered above |

Contact names are used everywhere, so Messages, Calls and WhatsApp show "Sara" rather than a phone number.

## Install

**Easiest: the one-file installer**
- **Mac:** open `PhoneKeep-Mac-AppleSilicon.dmg` (M1/M2/M3/M4 Macs) or `PhoneKeep-Mac-Intel.dmg`, then drag **PhoneKeep** onto **Applications**. The first time, **right-click PhoneKeep → Open → Open**. On macOS 15 or later, if there's no Open button, go to **System Settings → Privacy & Security** and click **Open Anyway**. This is needed only once, because the app isn't registered with Apple ($99/year).
- **Windows:** run `PhoneKeep-Setup.exe`. If SmartScreen warns, click **More info → Run anyway**. You also need Apple's USB driver: install **iTunes** or the free **Apple Devices** app from the Microsoft Store.

No Python needed. See "Making the installers" below for how to get these files.

**Or run from source** (needs Python):

### Setup (once)

1. Install **Python 3.10+** from <https://www.python.org/downloads/> (on Windows, tick "Add Python to PATH").
2. **Windows only:** install **iTunes** or the **Apple Devices** app from the Microsoft Store. It provides Apple's USB driver.
3. Unzip this folder somewhere.

## Use it

1. Plug in your iPhone (or use Wi-Fi sync), unlock it and tap **Trust This Computer**. PhoneKeep shows the phone's name and when it was last backed up.
2. Choose **what to keep**: **Chats** (WhatsApp, WhatsApp Business and Messages), **Chats & photos**, **Everything**, or **Custom** to pick exactly.
3. Choose how to **save chats**: **Web pages** (a WhatsApp-style browsable archive), **Excel** (one workbook, one sheet per chat, plus a summary sheet) and/or **CSV** (one file per chat, plus all chats in one file).
4. Click **Back up now**. Keep the phone unlocked. If it asks for its passcode, enter it on the phone.
5. **Choose your chats.** A window lists every chat from WhatsApp, WhatsApp Business and Messages. Click one to **preview** its latest messages and photos, and tick the ones you want to keep.
6. **Choose your photos.** Browse them month by month as thumbnails, click to select, or use **Select all** or **Select this month**. Only the photos you pick are copied.
7. When it's done, click **Open my archive**.

To skip the pickers and keep everything, turn off **which chats** and **which photos** next to "Let me choose". PhoneKeep remembers your choices for next time.

⚙ **Settings** holds the rest: folders, backup encryption (**recommended**, because encrypted backups are the only ones that include call history and Safari history), the Custom list, and **Use an existing backup**, which builds an archive from a backup already on this computer.

The first backup copies the whole phone and can take an hour or more. Apple only allows whole-phone backups; PhoneKeep then keeps just what you chose. Later backups only copy what has changed.

Default locations (in your home folder):
- Backups: `PhoneKeep/Backups`
- Archive: `PhoneKeep/Archive`

### About photos and iCloud Photos

If **iCloud Photos** is on, iOS leaves the photo library out of backups. Keep **"Copy photos directly from the phone"** ticked: PhoneKeep then copies the camera roll straight off the iPhone, and only new photos on later runs. If the phone is set to **Optimize iPhone Storage**, some originals only exist in iCloud. To get those, switch the phone to **Download and Keep Originals** first (Settings → Photos), or download them from icloud.com.

## Command line (optional)

```
python phonekeep.py devices                  # is the iPhone connected?
python phonekeep.py encryption on            # protect backups with a password
python phonekeep.py run --photos             # back up + copy photos + build full archive
python phonekeep.py backup                   # back up only
python phonekeep.py photos                   # copy photos straight off the phone
python phonekeep.py backups                  # list backups on this computer
python phonekeep.py export                   # build full archive from a backup
python phonekeep.py export --only messages,contacts,notes
python phonekeep.py export --all-files       # also dump every raw file
python phonekeep.py export --only whatsappbusiness --chats "Acme,Supplier" --formats excel,csv
python phonekeep.py whatsapp                 # WhatsApp-only archive
```
Sections: `whatsapp, whatsappbusiness, messages, photos, contacts, calls, notes, calendar, voicemail, voicememos, safari, apps, files`.

## Good to know

- **Not included:** saved passwords (Keychain), Health data and Screen Time. These need extra decryption that PhoneKeep doesn't do; they are still inside your encrypted backup and come back if you restore it to an iPhone.
- **Locked notes** show as locked; their content stays encrypted.
- **Excel and CSV files are safe to open:** a message that looks like a spreadsheet formula (for example one starting with `=`) is always kept as plain text, never run.
- **"No WhatsApp data"**: if WhatsApp's own *end-to-end encrypted chat backup* is on, iOS may keep chats out of device backups.
- **Mac: can't see iTunes/Finder backups**: give Terminal *Full Disk Access* (System Settings → Privacy & Security).
- **"No iPhone found"**: use a data cable, unlock the phone and accept the Trust prompt. On Windows, make sure iTunes or Apple Devices is installed.
- Voicemail audio is AMR; VLC or QuickTime plays it. WhatsApp voice notes (.opus) play in Chrome, Edge and Firefox.
- Your backup is a full copy of your phone. Keep it encrypted and somewhere safe.

## Making the installers

A Mac app has to be built on a Mac and a Windows app on Windows. GitHub can do both for free:

1. Create a free account at <https://github.com> and a **new repository** (it can be private).
2. Upload everything in this folder, **including the hidden `.github` folder**. On a Mac, press **Cmd + Shift + .** in Finder to show hidden files, then drag the folder's contents onto the repository's "uploading an existing file" page.
3. Go to **Actions → Build installers → Run workflow**.
4. After about 10–15 minutes, open the finished run. Under **Artifacts** you'll find the Mac `.dmg` files and `PhoneKeep-Setup.exe`.

Tip: create a tag such as `v2.0.0` (Releases → Draft a new release) and the installers are published on the Releases page automatically.

**Build on your own Mac instead:** with Python from python.org installed, run `bash packaging/build-mac.sh` in Terminal. It produces `PhoneKeep.dmg`.

## Built on

- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3): USB communication, backups and direct file copy
- [iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt): encrypted backup decryption
- [Pillow](https://python-pillow.org) + [pillow-heif](https://github.com/bigcat88/pillow_heif): thumbnails and HEIC conversion
