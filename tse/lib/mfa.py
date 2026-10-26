"""Two-step verification (TOTP, RFC 6238) — works with Google Authenticator, Microsoft Authenticator, Authy, 1Password.

Mandatory for The School Expert™ staff and admins; optional (recommended) for school / vendor owners and everyone else.
The shared secret is stored AES-256-GCM encrypted; recovery codes are stored as hashes only.
"""
import base64, hashlib, hmac, os, secrets, struct, time, urllib.parse
from ..db import db
from .security import encrypt_json, decrypt_json, token_hash

def new_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip('=')

def _code(secret, counter):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    h = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000).zfill(6)

def verify(secret, code, window=1, last_counter=None):
    """Returns the matched time-step (so a code cannot be replayed) or None."""
    code = ''.join(ch for ch in (code or '') if ch.isdigit())
    if len(code) != 6: return None
    now = int(time.time() // 30)
    for c in range(now - window, now + window + 1):
        if last_counter is not None and c <= last_counter: continue
        if hmac.compare_digest(_code(secret, c), code): return c
    return None

def provisioning_uri(secret, email):
    label = urllib.parse.quote(f'The School Expert:{email}')
    return f'otpauth://totp/{label}?secret={secret}&issuer=The%20School%20Expert&algorithm=SHA1&digits=6&period=30'

def user_secret(u):
    return decrypt_json(u['mfa_secret_enc']).get('s') if u.get('mfa_secret_enc') else None

def enable(user_id, secret):
    codes = [secrets.token_hex(4) + '-' + secrets.token_hex(4) for _ in range(10)]
    db.run('UPDATE users SET mfa_secret_enc = %s, mfa_enabled = true, mfa_recovery_hashes = %s WHERE id = %s',
           encrypt_json({'s': secret, 'last': 0}), [token_hash(c) for c in codes], user_id)
    return codes

def disable(user_id):
    db.run("UPDATE users SET mfa_secret_enc = NULL, mfa_enabled = false, mfa_recovery_hashes = '{}' WHERE id = %s", user_id)

def check(u, code):
    """Verify a TOTP or a one-time recovery code for user row u."""
    data = decrypt_json(u['mfa_secret_enc']) if u.get('mfa_secret_enc') else {}
    if data.get('s'):
        step = verify(data['s'], code, last_counter=data.get('last'))
        if step:
            data['last'] = step
            db.run('UPDATE users SET mfa_secret_enc = %s WHERE id = %s', encrypt_json(data), u['id'])
            return True
    h = token_hash((code or '').strip().lower())
    if h in (u.get('mfa_recovery_hashes') or []):
        db.run('UPDATE users SET mfa_recovery_hashes = array_remove(mfa_recovery_hashes, %s) WHERE id = %s', h, u['id'])
        return True
    return False

def required_for(u):
    return u['account_type'] in ('admin', 'staff')
