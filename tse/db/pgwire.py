"""Minimal pure-Python PostgreSQL client (protocol v3).

Why: keeps deployment free of compiled drivers (GoDaddy VPS / shared hosts), while still
using the *extended query protocol* so every value is sent as a bound parameter
(no client-side string interpolation, no SQL injection surface).

Supports: TCP or Unix socket, SSL (sslmode=require/verify-full), auth trust / cleartext /
md5 / SCRAM-SHA-256, transactions, text-format results converted by type OID.
"""
import socket, struct, hashlib, hmac, base64, os, ssl, json, datetime, decimal, uuid, re

class Error(Exception):
    def __init__(self, fields):
        self.fields = fields
        self.code = fields.get('C')
        super().__init__(f"{fields.get('S', 'ERROR')} {fields.get('C', '')}: {fields.get('M', '')}" + (f" ({fields.get('D')})" if fields.get('D') else ''))

class IntegrityError(Error):
    pass

# ---------- type conversion ----------
def _ts(v):
    v = v.replace(' ', 'T')
    if v.endswith(('+00', '-00')) or re.search(r'[+-]\d\d$', v):
        v += ':00'
    if 'infinity' in v: return None
    try:
        return datetime.datetime.fromisoformat(v)
    except ValueError:
        # fractional seconds with odd length
        m = re.match(r'(.*\.)(\d+)(.*)', v)
        if m:
            return datetime.datetime.fromisoformat(m.group(1) + m.group(2).ljust(6, '0')[:6] + m.group(3))
        raise

def _parse_array(s, conv):
    # handles 1-D arrays of scalars (text, int, uuid) — sufficient for this application
    if s == '{}': return []
    inner = s[1:-1]
    out, cur, i, quoted = [], '', 0, False
    while i < len(inner):
        ch = inner[i]
        if quoted:
            if ch == '\\': cur += inner[i + 1]; i += 2; continue
            if ch == '"': quoted = False; i += 1; continue
            cur += ch
        else:
            if ch == '"': quoted = True; cur = cur or ''; i += 1; continue
            if ch == ',': out.append(cur); cur = ''; i += 1; continue
            cur += ch
        i += 1
    out.append(cur)
    return [None if x == 'NULL' else conv(x) for x in out]

CONVERTERS = {
    16: lambda v: v == 't',                 # bool
    20: int, 21: int, 23: int, 26: int,     # int8 int2 int4 oid
    700: float, 701: float,                 # float4 float8
    1700: decimal.Decimal,                  # numeric
    114: json.loads, 3802: json.loads,      # json jsonb
    1082: datetime.date.fromisoformat,      # date
    1114: _ts, 1184: _ts,                   # timestamp, timestamptz
    2950: str,                              # uuid kept as str for templates/urls
}
ARRAY_OF = {1000: 16, 1005: 21, 1007: 23, 1016: 20, 1009: 25, 1015: 25, 2951: 2950, 1021: 700, 1022: 701, 1231: 1700}

def convert(oid, raw):
    if raw is None: return None
    if oid == 17:                                   # bytea (hex output format, the default since PG 9.0)
        return bytes.fromhex(raw[2:].decode()) if raw[:2] == b'\\x' else raw
    v = raw.decode('utf-8')
    if oid in ARRAY_OF:
        return _parse_array(v, CONVERTERS.get(ARRAY_OF[oid], str))
    f = CONVERTERS.get(oid)
    return f(v) if f else v

def encode_param(v):
    """Python value -> text-format bytes (or None for NULL)."""
    if v is None: return None
    if isinstance(v, bool): return b't' if v else b'f'
    if isinstance(v, (int, float, decimal.Decimal)): return str(v).encode()
    if isinstance(v, (datetime.datetime, datetime.date)): return v.isoformat().encode()
    if isinstance(v, uuid.UUID): return str(v).encode()
    if isinstance(v, (dict,)): return json.dumps(v, default=str).encode()
    if isinstance(v, (list, tuple)):
        if all(isinstance(x, (dict, list)) for x in v) and v:
            return json.dumps(v, default=str).encode()
        parts = []
        for x in v:
            if x is None: parts.append('NULL'); continue
            s = str(x).replace('\\', '\\\\').replace('"', '\\"')
            parts.append('"' + s + '"')
        return ('{' + ','.join(parts) + '}').encode()
    if isinstance(v, (bytes, bytearray, memoryview)): return b'\\x' + bytes(v).hex().encode()   # bytea hex input
    return str(v).encode()

class Json:
    """Wrap a value to send it as JSON even when it's a list."""
    def __init__(self, v): self.v = v

# ---------- connection ----------
class Connection:
    def __init__(self, host='localhost', port=5432, user='postgres', password=None, database=None,
                 sslmode='prefer', unix_socket=None, connect_timeout=10, application_name='schoolexpert'):
        self.user, self.password, self.database = user, password or '', database or user
        self.params = {}
        self.in_tx = False
        if unix_socket:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(connect_timeout)
            s.connect(unix_socket)
        else:
            s = socket.create_connection((host, int(port)), timeout=connect_timeout)
            if sslmode in ('require', 'verify-ca', 'verify-full', 'prefer'):
                s.sendall(struct.pack('!ii', 8, 80877103))
                resp = s.recv(1)
                if resp == b'S':
                    ctx = ssl.create_default_context()
                    if sslmode in ('require', 'prefer'):
                        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
                    s = ctx.wrap_socket(s, server_hostname=host)
                elif sslmode != 'prefer':
                    raise Error({'M': 'server does not support SSL'})
        s.settimeout(None)
        self.sock = s
        self._buf = b''
        self._startup(application_name)

    # low level io
    def _send(self, typ, payload=b''):
        self.sock.sendall((typ if typ else b'') + struct.pack('!i', len(payload) + 4) + payload)

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buf)))
            if not chunk: raise Error({'M': 'connection closed by server'})
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read(self):
        typ = self._recv_exact(1)
        ln = struct.unpack('!i', self._recv_exact(4))[0]
        return typ, self._recv_exact(ln - 4)

    @staticmethod
    def _fields(data):
        out = {}
        for part in data.split(b'\x00'):
            if part: out[chr(part[0])] = part[1:].decode('utf-8', 'replace')
        return out

    def _startup(self, appname):
        body = struct.pack('!i', 196608)
        for k, v in (('user', self.user), ('database', self.database), ('application_name', appname), ('client_encoding', 'UTF8'), ('DateStyle', 'ISO'), ('TimeZone', 'UTC')):
            body += k.encode() + b'\x00' + v.encode() + b'\x00'
        body += b'\x00'
        self.sock.sendall(struct.pack('!i', len(body) + 4) + body)
        while True:
            typ, data = self._read()
            if typ == b'R':
                code = struct.unpack('!i', data[:4])[0]
                if code == 0: continue
                if code == 3: self._send(b'p', self.password.encode() + b'\x00')
                elif code == 5:
                    salt = data[4:8]
                    inner = hashlib.md5(self.password.encode() + self.user.encode()).hexdigest()
                    self._send(b'p', b'md5' + hashlib.md5(inner.encode() + salt).hexdigest().encode() + b'\x00')
                elif code == 10: self._scram(data[4:])
                elif code in (11, 12): pass
                else: raise Error({'M': f'unsupported auth method {code}'})
            elif typ == b'S':
                k, v, _ = data.split(b'\x00', 2); self.params[k.decode()] = v.decode()
            elif typ == b'K': pass
            elif typ == b'E': raise Error(self._fields(data))
            elif typ == b'Z': return

    def _scram(self, mechs):
        if b'SCRAM-SHA-256' not in mechs: raise Error({'M': 'SCRAM-SHA-256 not offered'})
        nonce = base64.b64encode(os.urandom(18)).decode()
        first_bare = f'n=,r={nonce}'
        msg = ('n,,' + first_bare).encode()
        self._send(b'p', b'SCRAM-SHA-256\x00' + struct.pack('!i', len(msg)) + msg)
        typ, data = self._read()
        if typ == b'E': raise Error(self._fields(data))
        server_first = data[4:].decode()
        attrs = dict(x.split('=', 1) for x in server_first.split(','))
        salt, iters, rnonce = base64.b64decode(attrs['s']), int(attrs['i']), attrs['r']
        salted = hashlib.pbkdf2_hmac('sha256', self.password.encode(), salt, iters)
        client_key = hmac.new(salted, b'Client Key', 'sha256').digest()
        stored = hashlib.sha256(client_key).digest()
        final_wo_proof = f'c=biws,r={rnonce}'
        auth_msg = f'{first_bare},{server_first},{final_wo_proof}'.encode()
        sig = hmac.new(stored, auth_msg, 'sha256').digest()
        proof = base64.b64encode(bytes(a ^ b for a, b in zip(client_key, sig))).decode()
        self._send(b'p', f'{final_wo_proof},p={proof}'.encode())
        typ, data = self._read()
        if typ == b'E': raise Error(self._fields(data))
        server_key = hmac.new(salted, b'Server Key', 'sha256').digest()
        expected = base64.b64encode(hmac.new(server_key, auth_msg, 'sha256').digest()).decode()
        final = data[4:].decode()
        if f'v={expected}' != final: raise Error({'M': 'SCRAM server signature mismatch'})

    # ---------- query ----------
    def execute(self, sql, params=()):
        """Run one statement with bound parameters ($1..$n). Returns (columns, rows, rowcount)."""
        enc = [json.dumps(p.v, default=str).encode() if isinstance(p, Json) else encode_param(p) for p in params]
        q = sql.encode()
        self._send(b'P', b'\x00' + q + b'\x00' + struct.pack('!h', 0))
        bind = b'\x00\x00' + struct.pack('!h', 0) + struct.pack('!h', len(enc))
        for e in enc:
            bind += struct.pack('!i', -1) if e is None else struct.pack('!i', len(e)) + e
        bind += struct.pack('!h', 0)
        self._send(b'B', bind)
        self._send(b'D', b'P\x00')
        self._send(b'E', b'\x00' + struct.pack('!i', 0))
        self._send(b'S')
        cols, oids, rows, rowcount, err = [], [], [], -1, None
        while True:
            typ, data = self._read()
            if typ == b'T':
                n = struct.unpack('!h', data[:2])[0]; pos = 2
                for _ in range(n):
                    end = data.index(b'\x00', pos); name = data[pos:end].decode(); pos = end + 1
                    _tbl, _col, oid, _sz, _mod, _fmt = struct.unpack('!ihihih', data[pos:pos + 18]); pos += 18
                    cols.append(name); oids.append(oid)
            elif typ == b'D':
                n = struct.unpack('!h', data[:2])[0]; pos = 2; row = []
                for i in range(n):
                    ln = struct.unpack('!i', data[pos:pos + 4])[0]; pos += 4
                    if ln == -1: row.append(None)
                    else: row.append(convert(oids[i], data[pos:pos + ln])); pos += ln
                rows.append(row)
            elif typ == b'C':
                tag = data[:-1].decode().split()
                if tag and tag[-1].isdigit(): rowcount = int(tag[-1])
            elif typ == b'E':
                err = self._fields(data)
            elif typ == b'Z':
                self.in_tx = data in (b'T', b'E')
                if err:
                    raise (IntegrityError if err.get('C', '').startswith('23') else Error)(err)
                return cols, rows, rowcount
            # '1','2','n','s','N','S' ignored

    def simple(self, sql):
        """Simple-query protocol: allows multiple statements (migrations). No parameters."""
        self._send(b'Q', sql.encode() + b'\x00')
        err = None
        while True:
            typ, data = self._read()
            if typ == b'E': err = self._fields(data)
            elif typ == b'Z':
                self.in_tx = data in (b'T', b'E')
                if err: raise Error(err)
                return

    def close(self):
        try:
            self._send(b'X'); self.sock.close()
        except OSError:
            pass
