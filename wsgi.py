"""WSGI entry point: gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app"""
import os
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    if os.path.exists('.env'):
        for line in open('.env', encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from tse import create_app
app = create_app()
