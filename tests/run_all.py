"""Run every test script in order; exits non-zero if any fails.

Usage (from the repository root):  python tests/run_all.py
Generated data goes to tests/work/ (ignored by git).
"""
import os, shutil, signal, subprocess, sys, time
from pathlib import Path

# The app and its exports are UTF-8 everywhere; make Python on Windows read and print them that way too.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ["PHONEKEEP_NO_HELPER"] = "1"      # tests open the real window; it must not start a real helper
for _out in (sys.stdout, sys.stderr):        # run_all's own printing too (a Windows console is cp1252: "→" crashed it)
    _out.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
STEPS = [
    ("Full fake backup (every data type) + export", "test_full_backup.py", False),
    ("WhatsApp Business backup", "make_biz.py", False),
    ("Rich photo backup (months, Live Photo, video, thumbnails)", "make_rich.py", False),
    ("Security: script injection, path escapes, spreadsheet formulas", "test_security.py", False),
    ("Phone window with a simulated iPhone", "test_phone_window.py", True),   # needs a display
    ("S1: encryption by default, keychain, no password on command lines or in logs", "test_s1_encryption.py", True),
    ("S2: app lock with Touch ID / the computer password / Windows Hello", "test_s2_app_lock.py", True),
    ("S3: no network during backup + export + phone window", "test_s3_no_network.py", True),
    ("E3: plain-language errors, each situation reproduced", "test_e3_errors.py", True),
    ("B1: a running backup can be cancelled (engine, main window, guide, helper)", "test_b1_cancel.py", True),
    ("M3: chats to PDF (2,000 messages with photos in under 30 s; Arabic, French, emoji)", "test_m3_chat_pdf.py", True),
    ("M4: full detail in Excel and CSV (replies, reactions, edited, deleted and read times, service, group numbers)", "test_m4_full_detail.py", True),
    ("M5: one person in a group chat (People: preview, row counts, Excel, CSV and PDF keep only their messages)", "test_m5_group_person.py", True),
    ("M6: chat attachments open large (arrows go through them); a Media tab per chat; Save all with their dates", "test_m6_media_viewer.py", True),
    ("Music (P2): songs saved into Artist / Album folders with their tags and artwork; songs that only stream aren't listed, and a note says why", "test_p2_music.py", True),
    ("Video conversion (P8): Most compatible saves an iPhone (HEVC) video as an H.264 MP4 with its date taken and location on a Mac; elsewhere videos are saved as they are", "test_p8_video.py", True),
    ("Contacts (D1): photos, the phone's Lists with counts, linked cards as one, a contact card; vCard with photos, Excel, CSV; Keep both / Replace / Skip", "test_d1_contacts.py", True),
    ("Call recordings (D6): notes the Phone app made, who/when/length, transcript, Play, Save audio and transcript", "test_d6_call_recordings.py", True),
    ("Notes (D4): folders, Pinned, Recently Deleted; a note as on the phone (styles, checklists, tables, images, scans, drawings); Save as PDF or text", "test_d4_notes.py", True),
    ("E1: first-run guide walked end to end with a stub iPhone", "test_e1_first_run.py", True),
    ("E2: menu bar / tray helper backs up and notifies with no window open", "test_e2_helper.py", True),
    ("B2: scheduled automatic backups with a fake clock", "test_b2_schedule.py", False),
    ("B3: snapshots over time, content store, upgrade, FAT32", "test_b3_snapshots.py", False),
    ("B4: backup location, moving backups, unplugged drive, free space", "test_b4_location.py", True),
    ("X2: backup redaction tool leaves nothing personal and still opens", "test_x2_redaction.py", False),
    ("B5: open any backup with no phone; All files preview and save", "test_b5_open_backup.py", True),
    ("B8: choose which iPhone when several are reachable", "test_b8_choose_iphone.py", True),
    ("P1: photos: favourites, albums, hidden, HEIC to JPG with date and location", "test_p1_photos.py", True),
    ("V1-V3: device overview, battery health, storage usage", "test_v123_device.py", True),
    ("Q1: quick preview everywhere (Space)", "test_q1_previews.py", True),
    ("D9: save everything with one date range and search", "test_d9_save_everything.py", True),
    ("H1: the check-up: four cards, thresholds, why slow, one notification per red card", "test_h1_checkup.py", True),
    ("H2: storage suggestions, biggest first, with steps; the storage forecast", "test_h2_storage.py", True),
    ("H3: battery history chart, notes and tips for the model; Save details as CSV", "test_h3_battery.py", True),
    ("H4: stability: crash reports read-only, apps and restarts counted, Save reports", "test_h4_stability.py", True),
    ("H5: security checks: passcode, iOS version, profiles, apps outside the App Store, jailbreak; read-only", "test_h5_security.py", True),
    ("C1: photo clean-up: six cards, keepers, saving checked by checksum, 10,000 photos", "test_c1_cleanup.py", True),
    ("Build: the Mac build script puts build_label.py back with git", "test_build_label.py", False),
    ("Licence: GPL-3.0-or-later; the built app carries LICENSE and THIRD_PARTY_NOTICES.md", "test_licence.py", False),
    ("No real names: the owner's surname and first name are in no tracked file (checked by hash)", "test_no_owner_names.py", False),
    ("Theme: Direction A colours from theme.py only; buttons and selected rows", "test_theme.py", False),
    ("Mac window tabs: every window is made with tabs off (5.1.2)", "test_mac_tabs.py", False),
    ("PhoneKeep opens when drag-and-drop can't load (macOS 11-13; 5.2.2)", "test_dnd_start.py", True),
    ("Reconnect: the iPhone unplugged and plugged back in (5.1.3)", "test_reconnect.py", True),
    ("Fast overview: the window fills in without waiting for the app list; Wi-Fi asks less (5.1.3)", "test_fast_overview.py", True),
    ("Main window: the iPhone's home screen in the small phone picture (5.1.3)", "test_main_wallpaper.py", True),
    ("Storage timeout: one slow answer never blanks the rest; storage asked again, then 'Try again' (5.1.3)", "test_storage_timeout.py", True),
    ("Closed connection: reads on a let-go connection fail at once and plainly; the app list reconnects once (5.1.3)", "test_closed_connection.py", False),
    ("Storage: a quick failing app list doesn't make the screen ask and redraw for ever (5.2)", "test_storage_loop.py", True),
    ("Storage tips (V6): how to free each of the largest apps' space, steps only (5.2)", "test_storage_tips.py", True),
    ("Phone window layout (L1): header, Snapshot card, cards, four columns of tiles; every tile opens (5.2)", "test_l1_phone_window.py", True),
    ("Backup progress screen (L2): percentage, steps, Look at your iPhone, Cancel; the window comes back (5.2)", "test_l2_backup_progress.py", True),
    ("Settings layout (L3): the list on the left reaches every card; every setting kept; Activity and About (5.2)", "test_l3_settings.py", True),
    ("Closing the window while backing up (B9): the backup carries on, notifies, then quits; Quit asks first (5.3)", "test_b9_close_while_backing_up.py", True),
    ("One search across the phone (E4): every app at once, accents and Arabic marks ignored, 200,000 messages in under 1 s", "test_e4_search.py", True),
    ("File search (F3): * and ?, All files in the backup, every app's files on the phone; open and save", "test_f3_file_search.py", True),
    ("Protected saves (S6): password PDFs and encrypted ZIPs, made privately, the password never kept", "test_s6_protect.py", True),
    ("Activity record (S7): each backup and save once, kept 12 months, listed in Settings and saved as CSV", "test_s7_activity.py", True),
    ("Large phones (E7): 300,000 messages and 50,000 photos meet every speed target; the photo grid scrolls only what's on screen", "test_e7_large.py", True),
    ("Dark mode (E6): the mode chosen, contrast, every widget dark and readable, no white flash, Settings → Appearance", "test_e6_dark_mode.py", True),
    ("Tamper check (S8): each snapshot sealed and signed; one byte changed shows the amber banner on the full check", "test_s8_tamper.py", True),
    ("Closing a phone window while it reads its backup: the read finishes, then the files are let go (no crash)", "test_close_while_reading.py", True),
    ("All phones in one list (E5): a card for each phone backed up here or connected; each opens its own window", "test_e5_all_phones.py", True),
    ("Chats as on the phone (Q2): replies quoted, reactions on the bubble, link cards from the backup, voice notes with a waveform", "test_q2_chats.py", True),
    ("Backup timeline (Q5): the slider changes the open screen to the snapshot it stops on within 2 seconds, with the badge", "test_q5_timeline.py", True),
]
# On Linux (no desktop) the window tests run under a virtual display if xvfb-run is installed.
XVFB = [] if sys.platform in ("darwin", "win32") else (["xvfb-run", "-a"] if shutil.which("xvfb-run") else None)
# A script that hangs fails after this long (and faulthandler prints where it was stuck).
TIMEOUT = int(os.environ.get("PHONEKEEP_TEST_TIMEOUT", "420"))
# The window tests that used to hang on GitHub's Mac machines (18 Nov) hung under Tk 8.6, the Tk the installers
# bundle, not because of GitHub: a phone or Settings window that is withdrawn (or tied to a withdrawn window) is
# redrawn without end there. The tests now keep such windows see-through instead (tests/tkcompat.py), so every
# test counts everywhere and a hang fails the run.
# every test writes PhoneKeep's own files (activity log, settings, locks) to a test folder, never ~/PhoneKeep
os.environ["PHONEKEEP_HOME"] = str(HERE / "work" / "home")
REAL_HOME = Path.home() / "PhoneKeep"


def _real_home_state():
    try:
        return sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in REAL_HOME.iterdir() if p.is_file())
    except OSError:
        return None


real_before = _real_home_state()
failed = []
for name, script, needs_display in STEPS:
    print(f"\n=== {name} ({script})", flush=True)
    cmd = [sys.executable, "-X", "faulthandler", str(HERE / script)]
    if needs_display:
        if XVFB is None:
            print("skipped: no display (install xvfb to run it on Linux)", flush=True)
            continue
        cmd = XVFB + cmd
    t0 = time.time()
    posix = sys.platform != "win32"
    p = subprocess.Popen(cmd, cwd=HERE.parent, start_new_session=posix)   # own group: xvfb-run and the test
    try:
        code = p.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"TIMED OUT after {TIMEOUT} s; where it was stuck:", flush=True)
        if posix:
            os.killpg(p.pid, signal.SIGABRT)       # faulthandler prints every thread's stack
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            p.kill()
        p.wait()
        code = 1
    print(f"--- {script}: {'ok' if not code else 'FAILED'} in {time.time() - t0:.0f} s", flush=True)
    if code:
        failed.append(script)
if _real_home_state() != real_before:
    print(f"\nFAIL: the tests changed files in the real {REAL_HOME} (they must use PHONEKEEP_HOME)")
    failed.append("real ~/PhoneKeep untouched")
print("\nALL TESTS PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
