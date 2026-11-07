"""Lettura di documenti (txt, md, docx, pdf) e utilità di testo."""
import os
import re
import shutil
import sys
from pathlib import Path


def leggi_testo(path) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".docx":
        from docx import Document
        d = Document(str(p))
        parti = [x.text for x in d.paragraphs]
        for t in d.tables:
            for r in t.rows:
                parti.append(" | ".join(c.text for c in r.cells))
        return "\n".join(parti)
    if ext == ".pdf":
        import pymupdf
        with pymupdf.open(str(p)) as d:
            return "\n".join(pg.get_text() for pg in d)
    raise ValueError(f"Formato non supportato: {ext}")


def spezza_testo(testo: str, parole: int = 220) -> list:
    """Divide un testo lungo in pezzi di circa `parole` parole (per cercare esempi di stile)."""
    pars = [x.strip() for x in testo.splitlines() if x.strip()]
    pezzi, cur, n = [], [], 0
    for p in pars:
        w = len(p.split())
        if cur and n + w > parole:
            pezzi.append("\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        pezzi.append("\n".join(cur))
    return [p for p in pezzi if len(p.split()) >= 30]


def trova_soffice():
    """Restituisce il percorso di LibreOffice se installato, altrimenti None."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if exe:
        return exe
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac.exists():
        return str(mac)
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
        if base:
            c = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if c.exists():
                return str(c)
    return None


def cartella_documenti() -> Path:
    """Cartella "Documenti" vera dell'utente (anche se rinominata o spostata su OneDrive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"
