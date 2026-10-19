#!/usr/bin/env python3
"""Daily Granola export: decrypts Granola's local cache/database (Windows DPAPI key) and writes
one markdown file per meeting (AI notes + my notes + transcript when cached locally).
Idempotent: meetings already exported (matched by Granola ID) are skipped, except files that were
written before their transcript / notes were available, which get upgraded."""
import argparse, base64, ctypes, datetime as dt, glob, json, os, re, shutil, sys, tempfile, traceback
from ctypes import wintypes

HERE = os.environ.get("EXPORT_HOME") or os.path.dirname(os.path.abspath(__file__))
# Where the markdown files go. Override with --out or the GRANOLA_EXPORT_OUT environment variable.
DEFAULT_OUT = os.environ.get("GRANOLA_EXPORT_OUT") or os.path.join(os.path.expanduser("~"), "Documents", "Granola Notes")
NO_TRANSCRIPT = '_Transcript not available locally (Granola did not cache it on this device)._'
NO_NOTES = '_AI notes not generated yet at export time._'

def log(msg):
    line = f'{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}'
    print(line)
    try:
        with open(os.path.join(HERE, 'export.log'), 'a', encoding='utf-8') as f: f.write(line + '\n')
    except Exception: pass

# ---------- key handling ----------
def dpapi_unprotect(blob: bytes) -> bytes:
    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    inb = BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_char)))
    outb = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(outb)):
        raise OSError('CryptUnprotectData failed (must run as the same Windows user that runs Granola)')
    data = ctypes.string_at(outb.pbData, outb.cbData)
    ctypes.windll.kernel32.LocalFree(outb.pbData)
    return data

def get_master_key(gdir, key_file=None):
    if key_file: return open(key_file, 'rb').read()  # testing only
    ls = json.load(open(os.path.join(gdir, 'Local State'), encoding='utf-8'))
    raw = base64.b64decode(ls['os_crypt']['encrypted_key'])
    assert raw[:5] == b'DPAPI', 'unexpected key format'
    return dpapi_unprotect(raw[5:])

def get_dek(gdir, master):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = open(os.path.join(gdir, 'storage.dek'), 'rb').read()
    assert d[:3] == b'v10', 'unexpected storage.dek format'
    return base64.b64decode(AESGCM(master).decrypt(d[3:15], d[15:], None))

def load_cache(gdir, dek):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    files = sorted(glob.glob(os.path.join(gdir, 'cache-v*.json.enc')))
    if not files: raise FileNotFoundError('no cache-v*.json.enc found')
    e = open(files[-1], 'rb').read()
    return json.loads(AESGCM(dek).decrypt(e[:12], e[12:], None))['cache']['state']

def open_db(gdir, dek, tmp):
    import sqlcipher3
    for n in ('granola.db', 'granola.db-wal', 'granola.db-shm'):
        s = os.path.join(gdir, n)
        if os.path.exists(s): shutil.copy2(s, os.path.join(tmp, n))
    db = sqlcipher3.connect(os.path.join(tmp, 'granola.db'))
    db.execute(f"PRAGMA key=\"x'{dek.hex()}'\"")
    db.execute('select count(*) from sqlite_master').fetchone()
    return db

# ---------- markdown ----------
def inline(nodes):
    o = ''
    for n in nodes or []:
        if n['type'] == 'text':
            t = n['text']
            for m in n.get('marks', []):
                ty = m['type']
                if ty == 'bold': t = f'**{t}**'
                elif ty == 'italic': t = f'*{t}*'
                elif ty == 'code': t = f'`{t}`'
                elif ty == 'link': t = f"[{t}]({m['attrs'].get('href', '')})"
            o += t
        elif n['type'] == 'hardBreak': o += '  \n'
        else: o += inline(n.get('content'))
    return o

def block(n, ind=''):
    ty = n['type']; c = n.get('content', [])
    if ty == 'heading': return ['#' * n['attrs'].get('level', 3) + ' ' + inline(c), '']
    if ty == 'paragraph': return [ind + inline(c), ''] if c else []
    if ty in ('bulletList', 'orderedList'):
        out = []
        for i, li in enumerate(c, 1):
            mark = '-' if ty == 'bulletList' else f'{i}.'
            sub = []
            for ch in li.get('content', []): sub += block(ch, ind + '  ')
            sub = [s for s in sub if s != '']
            if sub:
                out.append(f'{ind}{mark} ' + (sub[0][len(ind) + 2:] if sub[0].startswith(ind + '  ') else sub[0]))
                out += sub[1:]
        return out + ['']
    if ty == 'blockquote':
        out = []
        for ch in c: out += ['> ' + l if l else '>' for l in block(ch)]
        return out
    if ty == 'codeBlock': return ['```', inline(c), '```', '']
    if ty == 'horizontalRule': return ['---', '']
    out = []
    for ch in c: out += block(ch, ind)
    return out

def to_md(js):
    if not js: return ''
    j = json.loads(js) if isinstance(js, str) else js
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(block(j))).strip()

def make_transcript(segs, tz):
    segs = sorted(segs, key=lambda x: x['start_timestamp'])
    ptime = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(tz)
    t0 = ptime(segs[0]['start_timestamp']); out = []; last = None
    for s in segs:
        sp = s.get('detected_speaker_name') or ('Me' if s['source'] == 'microphone' else 'Other')
        el = int((ptime(s['start_timestamp']) - t0).total_seconds())
        if sp == last: out[-1][1] += ' ' + s['text'].strip()
        else: out.append([f'{el // 3600:02d}:{el % 3600 // 60:02d}:{el % 60:02d}', s['text'].strip(), sp]); last = sp
    return '\n\n'.join(f'**{sp}** [{ts}]: {tx}' for ts, tx, sp in out)

# ---------- main ----------
def index_existing(outdir):
    idx = {}
    for p in glob.glob(os.path.join(outdir, '*.md')):
        try:
            head = open(p, encoding='utf-8').read()
        except Exception: continue
        m = re.search(r'^- \*\*Granola ID:\*\* ([0-9a-f-]{36})', head, re.M)
        if m: idx[m.group(1)] = (p, head)
    return idx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--granola-dir', default=os.path.join(os.environ.get('APPDATA', ''), 'Granola'))
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--tz', default=None, help='fixed UTC offset like +05:30 (default: system timezone)')
    ap.add_argument('--key-file', default=None, help='testing only')
    a = ap.parse_args()
    if a.tz:
        sign = -1 if a.tz[0] == '-' else 1; h, m = a.tz.lstrip('+-').split(':')
        tz = dt.timezone(sign * dt.timedelta(hours=int(h), minutes=int(m)))
    else: tz = dt.datetime.now().astimezone().tzinfo
    ptime = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(tz)

    master = get_master_key(a.granola_dir, a.key_file)
    dek = get_dek(a.granola_dir, master)
    T = load_cache(a.granola_dir, dek).get('transcripts', {})
    os.makedirs(a.out, exist_ok=True)
    existing = index_existing(a.out)
    new = upd = skip = 0
    with tempfile.TemporaryDirectory() as tmp:
        db = open_db(a.granola_dir, dek, tmp)
        rows = db.execute('select id,created_at,title,notes_markdown,google_calendar_event,people '
                          'from documents where deleted_at is null order by created_at').fetchall()
        for did, cr, title, nm, gce, people in rows:
            title = (title or 'Untitled').strip() or 'Untitled'
            panels = db.execute('select title,content from document_panels where document_id=? and deleted_at is null '
                                'order by created_at', (did,)).fetchall()
            has_t = bool(T.get(did)); mine = (nm or '').strip()
            if not (panels or has_t or mine): continue
            if did in existing:
                p, old = existing[did]
                need = (has_t and NO_TRANSCRIPT in old) or (panels and NO_NOTES in old)
                if not need: skip += 1; continue
            start = ptime(cr)
            try: start = ptime(json.loads(gce)['start']['dateTime'])
            except Exception: pass
            att = []
            try:
                for x in json.loads(people).get('attendees', []):
                    att.append(x.get('details', {}).get('person', {}).get('name', {}).get('fullName') or x.get('email'))
            except Exception: pass
            L = [f'# {title}', '', f'- **Date:** {start:%Y-%m-%d %H:%M} (UTC{start:%z})',
                 f'- **Granola ID:** {did}']
            if att: L.append('- **Attendees:** ' + ', '.join(dict.fromkeys(x for x in att if x)))
            L += ['', '## Granola AI Notes', '']
            if panels:
                for pt_, pc in panels:
                    if len(panels) > 1 and pt_: L += [f'### {pt_}', '']
                    L += [to_md(pc) or '_Empty_', '']
            else: L += [NO_NOTES, '']
            if mine: L += ['## My Notes', '', mine, '']
            L += ['## Transcript', '', make_transcript(T[did], tz) if has_t else NO_TRANSCRIPT, '']
            if did in existing: fn = existing[did][0]; upd += 1
            else:
                base = os.path.join(a.out, f'{start:%Y-%m-%d} - ' + re.sub(r'[<>:"/\\|?*]', '-', title).strip())
                fn = base + '.md'
                if os.path.exists(fn): fn = f'{base} ({start:%H%M}).md'
                new += 1
            with open(fn, 'w', encoding='utf-8', newline='\n') as f: f.write('\n'.join(L))
            log(('UPDATED ' if did in existing else 'NEW     ') + os.path.basename(fn) + (' [transcript]' if has_t else ''))
        db.close()
    log(f'done: {new} new, {upd} updated, {skip} unchanged')

if __name__ == '__main__':
    try: main()
    except Exception:
        log('ERROR ' + traceback.format_exc().replace('\n', ' | '))
        try: open(os.path.join(HERE, 'LAST_ERROR.txt'), 'w', encoding='utf-8').write(traceback.format_exc())
        except Exception: pass
        sys.exit(1)
    else:
        try: os.remove(os.path.join(HERE, 'LAST_ERROR.txt'))
        except OSError: pass
