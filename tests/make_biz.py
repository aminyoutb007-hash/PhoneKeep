"""Make tests/work/biz/backup: the full sample backup plus a WhatsApp Business database."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import sys, sqlite3, shutil, hashlib
import phonekeep as pk
from pathlib import Path
src = Path('tests/work/Backups/00008030-FULLTEST'); dst = Path('tests/work/biz/backup')
shutil.rmtree('tests/work/biz', ignore_errors=True); shutil.copytree(src, dst)
man = sqlite3.connect(dst / 'Manifest.db')
fid = man.execute("select fileID from Files where domain=? and relativePath='ChatStorage.sqlite'", (pk.WA_DOMAIN,)).fetchone()[0]
tmp = Path('tests/work/biz/b.sqlite'); tmp.write_bytes((dst / fid[:2] / fid).read_bytes())
c = sqlite3.connect(tmp)
c.execute("update ZWACHATSESSION set ZPARTNERNAME='Acme Customer Ltd'")
c.execute("update ZWAMESSAGE set ZTEXT='Hello, is my order ready?'")
c.execute("insert into ZWACHATSESSION values (2,'447700900222@s.whatsapp.net','Supplier Co',0,0)")
c.execute("insert into ZWACHATSESSION values (3,'1203630@g.us','Staff group',1,0)")
for i, (chat, txt) in enumerate([(2, 'Invoice attached'), (2, 'Thanks'), (3, 'Shift swap?')]):
    c.execute("insert into ZWAMESSAGE(Z_PK,ZCHATSESSION,ZISFROMME,ZMESSAGEDATE,ZTEXT,ZMESSAGETYPE) values (?,?,0,?,?,0)", (10 + i, chat, 770000000 + i * 3600, txt))
c.commit(); c.close()
nf = hashlib.sha1(f"{pk.WA_BUSINESS_DOMAIN}-ChatStorage.sqlite".encode()).hexdigest()
(dst / nf[:2]).mkdir(exist_ok=True); (dst / nf[:2] / nf).write_bytes(tmp.read_bytes())
man.execute("insert into Files values (?,?,?,1,NULL)", (nf, pk.WA_BUSINESS_DOMAIN, 'ChatStorage.sqlite')); man.commit()
print("ok", dst)
