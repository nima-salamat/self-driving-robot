"""Backward-compatible access to the extracted Stream editor Jinja template."""
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "stream.html"
HTML_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
