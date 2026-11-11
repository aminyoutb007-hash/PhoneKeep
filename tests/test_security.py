"""Security regression tests: booby-trapped messages (XSS), path escapes, spreadsheet formulas."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import sys, sqlite3, shutil, hashlib, re, csv, zipfile
import phonekeep as pk, sections as sx, tables
from pathlib import Path
ok = True
src = Path('tests/work/Backups/00008030-FULLTEST')

def copy(name):
    d = Path(f'tests/work/sec/{name}'); shutil.rmtree(d, ignore_errors=True); shutil.copytree(src, d / 'backup'); return d

# 1. XSS
d = copy('xss'); man = sqlite3.connect(d / 'backup/Manifest.db')
evil = '<img src=x onerror=alert(1)><script>alert(2)</script>"><svg onload=alert(3)> https://x.com/"onmouseover="alert(5)'
for dom, rel, table, col in [(pk.WA_DOMAIN, 'ChatStorage.sqlite', 'ZWAMESSAGE', 'ZTEXT'), (sx.HOME, 'Library/SMS/sms.db', 'message', 'text')]:
    fid = man.execute("select fileID from Files where domain=? and relativePath=?", (dom, rel)).fetchone()[0]
    db = sqlite3.connect(d / 'backup' / fid[:2] / fid); db.execute(f"update {table} set {col}=?", (evil,)); db.commit(); db.close()
sx.export_all(d / 'backup', d / 'out', formats={'web', 'excel', 'csv'}, log=lambda m: None)
bad = [str(f) for f in (d / 'out').rglob('*.html') for pat in ['<img src=x', '<script>alert', '<svg onload', 'onmouseover="alert'] if pat in f.read_text()]
print('XSS in archive pages:', bad or 'none'); ok &= not bad

# 2. path escapes
d = copy('trav'); man = sqlite3.connect(d / 'backup/Manifest.db')
def add(dom, rel, data):
    fid = hashlib.sha1(f"{dom}-{rel}".encode()).hexdigest(); (d / 'backup' / fid[:2]).mkdir(exist_ok=True)
    (d / 'backup' / fid[:2] / fid).write_bytes(data); man.execute("insert into Files values (?,?,?,1,NULL)", (fid, dom, rel))
add(pk.WA_DOMAIN, 'Message/../../../../ESCAPED_wa.txt', b'x')
add(sx.MEDIA, 'Library/SMS/Attachments/../../../../../ESCAPED_sms.jpeg', b'x')
add(sx.CAMERA, 'Media/DCIM/../../../../../ESCAPED_photo.JPG', b'x')
fid = man.execute("select fileID from Files where domain=? and relativePath='ChatStorage.sqlite'", (pk.WA_DOMAIN,)).fetchone()[0]
db = sqlite3.connect(d / 'backup' / fid[:2] / fid)
db.execute("CREATE TABLE IF NOT EXISTS ZWAMEDIAITEM(Z_PK INTEGER PRIMARY KEY, ZMESSAGE, ZMEDIALOCALPATH, ZTITLE)")
db.execute("insert into ZWAMEDIAITEM(Z_PK,ZMESSAGE,ZMEDIALOCALPATH) values (99,1,'../../../../ESCAPED_wa.txt')")
db.execute("update ZWAMESSAGE set ZMEDIAITEM=99, ZMESSAGETYPE=8"); db.commit(); db.close()
fid = man.execute("select fileID from Files where domain=? and relativePath='Library/SMS/sms.db'", (sx.HOME,)).fetchone()[0]
db = sqlite3.connect(d / 'backup' / fid[:2] / fid)
db.execute("update attachment set filename='~/Library/SMS/Attachments/../../../../../ESCAPED_sms.jpeg'"); db.commit(); db.close()
man.commit(); man.close()
out = d / 'a/b/c/out'
sx.export_all(d / 'backup', out, sections=sx.DEFAULT_SECTIONS + ['files'], formats={'web', 'excel', 'csv'}, log=lambda m: None)
esc = [str(p) for p in d.rglob('ESCAPED*') if 'backup' not in p.parts and out.resolve() not in p.resolve().parents]
print('files written outside the archive:', esc or 'none'); ok &= not esc

# 3. spreadsheet formulas
evil = ['=HYPERLINK("http://evil.example","Click")', '+1+cmd', '-2+3', '@SUM(1,1)', '\t=1']
chats = [{"name": "=Evil", "group": False, "messages": [{"time": "2025-06-01T10:00:00", "sender": "=cmd", "type": "text", "text": t} for t in evil]}]
o = Path('tests/work/sec/inj'); o.mkdir(parents=True, exist_ok=True)
x = tables.write_chats_xlsx(chats, o / 't.xlsx', log=lambda m: None); tables.write_chats_csv(chats, o / 'csv', log=lambda m: None)
z = zipfile.ZipFile(x); formulas = sum(len(re.findall(r'<f[ >]', z.read(n).decode())) for n in z.namelist() if n.startswith('xl/worksheets/'))
risky = [c for f in (o / 'csv').glob('*.csv') for r in list(csv.reader(open(f, encoding='utf-8-sig')))[1:] for c in r if c and c[0] in '=+-@\t']
print('formulas in Excel:', formulas, '| risky CSV values:', risky or 'none'); ok &= formulas == 0 and not risky
print('SECURITY TESTS:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
