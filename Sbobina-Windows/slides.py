"""Estrazione di testo e immagini dalle slide (PDF o PPTX)."""
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from documenti import trova_soffice


@dataclass
class Slide:
    n: int
    testo: str
    gid: int = 0               # numero progressivo su tutte le slide caricate
    fonte: str = ""
    visuale: bool = False      # contiene figure / schemi / tabelle
    pdf: str = ""              # PDF da cui renderizzare la slide
    pagina: int = -1
    img_bytes: bytes = b""     # immagine incorporata (solo fallback PPTX)
    ext: str = "png"
    id: int = 0                # numero progressivo globale (assegnato dalla pipeline)


def estrai_slide(path, work_dir) -> list:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _da_pdf(str(path))
    if ext == ".pptx":
        pdf = _pptx_a_pdf(str(path), work_dir)
        return _da_pdf(pdf, fonte=Path(path).stem) if pdf else _da_pptx(str(path))
    raise ValueError(f"Formato slide non supportato: {ext}")


def _da_pdf(path: str, fonte: str = "") -> list:
    import pymupdf
    fonte = fonte or Path(path).stem
    out = []
    with pymupdf.open(path) as doc:
        n_pag = len(doc)
        infos, conteggio = [], Counter()
        for page in doc:
            area = max(page.rect.width * page.rect.height, 1)
            imgs = []
            for im in page.get_image_info(xrefs=True):
                b = pymupdf.Rect(im["bbox"])
                imgs.append((im.get("xref", 0), (b.width * b.height) / area))
            conteggio.update({x for x, _ in imgs})
            infos.append(imgs)
        for i, page in enumerate(doc):
            # figure "vere": né sfondi a pagina intera né loghi ripetuti su molte slide
            util = [f for x, f in infos[i]
                    if 0.04 <= f <= 0.85 and conteggio[x] <= max(2, 0.3 * n_pag)]
            try:
                n_draw = len(page.get_drawings())
            except Exception:
                n_draw = 0
            out.append(Slide(
                n=i + 1, testo=page.get_text().strip(), fonte=fonte,
                visuale=bool(util) or n_draw >= 20, pdf=path, pagina=i,
            ))
    return out


def _pptx_a_pdf(path: str, work_dir):
    exe = trova_soffice()
    if not exe:
        return None
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(work), path],
                       capture_output=True, timeout=300, creationflags=flags)
    except Exception:
        return None
    pdf = work / (Path(path).stem + ".pdf")
    return str(pdf) if pdf.exists() else None


def _da_pptx(path: str) -> list:
    """Fallback senza LibreOffice: testo + immagine incorporata più grande di ogni slide."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    prs = Presentation(path)
    area_slide = max(prs.slide_width * prs.slide_height, 1)
    fonte = Path(path).stem
    out = []
    for i, slide in enumerate(prs.slides, 1):
        testi, best = [], [None]

        def visita(shapes):
            for sh in shapes:
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    visita(sh.shapes)
                    continue
                if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                    testi.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for r in sh.table.rows:
                        testi.append(" ".join(c.text for c in r.cells))
                if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    frac = (sh.width * sh.height) / area_slide
                    ext = sh.image.ext.lower()
                    if frac >= 0.04 and ext in ("png", "jpg", "jpeg", "gif", "bmp"):
                        if best[0] is None or frac > best[0][0]:
                            best[0] = (frac, sh.image.blob, ext)

        visita(slide.shapes)
        s = Slide(n=i, testo="\n".join(t for t in testi if t.strip()), fonte=fonte)
        if best[0]:
            s.visuale, s.img_bytes, s.ext = True, best[0][1], best[0][2]
        out.append(s)
    return out


def salva_immagine(slide: Slide, out_dir, dpi: int = 110):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^\w\-]+", "_", slide.fonte) or "slide"
    f = out / f"{nome}_{getattr(slide, 'id', slide.n):03d}.{slide.ext}"
    if slide.img_bytes:
        f.write_bytes(slide.img_bytes)
    elif slide.pdf:
        import pymupdf
        with pymupdf.open(slide.pdf) as d:
            d[slide.pagina].get_pixmap(dpi=dpi).save(str(f))
    else:
        return None
    return str(f)
