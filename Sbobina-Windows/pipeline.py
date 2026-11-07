"""Pipeline in due fasi:
 1) prepara_bozza: trascrizione -> slide -> riscrittura -> revisione -> proposta immagini (testo modificabile)
 2) esporta_bozza: dal testo (anche modificato dall'utente) a DOCX e PDF."""
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import documenti
import esporta
import riscrittura as rw
import slides as sl
import trascrizione as tr
from esporta import MARK
from llm import Llm
from similarita import Similarita, matrice_lessicale

OUT_ROOT = documenti.cartella_documenti() / "Sbobine"


@dataclass
class Config:
    audio: list = field(default_factory=list)
    trascrizione_txt: str = ""
    modello_whisper: str = "auto"
    materia: str = ""
    numero: str = ""
    data: str = ""
    prof: str = ""
    sbobinatori: str = ""
    slide: list = field(default_factory=list)
    vecchie: list = field(default_factory=list)
    regole_files: list = field(default_factory=list)
    regole_testo: str = ""
    riscrivi: bool = True
    revisione: bool = True
    crea_pdf: bool = True
    immagini: str = "figure"          # "figure" | "tutte" | "nessuna"
    motore: str = "ollama"            # "ollama" | "api"
    modello_llm: str = "qwen2.5:7b"
    base_url: str = ""
    api_key: str = ""


@dataclass
class Risultato:
    cartella: str = ""
    docx: str = ""
    pdf: str = ""
    trascrizione: str = ""
    report: str = ""
    riepilogo: str = ""


def _nessun_progresso(frac, desc):
    pass


# ------------------------------------------------------------ utilità sul testo
def chunks_md(md: str) -> list:
    return [c for c in re.split(r"\n\s*\n", md.strip()) if c.strip()]


def e_testo(chunk: str) -> bool:
    """Paragrafo 'vero' (non titolo, nota o marcatore): lì ha senso agganciare una slide."""
    c = chunk.strip()
    return not (c.startswith("#") or c.upper().startswith("NOTA") or MARK.match(c))


def rimuovi_marcatori(md: str, slide_id: int) -> str:
    out = [c for c in chunks_md(md)
           if not (MARK.match(c.strip()) and int(MARK.match(c.strip()).group(1)) == slide_id)]
    return "\n\n".join(out)


def slide_usate(md: str) -> set:
    return {int(m.group(1)) for c in chunks_md(md) if (m := MARK.match(c.strip()))}


def proponi_slide(md, slide_dicts, modo, sim, report):
    """Inserisce nel testo i marcatori [[SLIDE n]] dopo il paragrafo più vicino a ciascuna slide."""
    if modo == "nessuna" or not slide_dicts:
        return md
    tutte = [s for s in slide_dicts if modo == "tutte" or s["visuale"]]
    cand = [s for s in tutte if len(s["testo"].split()) >= 3]
    chunks = chunks_md(md)
    idx = [i for i, c in enumerate(chunks) if e_testo(c)]
    if len(tutte) > len(cand):
        report.append(f"Slide con figure ma senza testo (scegli tu dove metterle): {len(tutte) - len(cand)}")
    if not cand or not idx:
        return md
    M = sim.matrice([s["testo"] for s in cand], [chunks[i] for i in idx])
    posti, scartate = {}, []
    for s, riga in zip(cand, M):
        j = max(range(len(riga)), key=riga.__getitem__)
        if riga[j] >= sim.soglia:
            posti.setdefault(idx[j], []).append(s)
        else:
            scartate.append(s)
    out, n = [], 0
    for i, c in enumerate(chunks):
        out.append(c)
        for s in sorted(posti.get(i, []), key=lambda x: x["id"]):
            out.append(f"[[SLIDE {s['id']}]]")
            n += 1
    report.append(f"Immagini proposte: {n} slide (confronto {sim.metodo}).")
    if scartate:
        report.append("Slide con figure non agganciate a nessun paragrafo (scegli tu): "
                      + ", ".join(str(s["id"]) for s in scartate))
    return "\n\n".join(out)


# ------------------------------------------------------------ FASE 1: bozza
def prepara_bozza(cfg: Config, prog=_nessun_progresso, llm=None) -> dict:
    materia = cfg.materia.strip() or "Lezione"
    numero = cfg.numero.strip() or "1"
    data = cfg.data.strip() or date.today().strftime("%d/%m/%Y")
    base = re.sub(r"[^\w\-]+", "_", f"{materia}_{numero}_{data}").strip("_")
    cartella = OUT_ROOT / base
    cartella.mkdir(parents=True, exist_ok=True)
    meta = {"titolo": f"{materia} - Lezione n. {numero}", "data": data,
            "prof": cfg.prof.strip(), "sbobinatori": cfg.sbobinatori.strip()}
    report = []

    # ---- trascrizione fedele
    if cfg.trascrizione_txt:
        raw = Path(cfg.trascrizione_txt).read_text(encoding="utf-8", errors="replace")
    else:
        size = tr.scegli_modello(cfg.modello_whisper)
        segs = tr.trascrivi(cfg.audio, size, lambda f, d: prog(0.02 + 0.43 * f, d))
        raw = tr.segmenti_a_testo(segs)
    f_raw = cartella / f"{base}_trascrizione_grezza.txt"
    f_raw.write_text(raw, encoding="utf-8")
    righe = tr.testo_a_righe(raw)
    if not righe:
        raise ValueError("La trascrizione è vuota: controlla l'audio.")

    # ---- motore AI (solo se serve la riscrittura)
    stile = dict(rw.STILE_DEFAULT)
    if cfg.riscrivi:
        prog(0.46, "Preparo il motore AI")
        if llm is None:
            llm = Llm(cfg.motore, cfg.modello_llm, cfg.base_url, cfg.api_key)
        llm.prepara(lambda f, d: prog(0.46 + 0.04 * f, d))
        sim = Similarita(llm)
    else:
        sim = Similarita(None)

    # ---- slide: lettura e rendering di tutte le pagine (per la galleria)
    prog(0.51, "Leggo le slide")
    work = Path(tempfile.mkdtemp())
    slide_list = []
    for p in cfg.slide:
        try:
            slide_list += sl.estrai_slide(p, work)
        except Exception as e:
            report.append(f"Slide non lette ({Path(p).name}): {e}")
    for i, s in enumerate(slide_list, 1):
        s.id = i
    multi = len({s.fonte for s in slide_list}) > 1
    slide_dicts = []
    for k, s in enumerate(slide_list):
        if k % 5 == 0:
            prog(0.52 + 0.06 * k / max(len(slide_list), 1), f"Preparo le immagini delle slide ({k + 1}/{len(slide_list)})")
        try:
            img = sl.salva_immagine(s, cartella / "immagini")
        except Exception:
            img = None
        if img:
            slide_dicts.append({"id": s.id, "fonte": s.fonte, "n": s.n, "testo": s.testo, "img": img,
                                "visuale": s.visuale,
                                "didascalia": f"{s.fonte} - slide {s.n}" if multi else f"Slide {s.n}"})
    if slide_list and not slide_dicts:
        report.append("Nessuna immagine ricavabile dalle slide (per i PPTX installa LibreOffice o carica il PDF).")

    # ---- riscrittura + revisione
    if cfg.riscrivi:
        esempi_chunks = []
        for p in cfg.vecchie:
            try:
                esempi_chunks += documenti.spezza_testo(documenti.leggi_testo(p))
            except Exception as e:
                report.append(f"Vecchia sbobina non letta ({Path(p).name}): {e}")
        regole = cfg.regole_testo.strip()
        for p in cfg.regole_files:
            try:
                regole += "\n" + documenti.leggi_testo(p)
            except Exception as e:
                report.append(f"File regole non letto ({Path(p).name}): {e}")
        stile = rw.estrai_stile(llm, regole)

        blocchi_raw = rw.blocchi_da_righe(righe)
        slide_txt = [s for s in slide_list if len(s.testo.split()) >= 5]
        M_slide = sim.matrice(blocchi_raw, [s.testo for s in slide_txt]) if slide_txt else None
        M_es = sim.matrice(blocchi_raw, esempi_chunks) if esempi_chunks else None

        uscite, coda, n = [], "", len(blocchi_raw)
        for i, blocco in enumerate(blocchi_raw):
            prog(0.60 + 0.30 * i / n, f"Riscrittura: blocco {i + 1} di {n}")
            ctx = {"materia": materia, "prof": meta["prof"], "regole": regole, "coda": coda}
            if M_slide is not None:
                top = sorted(range(len(slide_txt)), key=lambda j: -M_slide[i][j])[:3]
                ctx["slide"] = [slide_txt[j].testo[:600] for j in top]
            if M_es is not None:
                top = sorted(range(len(esempi_chunks)), key=lambda j: -M_es[i][j])[:2]
                ctx["esempi"] = [esempi_chunks[j][:1500] for j in top]
            extra = " ".join(ctx.get("slide", []))
            try:
                out = rw.riscrivi_blocco(llm, blocco, ctx)
                if not out:
                    raise ValueError("risposta vuota")
                if cfg.revisione:
                    prog(0.60 + 0.30 * (i + 0.6) / n, f"Revisione: blocco {i + 1} di {n}")
                    problemi = rw.rivedi_blocco(llm, blocco, out, extra)
                    if problemi:
                        out2 = rw.riscrivi_blocco(llm, blocco, ctx, feedback=problemi, precedente=out)
                        if out2 and len(rw.controlli_deterministici(blocco, out2, extra)) <= \
                                len(rw.controlli_deterministici(blocco, out, extra)):
                            out = out2
                        resto = rw.controlli_deterministici(blocco, out, extra)
                        if resto:
                            out += "\n\nNOTA: ⚠️ DA RICONTROLLARE - " + "; ".join(resto)
                            report.append(f"Blocco {i + 1}: da ricontrollare - " + "; ".join(resto))
            except Exception as e:
                out = ("NOTA: ⚠️ Blocco non riscritto automaticamente (" + str(e)[:100].replace("\n", " ") +
                       "): qui sotto la trascrizione originale.\n\n" + blocco)
                report.append(f"Blocco {i + 1}: ERRORE, inserita la trascrizione originale ({str(e)[:100]})")
            uscite.append(out)
            coda = " ".join(out.split()[-60:])
        md = "\n\n".join(uscite)
    else:
        paragrafi, cur = [], []
        for r in righe:
            cur.append(r)
            if len(cur) >= 6:
                paragrafi.append(" ".join(cur))
                cur = []
        if cur:
            paragrafi.append(" ".join(cur))
        md = "\n\n".join(paragrafi)
        n = len(paragrafi)

    # ---- proposta di immagini
    prog(0.93, "Propongo le immagini")
    md = proponi_slide(md, slide_dicts, cfg.immagini, sim, report)

    f_md = cartella / f"{base}_testo.md"
    f_md.write_text(md, encoding="utf-8")
    f_rep = cartella / f"{base}_report_revisione.txt"
    f_rep.write_text("REPORT DELLA REVISIONE AUTOMATICA\n\n" + ("\n".join(report) or "Nessuna segnalazione."),
                     encoding="utf-8")
    da_vedere = len([r for r in report if "da ricontrollare" in r or "ERRORE" in r])
    riepilogo = (f"{n} blocchi elaborati, {da_vedere} da ricontrollare (cerca le note ⚠️ nel testo)."
                 if da_vedere else f"{n} blocchi elaborati, nessuna segnalazione.")
    prog(1.0, "Bozza pronta")
    return {"cartella": str(cartella), "base": base, "meta": meta, "stile": stile, "md": md,
            "md_path": str(f_md), "slides": slide_dicts, "report": report, "riepilogo": riepilogo,
            "trascrizione": str(f_raw), "report_path": str(f_rep)}


# ------------------------------------------------------------ FASE 2: export
def esporta_bozza(md: str, bozza: dict, crea_pdf=True, prog=_nessun_progresso) -> dict:
    cartella = Path(bozza["cartella"])
    base = bozza["base"]
    md, rimossi = esporta.rimuovi_avvisi(md)
    smap = {s["id"]: (s["img"], s["didascalia"]) for s in bozza["slides"]}
    blocchi = esporta.markdown_a_blocchi(md, smap)
    (cartella / f"{base}_testo_modificato.md").write_text(md, encoding="utf-8")
    f_docx, f_pdf = cartella / f"{base}.docx", cartella / f"{base}.pdf"
    prog(0.4, "Creo il documento Word")
    esporta.scrivi_docx(f_docx, bozza["meta"], blocchi, bozza["stile"])
    out = {"docx": str(f_docx), "pdf": "", "rimossi": rimossi, "metodo_pdf": "",
           "immagini": sum(1 for b in blocchi if b[0] == "img")}
    if crea_pdf:
        prog(0.7, "Creo il PDF")
        out["metodo_pdf"] = esporta.crea_pdf(f_docx, f_pdf, bozza["meta"], blocchi, bozza["stile"])
        out["pdf"] = str(f_pdf)
    prog(1.0, "Fatto")
    return out


# ------------------------------------------------------------ comodo: tutto in un colpo
def genera(cfg: Config, prog=_nessun_progresso, llm=None) -> Risultato:
    b = prepara_bozza(cfg, prog, llm)
    e = esporta_bozza(b["md"], b, cfg.crea_pdf)
    return Risultato(cartella=b["cartella"], docx=e["docx"], pdf=e["pdf"], trascrizione=b["trascrizione"],
                     report=b["report_path"], riepilogo=b["riepilogo"])
