"""Vercel entry point: every request is rewritten here (see vercel.json)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tse import create_app
app = create_app()
