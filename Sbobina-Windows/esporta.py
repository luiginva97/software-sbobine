"""Esportazione in DOCX e PDF a partire da un elenco di blocchi.
Blocchi: ("h2", testo) ("h3", testo) ("p", testo) ("li", testo) ("nota", testo) ("img", percorso, didascalia)"""
import os
import re
import subprocess
import sys
from pathlib import Path

from documenti import trova_soffice


MARK = re.compile(r"^\[\[\s*SLIDE\s+(\d+)\s*\]\]$", re.I)


def rimuovi_avvisi(md: str):
    """Toglie le note di avviso automatiche (NOTA: ⚠️ ...). Restituisce (testo, quante)."""
    righe = md.splitlines()
    tenute = [r for r in righe if not re.match(r"^\s*NOTA\s*:\s*⚠", r)]
    return "\n".join(tenute), len(righe) - len(tenute)


def markdown_a_blocchi(md: str, slide_map=None) -> list:
    """slide_map: {id: (percorso_immagine, didascalia)} per i marcatori [[SLIDE n]]."""
    blocchi, par = [], []

    def flush():
        if par:
            blocchi.append(("p", " ".join(par)))
            par.clear()

    for riga in md.splitlines():
        r = riga.strip()
        if not r:
            flush()
            continue
        mk = MARK.match(r)
        if mk:
            flush()
            if slide_map and int(mk.group(1)) in slide_map:
                p, cap = slide_map[int(mk.group(1))]
                blocchi.append(("img", p, cap))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", r)
        if m:
            flush()
            blocchi.append(("h2" if len(m.group(1)) <= 2 else "h3", m.group(2).strip("* ")))
        elif re.match(r"^(NOTA|Nota)\s*:", r) or r.startswith(">"):
            flush()
            blocchi.append(("nota", re.sub(r"^(>|NOTA\s*:|Nota\s*:)\s*", "", r)))
        elif re.match(r"^([-•]|\*(?!\*))\s+", r) or re.match(r"^\d+[.)]\s+", r):
            flush()
            blocchi.append(("li", re.sub(r"^([-•*]|\d+[.)])\s+", "", r)))
        else:
            par.append(r)
    flush()
    return blocchi


def blocchi_a_markdown(blocchi) -> str:
    """Operazione inversa: blocchi -> testo modificabile (con marcatori [[SLIDE n]])."""
    out, prec = [], None
    for b in blocchi:
        t = b[0]
        if t == "h2":
            s = "## " + b[1]
        elif t == "h3":
            s = "### " + b[1]
        elif t == "p":
            s = b[1]
        elif t == "li":
            s = "- " + b[1]
        elif t == "nota":
            s = "NOTA: " + b[1]
        elif t == "img_ref":
            s = f"[[SLIDE {b[1]}]]"
        else:
            continue
        if out:
            out.append("\n" if (t == "li" and prec == "li") else "\n\n")
        out.append(s)
        prec = t
    return "".join(out)


# ---------------------------------------------------------------- DOCX
def _font_stile(style, nome, size=None, bold=None, italic=None):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    style.font.name = nome
    rpr = style.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(a), nome)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]
    if size:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic
    style.font.color.rgb = RGBColor(0, 0, 0)


def _runs(par, testo):
    for pezzo in re.split(r"(\*\*.+?\*\*)", testo):
        if pezzo.startswith("**") and pezzo.endswith("**") and len(pezzo) > 4:
            par.add_run(pezzo[2:-2]).bold = True
        elif pezzo:
            par.add_run(pezzo)


def _numero_pagina(section):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tipo, testo in (("begin", None), ("instr", "PAGE"), ("end", None)):
        if tipo == "instr":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = testo
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        run._r.append(el)


def scrivi_docx(path, meta, blocchi, stile):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(stile["margini_cm"])
    font, dim = stile["font"], stile["dimensione"]
    _font_stile(doc.styles["Normal"], font, dim)
    doc.styles["Normal"].paragraph_format.line_spacing = stile["interlinea"]
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)
    _font_stile(doc.styles["Title"], font, dim + 8, bold=True)
    _font_stile(doc.styles["Heading 1"], font, dim + 4, bold=True)
    _font_stile(doc.styles["Heading 2"], font, dim + 2, bold=True)
    _font_stile(doc.styles["List Bullet"], font, dim)
    _numero_pagina(sec)

    doc.add_heading(meta["titolo"], level=0)
    for riga in (f"Data: {meta['data']}", f"Docente: {meta['prof']}" if meta["prof"] else "",
                 f"Sbobinatori: {meta['sbobinatori']}" if meta["sbobinatori"] else ""):
        if riga:
            doc.add_paragraph(riga)
    doc.add_paragraph()

    for b in blocchi:
        tipo = b[0]
        if tipo == "h2":
            doc.add_heading(b[1], level=1)
        elif tipo == "h3":
            doc.add_heading(b[1], level=2)
        elif tipo == "p":
            p = doc.add_paragraph()
            if stile["giustificato"]:
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            _runs(p, b[1])
        elif tipo == "li":
            _runs(doc.add_paragraph(style="List Bullet"), b[1])
        elif tipo == "nota":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            r = p.add_run("Nota: ")
            r.bold = r.italic = True
            for pezzo in re.split(r"(\*\*.+?\*\*)", b[1]):
                run = p.add_run(pezzo[2:-2] if pezzo.startswith("**") and pezzo.endswith("**") else pezzo)
                run.italic = True
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "EDEDED")
            p._p.get_or_add_pPr().append(shd)
        elif tipo == "img":
            try:
                doc.add_picture(b[1], width=Cm(min(14, 21 - 2 * stile["margini_cm"])))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                c = doc.add_paragraph()
                c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = c.add_run(b[2])
                r.italic = True
                r.font.size = Pt(max(dim - 3, 8))
            except Exception:
                pass
    doc.save(str(path))


# ---------------------------------------------------------------- PDF
_FONT_WIN = {
    "times new roman": ("times", "timesbd", "timesi", "timesbi"),
    "arial": ("arial", "arialbd", "ariali", "arialbi"),
    "calibri": ("calibri", "calibrib", "calibrii", "calibriz"),
    "courier new": ("cour", "courbd", "couri", "courbi"),
    "georgia": ("georgia", "georgiab", "georgiai", "georgiaz"),
    "verdana": ("verdana", "verdanab", "verdanai", "verdanaz"),
}


_FONT_MAC = {
    "times new roman": ("Times New Roman.ttf", "Times New Roman Bold.ttf",
                        "Times New Roman Italic.ttf", "Times New Roman Bold Italic.ttf"),
    "arial": ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
    "courier new": ("Courier New.ttf", "Courier New Bold.ttf", "Courier New Italic.ttf",
                    "Courier New Bold Italic.ttf"),
    "georgia": ("Georgia.ttf", "Georgia Bold.ttf", "Georgia Italic.ttf", "Georgia Bold Italic.ttf"),
    "verdana": ("Verdana.ttf", "Verdana Bold.ttf", "Verdana Italic.ttf", "Verdana Bold Italic.ttf"),
}


def _registra_font(nome: str) -> str:
    """Restituisce il nome di una famiglia registrata in reportlab (TTF di Windows o Mac se ci sono)."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    chiave = nome.lower().strip()
    candidati = []
    if chiave in _FONT_WIN:
        cartella = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidati.append([cartella / (f + ".ttf") for f in _FONT_WIN[chiave]])
    if chiave in _FONT_MAC:
        for base in ("/System/Library/Fonts/Supplemental", "/Library/Fonts"):
            candidati.append([Path(base) / f for f in _FONT_MAC[chiave]])
    for files in candidati:
        if all(f.exists() for f in files):
            fam = "SB-" + chiave.replace(" ", "")
            for i, (suffisso, f) in enumerate(zip(("R", "B", "I", "BI"), files)):
                pdfmetrics.registerFont(TTFont(f"{fam}-{suffisso}", str(f)))
                addMapping(fam, i & 1, i >> 1, f"{fam}-{suffisso}")
            return fam
    if "times" in chiave or "georgia" in chiave or "garamond" in chiave:
        return "Times-Roman"
    if "courier" in chiave or "consolas" in chiave:
        return "Courier"
    return "Helvetica"


def _xml(t: str) -> str:
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def scrivi_pdf_reportlab(path, meta, blocchi, stile):
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    fam = _registra_font(stile["font"])
    dim, lead = stile["dimensione"], stile["dimensione"] * stile["interlinea"] * 1.2
    al = TA_JUSTIFY if stile["giustificato"] else TA_LEFT
    base = ParagraphStyle("b", fontName=fam, fontSize=dim, leading=lead, alignment=al, spaceAfter=6)
    st = {
        "title": ParagraphStyle("t", parent=base, fontSize=dim + 8, leading=(dim + 8) * 1.2,
                                alignment=TA_LEFT, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base, fontSize=dim + 4, leading=(dim + 4) * 1.2,
                             alignment=TA_LEFT, spaceBefore=10, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base, fontSize=dim + 2, leading=(dim + 2) * 1.2,
                             alignment=TA_LEFT, spaceBefore=8),
        "li": ParagraphStyle("li", parent=base, leftIndent=18, bulletIndent=6),
        "nota": ParagraphStyle("n", parent=base, leftIndent=12, backColor="#EDEDED", borderPadding=4),
        "cap": ParagraphStyle("c", parent=base, fontSize=max(dim - 3, 8), alignment=TA_CENTER),
    }
    # titoli in grassetto/corsivo usando i tag (la famiglia registrata li mappa)
    def B(t):
        return f"<b>{t}</b>"

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=stile["margini_cm"] * cm,
                            rightMargin=stile["margini_cm"] * cm, topMargin=stile["margini_cm"] * cm,
                            bottomMargin=stile["margini_cm"] * cm, title=meta["titolo"])
    larg = A4[0] - 2 * stile["margini_cm"] * cm
    el = [Paragraph(B(_xml(meta["titolo"])), st["title"]), Paragraph(_xml(f"Data: {meta['data']}"), base)]
    if meta["prof"]:
        el.append(Paragraph(_xml(f"Docente: {meta['prof']}"), base))
    if meta["sbobinatori"]:
        el.append(Paragraph(_xml(f"Sbobinatori: {meta['sbobinatori']}"), base))
    el.append(Spacer(1, 12))
    for b in blocchi:
        t = b[0]
        if t in ("h2", "h3"):
            el.append(Paragraph(B(_xml(b[1])), st[t]))
        elif t == "p":
            el.append(Paragraph(_xml(b[1]), base))
        elif t == "li":
            el.append(Paragraph(_xml(b[1]), st["li"], bulletText="•"))
        elif t == "nota":
            el.append(Paragraph("<i><b>Nota:</b> " + _xml(b[1]) + "</i>", st["nota"]))
        elif t == "img":
            try:
                iw, ih = ImageReader(b[1]).getSize()
                w = min(14 * cm, larg)
                h = w * ih / iw
                if h > 11 * cm:
                    w, h = w * 11 * cm / h, 11 * cm
                img = Image(b[1], width=w, height=h)
                img.hAlign = "CENTER"
                el += [Spacer(1, 4), img, Paragraph("<i>" + _xml(b[2]) + "</i>", st["cap"])]
            except Exception:
                pass

    def piede(canvas, d):
        canvas.setFont(fam if fam in ("Times-Roman", "Courier", "Helvetica") else fam, 9)
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, str(d.page))

    doc.build(el, onFirstPage=piede, onLaterPages=piede)


def crea_pdf(docx_path, pdf_path, meta, blocchi, stile):
    """PDF identico al DOCX se c'è LibreOffice, altrimenti PDF generato direttamente."""
    exe = trova_soffice()
    if exe:
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0
            subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir",
                            str(Path(pdf_path).parent), str(docx_path)],
                           capture_output=True, timeout=300, creationflags=flags)
            generato = Path(pdf_path).parent / (Path(docx_path).stem + ".pdf")
            if generato.exists():
                if generato != Path(pdf_path):
                    generato.replace(pdf_path)
                return "libreoffice"
        except Exception:
            pass
    scrivi_pdf_reportlab(pdf_path, meta, blocchi, stile)
    return "reportlab"
