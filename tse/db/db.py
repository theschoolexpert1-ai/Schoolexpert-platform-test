"""Database access: tiny connection pool + helpers. SQL uses %s placeholders (converted to $n)."""
import os, re, threading, queue, contextlib, time, urllib.parse
from . import pgwire
from .pgwire import Json, Error, IntegrityError

_pool = None
_lock = threading.Lock()

def _conn_args(url):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    args = dict(host=u.hostname or 'localhost', port=u.port or 5432, user=urllib.parse.unquote(u.username or 'postgres'),
                password=urllib.parse.unquote(u.password or ''), database=(u.path or '/').lstrip('/') or None,
                sslmode=q.get('sslmode', 'prefer'))
    if q.get('host', '').startswith('/'):
        args['unix_socket'] = os.path.join(q['host'], f".s.PGSQL.{args['port']}")
    return args

class Pool:
    def __init__(self, url, size=10):
        self.args = _conn_args(url); self.size = size
        self.q = queue.LifoQueue(); self.created = 0
    def get(self):
        try:
            c = self.q.get_nowait()
            return c
        except queue.Empty:
            with _lock:
                if self.created < self.size:
                    self.created += 1
                    try:
                        return pgwire.Connection(**self.args)
                    except Exception:
                        self.created -= 1; raise
            return self.q.get(timeout=30)
    def put(self, c, broken=False):
        if broken:
            with _lock: self.created -= 1
            c.close(); return
        if c.in_tx:
            c._tse_ctx = None
            try: c.simple('ROLLBACK')
            except Exception:
                with _lock: self.created -= 1
                return
        self.q.put(c)

def init(url, size=10):
    global _pool
    _pool = Pool(url, size)

_PH = re.compile(r"%s|%%")
def _convert(sql):
    n = [0]
    def rep(m):
        if m.group(0) == '%%': return '%'
        n[0] += 1; return f'${n[0]}'
    return _PH.sub(rep, sql)

class Row(dict):
    __getattr__ = dict.get

_local = threading.local()

@contextlib.contextmanager
def connection():
    c = getattr(_local, 'conn', None)
    if c is not None:
        yield c; return
    c = _pool.get(); broken = False
    _local.conn = c
    try:
        yield c
    except (OSError, pgwire.Error) as e:
        broken = isinstance(e, OSError); raise
    finally:
        _local.conn = None
        _pool.put(c, broken)

@contextlib.contextmanager
def transaction():
    """Nested-safe transaction scope bound to the current thread."""
    depth = getattr(_local, 'depth', 0)
    with connection() as c:
        if depth == 0: c.simple('BEGIN')
        _local.depth = depth + 1
        _local.conn = c
        try:
            yield c
            if depth == 0: c.simple('COMMIT')
        except BaseException:
            if depth == 0:
                try: c.simple('ROLLBACK')
                except Exception: pass
                c._tse_ctx = None          # settings made inside the rolled-back transaction are undone
            raise
        finally:
            _local.depth = depth
            if depth == 0: _local.conn = None

# ---------------- row-level-security context ----------------
_ctx_provider = None
def set_context_provider(fn):
    """fn() -> (bypass 'on'|'off', user_id str, org_ids 'a,b') for the current request; installed by the app."""
    global _ctx_provider
    _ctx_provider = fn

@contextlib.contextmanager
def elevated():
    """Trusted server-side work that legitimately spans tenants (payment fulfilment, notifications, scheduled jobs).
    Never wrap code that echoes data back to the requester."""
    _local.elevated = getattr(_local, 'elevated', 0) + 1
    try: yield
    finally: _local.elevated -= 1

def _context():
    if getattr(_local, 'elevated', 0): return ('on', '', '')
    return _ctx_provider() if _ctx_provider else ('on', '', '')

_SET_CTX = "SELECT set_config('app.bypass', $1, false), set_config('app.user_id', $2, false), set_config('app.org_ids', $3, false)"
def _apply_ctx(c):
    ctx = _context()
    if getattr(c, '_tse_ctx', None) != ctx:
        c.execute(_SET_CTX, ctx)
        c._tse_ctx = ctx

def _run(sql, params):
    with connection() as c:
        _apply_ctx(c)
        return c.execute(_convert(sql), params)

def all(sql, *params):
    cols, rows, _ = _run(sql, params)
    return [Row(zip(cols, r)) for r in rows]

def one(sql, *params):
    r = all(sql, *params)
    return r[0] if r else None

def val(sql, *params):
    cols, rows, _ = _run(sql, params)
    return rows[0][0] if rows else None

def run(sql, *params):
    return _run(sql, params)[2]

def script(sql):
    with connection() as c:
        c.simple(sql)

def insert(table, data, returning='id'):
    keys = list(data.keys())
    sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})" + (f' RETURNING {returning}' if returning else '')
    vals = [Json(v) if isinstance(v, (dict, list)) and _is_json_col(k) else v for k, v in data.items()]
    return val(sql, *vals) if returning else run(sql, *vals)

def update(table, where_id, data, key='id'):
    if not data: return 0
    sets = ', '.join(f'{k} = %s' for k in data)
    vals = [Json(v) if isinstance(v, (dict, list)) and _is_json_col(k) else v for k, v in data.items()]
    return run(f'UPDATE {table} SET {sets} WHERE {key} = %s', *vals, where_id)

# columns that hold jsonb (so lists are sent as JSON rather than arrays)
JSON_COLS = {'answers', 'definition', 'meta', 'grants', 'features', 'data', 'bulk_tiers', 'payload', 'public_data', 'detailed_data',
             'cv_json', 'cv_snapshot', 'checks', 'value', 'files', 'raw', 'address', 'postal_address', 'prefs', 'nominee', 'billing',
             'settings', 'guardian', 'attribution', 'prefs_json'}
def _is_json_col(k):
    return k in JSON_COLS
