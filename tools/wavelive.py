"""wavelive.py — the live link of tools/wavemcp.py: the pages a person has open, connected to this process.

An HTTP server on 127.0.0.1 (from port 8742, or WAVELENS_LIVE_PORT, on) that a page connects to (EventSource): GET /events
gives it the viewer's commands (view_edit, view_get of wavemcp.py), POST /hello says who it is (its path, title, views),
POST /reply brings their results, POST /bye says it leaves. Every request carries this user's token
(~/.cache/wavelens/live-token, which view_live writes into a page); the Host is this machine, the Origin a file:// page
or this machine. While it runs, ~/.cache/wavelens/live/<port>.json says so (the VS Code extension's tabs connect to it,
vscode/), and a dump view_live asks VS Code to open is an open-<time>-<pid>.json there. Standard library only; the
names are wavemcp.py's too (from wavemcp import Bridge … as before).
"""
import atexit, contextlib, hmac, http.server, json, os, queue, re, secrets, shutil, socket, subprocess, sys, threading, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import wavepage  # noqa: E402
from common import WaveError  # noqa: E402

LIVE_PORT = 8742   # the first port tried (WAVELENS_LIVE_PORT), then the next nine
BRIDGE = []   # the one Bridge of this process, once a view tool started it


def cache_dir():
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'wavelens')


def live_token(new=False):
    """This user's token of the live link (made once, kept: a page that has it reconnects after a restart); new: another one."""
    d = cache_dir()
    p = os.path.join(d, 'live-token')
    try:
        with open(p, encoding='utf-8') as f:
            t = f.read().strip()
        if len(t) >= 16 and not new:
            return t
    except OSError:
        pass
    os.makedirs(d, exist_ok=True)
    t = secrets.token_urlsafe(18)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(t + '\n')
    return t


CID_RE = re.compile(r'[0-9a-z]{4,32}')   # a page's id on the link (edit.js: 8 letters and digits)
MAX_BODY = 64 << 20   # bytes of a page's answer (a picture)


class LiveHandler(http.server.BaseHTTPRequestHandler):
    """GET /events (server-sent events: the commands for the page), POST /hello (its viewers), POST /reply (the results);
    the token in every request, an Origin of a file:// page ("null") or this machine only."""
    bridge = None
    server_version, sys_version = 'wavelens', ''

    def log_message(self, *a):   # stdout is the protocol, stderr is the agent's log: quiet
        pass

    def head(self, code, ctype='application/json', length=None):
        self.send_response(code)
        self.origin()
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', ctype)
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def answer(self, code, obj):
        body = json.dumps(obj).encode()
        self.head(code, length=len(body))
        self.wfile.write(body)

    def query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def local(self):
        """The Host of the request is this server by a local name (not a name of another site sent here: DNS rebinding)."""
        return bool(re.fullmatch(rf'(127\.0\.0\.1|localhost|\[::1\]):{self.bridge.port}', self.headers.get('Host') or '', re.I))

    def origin_ok(self):
        o = self.headers.get('Origin')
        return o in (None, 'null') or bool(re.fullmatch(r'https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?', o))

    def origin(self):
        """The header that lets a page read the answer: for an Origin this link serves only."""
        if self.headers.get('Origin') and self.origin_ok():
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])

    def allowed(self):
        if not self.local() or not self.origin_ok():
            return False
        return hmac.compare_digest((self.query().get('token') or [''])[0].encode(), self.bridge.token.encode())

    def do_PUT(self):
        self.answer(405, {'error': 'GET or POST'})

    do_DELETE = do_PATCH = do_PUT

    def do_OPTIONS(self):
        if not self.local() or not self.origin_ok():
            return self.answer(403, {'error': 'not allowed'})
        self.send_response(204)
        self.origin()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/':
            return self.answer(200, {'wavelens': 'live'}) if self.local() else self.answer(403, {'error': 'not allowed'})
        if path != '/events':
            return self.answer(404, {'error': 'no such place'})
        cid = (self.query().get('cid') or [''])[0]
        if not self.allowed() or not CID_RE.fullmatch(cid):
            return self.answer(403, {'error': 'not allowed'})
        q = self.bridge.attach(cid)
        self.head(200, 'text/event-stream')
        try:
            self.wfile.write(b'retry: 2000\n\n')
            self.wfile.flush()
            while not self.bridge.closed:
                try:
                    m = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    continue
                if m is None:
                    break
                self.wfile.write(('event: cmd\ndata: ' + json.dumps(m, ensure_ascii=False) + '\n\n').encode())
                self.wfile.flush()
        except OSError:   # the page went (closed, reloaded)
            pass
        finally:
            self.bridge.detach(cid, q)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        cid = (self.query().get('cid') or [''])[0]
        if path not in ('/hello', '/bye', '/reply'):
            return self.answer(404, {'error': 'no such place'})
        if not self.allowed() or not CID_RE.fullmatch(cid):
            return self.answer(403, {'error': 'not allowed'})
        try:   # a body that is not one JSON object: said, nothing done (no traceback of the server's thread)
            n = int(self.headers.get('Content-Length') or 0)
            if not 0 <= n <= MAX_BODY:
                return self.answer(413 if n > 0 else 400, {'error': f'a body of 0 to {MAX_BODY} bytes'})
            data = json.loads(self.rfile.read(n) or b'{}')
        except (ValueError, RecursionError):
            return self.answer(400, {'error': 'not JSON'})
        if not isinstance(data, dict):
            return self.answer(400, {'error': 'not a JSON object'})
        if path == '/hello':
            self.bridge.hello(cid, data)
        elif path == '/bye':   # the page leaves (closed, reloaded)
            self.bridge.drop(cid)
        elif not self.bridge.resolve(cid, data.get('rid'), data.get('results')):   # /reply: to a command sent to this page
            return self.answer(409, {'error': 'no command of this page is waiting for that answer'})
        self.answer(200, {})


class Bridge:
    """The live link of this process: the pages connected (by their cid: path, title, viewers, a queue of commands) and
    the commands waiting for their answer."""

    def __init__(self, port=None, token=None):
        self.token, self.closed, self.clients, self.pending, self.rid = token or live_token(), False, {}, {}, 0
        self.lock, self.changed = threading.Lock(), threading.Condition()
        handler = type('Handler', (LiveHandler,), {'bridge': self})
        first = port if port is not None else int(os.environ.get('WAVELENS_LIVE_PORT') or LIVE_PORT)
        for p in [first] if port is not None else range(first, first + 10):
            try:
                self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', p), handler)
                break
            except OSError:
                continue
        else:
            raise WaveError(f'the live link: no free port from {first} on (WAVELENS_LIVE_PORT)')
        self.httpd.daemon_threads = True
        self.httpd.handle_error = lambda request, addr: print(f'wavemcp: the live link: {sys.exc_info()[1]!r} ({addr[0]})', file=sys.stderr)
        self.port, self.started = self.httpd.server_address[1], time.monotonic()
        self.waited = False   # a dump's tab waited for once (its first view tool): an error need not cost 5 s each time
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.announce()

    def announce(self):
        """~/.cache/wavelens/live/<port>.json while this link runs: the VS Code extension's tabs connect to it (vscode/)."""
        d = os.path.join(cache_dir(), 'live')
        self.note = os.path.join(d, f'{self.port}.json')
        try:
            os.makedirs(d, exist_ok=True)
            with open(self.note, 'w', encoding='utf-8') as f:
                json.dump({'port': self.port, 'pid': os.getpid(), 'host': socket.gethostname(), 'started': time.time()}, f)
            atexit.register(self.unannounce)
        except OSError:
            self.note = None

    def unannounce(self):
        if self.note:
            with contextlib.suppress(OSError):
                os.remove(self.note)
            self.note = None

    def close(self):
        self.closed = True
        self.unannounce()
        for c in list(self.clients.values()):
            c['q'].put(None)
        self.httpd.shutdown()
        self.httpd.server_close()

    def attach(self, cid):
        with self.lock:
            old = self.clients.get(cid)
            if old:
                old['q'].put(None)
            self.clients[cid] = {'cid': cid, 'q': queue.Queue(), 'path': (old or {}).get('path'), 'title': (old or {}).get('title', ''),
                                 'url': (old or {}).get('url', ''), 'views': (old or {}).get('views', []), 'at': time.monotonic()}
            return self.clients[cid]['q']

    def detach(self, cid, q):
        with self.lock:
            if cid in self.clients and self.clients[cid]['q'] is q:
                del self.clients[cid]
        with self.changed:
            self.changed.notify_all()

    def drop(self, cid):
        with self.lock:
            c = self.clients.pop(cid, None)
        if c:
            c['q'].put(None)
        with self.changed:
            self.changed.notify_all()

    def hello(self, cid, data):
        with self.lock:
            c = self.clients.get(cid)
            if c:
                c.update(path=str(data.get('path') or ''), url=str(data.get('url') or ''), title=str(data.get('title') or ''),
                         views=[v for v in data['views'] if isinstance(v, dict)] if isinstance(data.get('views'), list) else [], at=time.monotonic())
        with self.changed:
            self.changed.notify_all()

    def pages(self):
        """The connected pages that said who they are, the latest first."""
        with self.lock:
            return sorted((dict(c) for c in self.clients.values() if c.get('path') is not None), key=lambda c: -c['at'])

    def wait(self, test, timeout):
        """Until test() is true (a page connected), at most timeout s -> its value."""
        end = time.monotonic() + timeout
        with self.changed:
            while True:
                got = test()
                left = end - time.monotonic()
                if got or left <= 0:
                    return got
                self.changed.wait(left)

    def send(self, cid, view, ops, timeout=10):
        """The commands to a page's viewer -> their results (view.run), or a WaveError (LiveGone: no answer, the page is
        taken for gone)."""
        with self.lock:
            c = self.clients.get(cid)
            if not c:
                raise WaveError('the page went (closed or reloaded): view_get lists the pages connected')
            self.rid += 1
            rid, ev = self.rid, threading.Event()
            self.pending[rid] = [ev, None, cid]   # answered by this page only
            c['q'].put({'rid': rid, 'view': view, 'ops': ops})
        if not ev.wait(timeout):
            self.pending.pop(rid, None)
            self.drop(cid)
            raise LiveGone(f'the live page did not answer in {timeout} s (its tab closed?)')
        got = self.pending.pop(rid)[1]
        if isinstance(got, dict) and got.get('error'):
            raise WaveError(str(got['error']))
        if not isinstance(got, list) or len(got) != len(ops):
            raise WaveError(f'the live page answered {json.dumps(got)[:200]}, not a result per command')
        return got

    def resolve(self, cid, rid, results):
        """A page's answer to command rid -> whether it was one sent to that page and not answered yet."""
        with self.lock:
            p = self.pending.get(rid) if isinstance(rid, int) and not isinstance(rid, bool) else None
            if not p or p[2] != cid or p[0].is_set():
                return False
            p[1] = results
            p[0].set()
        return True


class LiveGone(WaveError):
    pass


def bridge():
    if not BRIDGE:
        BRIDGE.append(Bridge())
    return BRIDGE[0]


def same_file(page_path, browser_path):
    """A page's path here and the path a browser has of it (file:///C:/…, /mnt/c/…, //wsl.localhost/<distro>/…)."""
    def norm(p):
        p = urllib.parse.unquote(str(p)).replace('\\', '/')
        m = re.match(r'^/?([a-zA-Z]):/(.*)$', p)
        if m:
            p = f'/mnt/{m.group(1).lower()}/{m.group(2)}'
        d = os.environ.get('WSL_DISTRO_NAME')
        if d and p.lower().startswith(f'/{d.lower()}/'):
            p = p[len(d) + 1:]
        p = os.path.normcase(os.path.normpath(p))
        return p.lower() if re.match(r'^/mnt/[a-z]/', p, re.I) else p   # a Windows drive (WSL) ignores case, Linux does not
    return norm(page_path) == norm(browser_path)


def page_arg(a):
    p = a.get('page')
    return os.path.abspath(os.path.expanduser(str(p))) if p else None


def live_page(a, wait=0.0):
    """The connected page the arguments name (page: its file; none: the only one) -> its client, or None."""
    if not BRIDGE:
        return None
    path = page_arg(a)
    pick = lambda: [c for c in BRIDGE[0].pages() if same_file(path, c['path'])] if path else BRIDGE[0].pages()
    got = BRIDGE[0].wait(pick, wait) if wait else pick()
    if not got:
        return None
    if not path and len({c['path'] for c in got}) > 1:
        raise WaveError('several pages are live: give "page" (' + ', '.join(sorted({os.path.basename(c['path']) for c in got})) + ')')
    return got[0]


def live_view(c, view):
    """The viewer of a live page: the one named, else the only one -> its {key, timed, …}."""
    vs = c.get('views') or []
    if view:
        v = next((v for v in vs if v.get('key') == view), None)
        if not v:
            raise WaveError(f'no view "{view}" in the live page ({", ".join(x.get("key", "") for x in vs)})')
        return v
    if len(vs) != 1:
        raise WaveError(f'the live page has {len(vs)} views: give "view" (' + ', '.join(x.get('key', '') for x in vs) + ')')
    return vs[0]


DUMP_RE = re.compile(r'\.(vcd|fst)$', re.I)   # a dump open in a tab of VS Code (vscode/): live only, no file to write into


def vscode_open(path, port):
    """A dump in a wavelens tab of the VS Code windows of this host (vscode/ watches ~/.cache/wavelens/live), connected to
    the bridge on port -> asked."""
    d = os.path.join(cache_dir(), 'live')
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f'open-{time.time_ns()}-{os.getpid()}.json')
        with open(p + '.part', 'w', encoding='utf-8') as f:
            json.dump({'path': path, 'port': port, 'host': socket.gethostname(), 'at': int(time.time() * 1000)}, f)
        os.replace(p + '.part', p)
        return True
    except OSError:
        return False


def open_browser(path):
    """The page in the person's browser (WSL: the Windows one) -> whether it was handed over."""
    cands = []
    if shutil.which('wslview'):
        cands.append(['wslview', path])
    if shutil.which('explorer.exe') and shutil.which('wslpath'):
        try:
            cands.append(['explorer.exe', subprocess.run(['wslpath', '-w', path], capture_output=True, text=True, timeout=5,
                                                         stdin=subprocess.DEVNULL).stdout.strip()])
        except (OSError, subprocess.SubprocessError):
            pass
    for opener in ('xdg-open', 'open'):
        if shutil.which(opener):
            cands.append([opener, path])
    for cmd in cands:
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # not the protocol's stdin
            return True
        except OSError:
            continue
    return False


def has_live_block(path):
    try:
        with open(path, encoding='utf-8') as f:
            return bool(wavepage.LIVE_RE.search(f.read()))
    except OSError:
        return False


def target(a):
    """Where the view tools work: ('live', client, viewer) or ('file', path, None). A page that carries the live link
    gets a moment to connect when the link has just started (with the first view tool of this server)."""
    path = page_arg(a)
    if path and not os.path.isfile(path):
        raise WaveError(f'no such page: {path}')
    if path and DUMP_RE.search(path):   # a dump: its tab in VS Code, or nothing
        b = bridge()   # the extension's tabs connect within a few seconds of its start: waited for once
        c = live_page(a, wait=0 if b.waited else max(0.0, 5 - (time.monotonic() - b.started)))
        b.waited = True
        if not c:
            raise WaveError(f'{os.path.basename(path)} is not open in VS Code (WaveLens): view_live with page and open: true opens it there')
        return 'live', c, live_view(c, a.get('view'))
    linked = bool(path) and has_live_block(path)
    if linked and not BRIDGE:
        bridge()
    c = live_page(a, wait=max(0.0, 3 - (time.monotonic() - BRIDGE[0].started)) if linked else 0)
    if c:
        return 'live', c, live_view(c, a.get('view'))
    if not path:
        raise WaveError('"page" is required: the .html (wave_page, make html) — no page is live (view_live connects one)')
    return 'file', path, None
