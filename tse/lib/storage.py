"""File storage. Local disk today; S3-compatible object storage after cloud migration (same interface).

Public files (logos, photos) -> served at /media/<path>.
Private files (certificates, ID/registration documents, CVs) -> never public; streamed through an
authorised route after a permission check (DPDP: purpose limitation + access control).
"""
import os, uuid, io, mimetypes, datetime, hashlib, hmac
from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED = {
    'image': {'.jpg', '.jpeg', '.png', '.webp', '.gif'},
    'doc': {'.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt'},
    'video': {'.mp4', '.mov', '.webm'},
}
ALL_EXT = set().union(*ALLOWED.values())

class UploadError(ValueError):
    pass

def _kind(ext):
    for k, v in ALLOWED.items():
        if ext in v: return k
    return None

def _sniff_ok(head, ext):
    sigs = {'.pdf': [b'%PDF'], '.png': [b'\x89PNG'], '.jpg': [b'\xff\xd8'], '.jpeg': [b'\xff\xd8'], '.gif': [b'GIF8'],
            '.webp': [b'RIFF'], '.docx': [b'PK'], '.pptx': [b'PK'], '.xlsx': [b'PK'], '.doc': [b'\xd0\xcf'], '.ppt': [b'\xd0\xcf'], '.xls': [b'\xd0\xcf']}
    return ext not in sigs or any(head.startswith(s) for s in sigs[ext])

def _active_content(data, ext):
    """Reject documents that can run code: PDF JavaScript/launch actions/embedded files, Office macros, zip bombs."""
    if ext == '.pdf':
        low = data[:20_000_000]
        for marker in (b'/JavaScript', b'/JS ', b'/JS(', b'/Launch', b'/EmbeddedFile', b'/RichMedia', b'/XFA'):
            if marker in low: return 'PDFs with scripts, embedded files or launch actions are not accepted. Please “Print to PDF” and upload again.'
    if ext in ('.docx', '.pptx', '.xlsx'):
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist(); total = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile:
            return 'That document appears to be damaged.'
        if total > 150 * 1024 * 1024 or len(names) > 5000: return 'That document is too large when unpacked.'
        if any(n.lower().endswith(('vbaproject.bin', '.bin')) and 'vba' in n.lower() for n in names) or any('activex' in n.lower() for n in names):
            return 'Documents with macros or ActiveX controls are not accepted. Please save as a normal .docx/.pptx/.xlsx or PDF.'
    if ext in ('.doc', '.ppt', '.xls') and (b'V\x00B\x00A\x00' in data or b'_VBA_PROJECT' in data or b'Macros' in data):
        return 'Documents with macros are not accepted. Please upload a PDF instead.'
    return None

def _virus_scan(data):
    """Optional ClamAV scan (set CLAMD_HOST / CLAMD_PORT, e.g. 127.0.0.1:3310). Fails closed when configured but unreachable."""
    host = current_app.config.get('CLAMD_HOST')
    if not host: return None
    import socket, struct
    try:
        with socket.create_connection((host, int(current_app.config.get('CLAMD_PORT') or 3310)), timeout=20) as sck:
            sck.sendall(b'zINSTREAM\0')
            for i in range(0, len(data), 65536):
                chunk = data[i:i + 65536]; sck.sendall(struct.pack('>I', len(chunk)) + chunk)
            sck.sendall(struct.pack('>I', 0))
            reply = sck.recv(4096).decode(errors='replace')
    except OSError:
        return 'Our virus scanner is unavailable — please try again in a few minutes.'
    return None if reply.strip().endswith('OK') else 'This file was flagged by our virus scanner and was not accepted.'

def _clean_image(data, ext):
    """Re-encode images: strips EXIF (incl. GPS location) and caps dimensions."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(data)); im = ImageOps.exif_transpose(im)
        im.thumbnail((1800, 1800))
        out = io.BytesIO()
        fmt = 'PNG' if ext == '.png' else 'WEBP' if ext == '.webp' else 'GIF' if ext == '.gif' else 'JPEG'
        if fmt == 'JPEG' and im.mode not in ('RGB', 'L'): im = im.convert('RGB')
        im.save(out, fmt, quality=85, optimize=True)
        return out.getvalue()
    except Exception:
        raise UploadError('That image could not be read. Please upload a JPG or PNG.')

def save(file_storage, private=False, folder='misc', kinds=('image', 'doc'), allow_ext=None):
    if not file_storage or not file_storage.filename: return None
    name = secure_filename(file_storage.filename) or 'file'
    ext = os.path.splitext(name)[1].lower()
    if _kind(ext) not in kinds:
        raise UploadError(f'File type {ext or "(none)"} is not allowed here.')
    if allow_ext and ext.lstrip('.') not in {x.lower().lstrip('.') for x in allow_ext} | ({'jpeg'} if 'jpg' in allow_ext else set()):
        raise UploadError('Allowed file types: ' + ', '.join(x.upper() for x in allow_ext) + '.')
    data = file_storage.read()
    if not data: raise UploadError('The uploaded file is empty.')
    if not _sniff_ok(data[:8], ext): raise UploadError('The file content does not match its extension.')
    problem = _active_content(data, ext) or _virus_scan(data)
    if problem: raise UploadError(problem)
    if _kind(ext) == 'image': data = _clean_image(data, ext)
    if private:   # private documents (IDs, certificates, CVs) are encrypted at rest with AES-256-GCM
        from .security import encrypt_bytes
        stored = encrypt_bytes(data)
    else:
        stored = data
    stamp = datetime.date.today().strftime('%Y/%m')
    rel = f'{folder}/{stamp}/{uuid.uuid4().hex}{ext}'
    backend = current_app.config['STORAGE_BACKEND']
    if backend == 's3':
        _s3_put(rel, stored, private)
    elif backend == 'db':
        from ..db import db
        with db.elevated():
            db.run('INSERT INTO blobs (key, private, mime, size, data) VALUES (%s,%s,%s,%s,%s)', rel, private,
                   mimetypes.guess_type(name)[0] or 'application/octet-stream', len(stored), stored)
    else:
        root = current_app.config['PRIVATE_UPLOAD_DIR' if private else 'UPLOAD_DIR']
        path = os.path.join(root, rel); os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f: f.write(stored)
    return {'url': (f'private:{rel}' if private else f'/media/{rel}'), 'name': name, 'size': len(data), 'private': private}

def private_path(ref):
    rel = ref.split(':', 1)[1]
    root = os.path.realpath(current_app.config['PRIVATE_UPLOAD_DIR'])
    p = os.path.realpath(os.path.join(root, rel))
    if not p.startswith(root + os.sep): raise UploadError('bad path')
    return p

def _s3_put(key, data, private):
    _s3_request('PUT', ('private/' if private else 'public/') + key, data)

def read_private(ref):
    """Bytes of a private upload, from local disk or object storage."""
    rel = ref.split(':', 1)[1]
    from .security import decrypt_bytes
    if current_app.config['STORAGE_BACKEND'] == 'db':
        from ..db import db
        with db.elevated():
            row = db.one('SELECT data FROM blobs WHERE key = %s AND private', rel)
        if not row: raise UploadError('missing file')
        return decrypt_bytes(bytes(row['data']))
    if current_app.config['STORAGE_BACKEND'] == 's3':
        return decrypt_bytes(_s3_request('GET', 'private/' + rel))
    with open(private_path(ref), 'rb') as f:
        return decrypt_bytes(f.read())

def _s3_request(method, key, data=b''):
    """Minimal AWS SigV4 request so no SDK is required. Works with AWS S3 (ap-south-1), DO Spaces, Wasabi, MinIO."""
    import requests
    cfg = current_app.config
    host = cfg['S3_ENDPOINT'].replace('https://', '') or f"{cfg['S3_BUCKET']}.s3.{cfg['S3_REGION']}.amazonaws.com"
    now = datetime.datetime.utcnow(); amz = now.strftime('%Y%m%dT%H%M%SZ'); day = now.strftime('%Y%m%d')
    payload_hash = hashlib.sha256(data).hexdigest()
    headers = {'host': host, 'x-amz-content-sha256': payload_hash, 'x-amz-date': amz}
    if method == 'PUT':
        headers['content-type'] = mimetypes.guess_type(key)[0] or 'application/octet-stream'
        headers['x-amz-server-side-encryption'] = 'AES256'
    signed = ';'.join(sorted(headers))
    canon = '\n'.join([method, '/' + key, '', ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers)), signed, payload_hash])
    scope = f"{day}/{cfg['S3_REGION']}/s3/aws4_request"
    sts = '\n'.join(['AWS4-HMAC-SHA256', amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
    def h(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()
    k = h(h(h(h(('AWS4' + cfg['S3_SECRET_KEY']).encode(), day), cfg['S3_REGION']), 's3'), 'aws4_request')
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = f"AWS4-HMAC-SHA256 Credential={cfg['S3_ACCESS_KEY']}/{scope}, SignedHeaders={signed}, Signature={sig}"
    r = requests.request(method, f'https://{host}/{key}', data=data or None, headers=headers, timeout=60)
    if r.status_code >= 300: raise UploadError(f'Object storage error {r.status_code}')
    return r.content


def read_public(rel):
    """(bytes, mime) of a public upload for /media/<path> when files live in the database or object storage."""
    from ..db import db
    if current_app.config['STORAGE_BACKEND'] == 'db':
        row = db.one('SELECT data, mime FROM blobs WHERE key = %s AND NOT private', rel)
        return (bytes(row['data']), row['mime']) if row else (None, None)
    if current_app.config['STORAGE_BACKEND'] == 's3':
        return _s3_request('GET', 'public/' + rel), mimetypes.guess_type(rel)[0] or 'application/octet-stream'
    return None, None
