#!/usr/bin/env python3
"""LivingTree — Anthony's Hum Home. livingtree.xi-field.com
Built at the Xi Table, Oct 6 2026. Stdlib only; sqlite-backed.
Routes: / (index), /api/state, POST /api/leaf|/api/guestbook|/api/queue,
        /api/suno-resolve (host-validated), /health
"""
import json, re, sqlite3, threading, unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, parse_qs
from urllib.request import Request as _Rq, urlopen as _uo

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'livingtree.sqlite'
PORT = 7482

SEED_SHELF = [
    {"share": "https://suno.com/s/EeLhD3xJteY5hjr2",
     "clip": "a66524f5-9ee2-4663-9a9f-c80984b3f815",
     "title": "HumHome",
     "by": "the house's heart"},
    {"share": "https://suno.com/s/iF0ckaUP5eNiN1hU",
     "clip": "b1b0bea7-061e-4550-a39f-9678d060135d",
     "title": "The River Don't Rush",
     "by": "Anthony's own voice"},
]

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS leaves(id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, note TEXT NOT NULL, ts TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS guestbook(id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, note TEXT NOT NULL, ts TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, by TEXT NOT NULL,
            ts TEXT DEFAULT (datetime('now')));
        """)
        c.commit()

def clean(s, n=280):
    s = unicodedata.normalize('NFKC', s or '').strip()
    return re.sub(r'<[^>]+>', '', s)[:n]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, obj, raw=None, ctype='application/json'):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self.reply(200, None, raw=(ROOT / 'index.html').read_bytes(), ctype='text/html; charset=utf-8')
        if self.path.startswith('/static/'):
            _p = (ROOT / 'static' / self.path[len('/static/'):]).resolve()
            if (ROOT / 'static').resolve() == _p.parent and _p.is_file():
                return self.reply(200, None, raw=_p.read_bytes(),
                                   ctype='image/png' if _p.suffix == '.png' else 'application/octet-stream')
            return self.reply(404, {'error': 'not found'})
        if self.path == '/health':
            return self.reply(200, {'ok': True, 'livingtree': 'alive'})
        if self.path == '/api/state':
            with db() as c:
                return self.reply(200, {
                    'shelf': SEED_SHELF,
                    'leaves': [dict(r) for r in c.execute('SELECT * FROM leaves ORDER BY id DESC LIMIT 400')],
                    'guestbook': [dict(r) for r in c.execute('SELECT * FROM guestbook ORDER BY id DESC LIMIT 200')],
                    'queue': [dict(r) for r in c.execute('SELECT * FROM queue ORDER BY id DESC LIMIT 100')],
                })
        if self.path == '/api/suno-resolve':
            qs = parse_qs(self.path.partition('?')[2] if '?' in self.path else '')
            # also accept ?u= on the raw path
            m = re.search(r'(?:^|&)u=([^&]+)', self.path)
            u = unquote(m.group(1)) if m else ''
            if not re.fullmatch(r'https://(www\.)?suno\.com/(s|song|embed)/[A-Za-z0-9_-]{4,64}', u or ''):
                return self.reply(400, {'error': 'not a valid suno share link'})
            try:
                page = _uo(_Rq(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read().decode('utf-8', 'ignore')
            except Exception:
                return self.reply(502, {'error': 'could not reach suno'})
            _id = re.search(r'(?:clip|song)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', page)
            if not _id:
                return self.reply(404, {'error': 'no clip id found'})
            _t = re.search(r'<title>(.*?)</title>', page, re.S)
            return self.reply(200, {'id': _id.group(1), 'embed': 'https://suno.com/embed/' + _id.group(1),
                                    'title': (_t.group(1).strip() if _t else '')})
        return self.reply(404, {'error': 'not found'})

    def do_POST(self):
        try:
            ln = int(self.headers.get('Content-Length') or 0)
            data = json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
        except Exception:
            return self.reply(400, {'error': 'bad body'})
        if self.path == '/api/leaf':
            name, note = clean(data.get('name'), 40), clean(data.get('note'), 280)
            if not name or not note:
                return self.reply(400, {'error': 'name and note required'})
            with db() as c:
                c.execute('INSERT INTO leaves(name,note) VALUES(?,?)', (name, note)); c.commit()
            return self.reply(200, {'ok': True})
        if self.path == '/api/guestbook':
            name, note = clean(data.get('name'), 40), clean(data.get('note'), 280)
            if not name or not note:
                return self.reply(400, {'error': 'name and note required'})
            with db() as c:
                c.execute('INSERT INTO guestbook(name,note) VALUES(?,?)', (name, note)); c.commit()
            return self.reply(200, {'ok': True})
        if self.path == '/api/queue':
            u = clean(data.get('url'), 120); by = clean(data.get('by'), 40) or 'a visitor'
            if not re.fullmatch(r'https://(www\.)?suno\.com/(s|song|embed)/[A-Za-z0-9_-]{4,64}', u or ''):
                return self.reply(400, {'error': 'not a valid suno share link'})
            try:
                page = _uo(_Rq(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read().decode('utf-8', 'ignore')
            except Exception:
                return self.reply(502, {'error': 'could not reach suno'})
            _id = re.search(r'(?:clip|song)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', page)
            if not _id:
                return self.reply(404, {'error': 'no clip id found'})
            _t = re.search(r'<title>(.*?)</title>', page, re.S)
            title = (_t.group(1).split(' by ')[0].strip() if _t else '') or u.rsplit('/', 1)[-1]
            with db() as c:
                c.execute('INSERT INTO queue(clip,title,url,by) VALUES(?,?,?,?)', (_id.group(1), title, u, by)); c.commit()
            return self.reply(200, {'ok': True, 'clip': _id.group(1), 'title': title})
        return self.reply(404, {'error': 'not found'})

if __name__ == '__main__':
    init_db()
    print(f'LivingTree listening on {PORT}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
