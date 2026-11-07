"""Sbobina - interfaccia (Gradio). Si avvia da main.py.
Flusso: 1) Genera bozza  ->  2) modifica il testo e scegli le slide  ->  3) Esporta Word/PDF."""
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import gradio as gr

import pipeline
import trascrizione as tr
from llm import ErroreMotore
from similarita import matrice_lessicale

IMPOSTAZIONI = Path.home() / ".sbobina" / "impostazioni.json"

MODELLI_WHISPER = [
    ("Automatico (consigliato)", "auto"),
    ("Veloce, qualità discreta (small)", "small"),
    ("Bilanciato (medium)", "medium"),
    ("Massima qualità, più lento (large-v3)", "large-v3"),
]
MOTORI = [("Locale con Ollama: gratis e privato", "ollama"),
          ("Online (API compatibile OpenAI: Groq, Gemini, OpenRouter...)", "api")]
IMMAGINI = [("Solo slide con figure, schemi o tabelle (consigliato)", "figure"),
            ("Tutte le slide pertinenti", "tutte"), ("Nessuna immagine (le scelgo io)", "nessuna")]

GUIDA = ("**Come si modifica:** scrivi direttamente nel testo. `## Titolo` = titolo, `- ` = elenco, "
         "`**parola**` = grassetto, `NOTA: ...` = riquadro nota, `[[SLIDE 5]]` = immagine della slide 5 "
         "(cancella la riga per toglierla). Le note `NOTA: ⚠️ ...` segnalano passaggi da controllare e "
         "**vengono tolte automaticamente all'esportazione**.")


# ---------- impostazioni ricordate
def carica_impostazioni() -> dict:
    try:
        return json.loads(IMPOSTAZIONI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salva_impostazioni(d: dict):
    try:
        IMPOSTAZIONI.parent.mkdir(parents=True, exist_ok=True)
        IMPOSTAZIONI.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


S = carica_impostazioni()


def _paths(files):
    return [f if isinstance(f, str) else f.name for f in (files or [])]


def apri_cartella(bozza):
    folder = (bozza or {}).get("cartella")
    if not folder:
        return
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


def hw_text() -> str:
    acc = tr.accelerazione()
    if acc == "cuda":
        return "🟢 Scheda video NVIDIA rilevata: trascrizione veloce."
    if acc == "apple":
        return "🟢 Mac con chip Apple Silicon rilevato: trascrizione accelerata."
    if acc == "vulkan":
        return "🟢 whisper.cpp con Vulkan trovato: trascrizione accelerata dalla scheda video (AMD o altra)."
    if sys.platform == "darwin":
        return "🟡 Mac senza accelerazione dedicata: userò la CPU (più lento, modello leggero consigliato)."
    if tr.amd_gpu_rilevata():
        return ("🟡 Scheda video AMD rilevata, ma manca whisper-cli (Vulkan): userò la CPU (più lento). "
                "Vedi la sezione \"GPU AMD\" nel file LEGGIMI.txt.")
    return "🟡 Nessuna GPU NVIDIA rilevata: userò la CPU (più lento)."


# ---------- funzioni dell'editor (testabili senza interfaccia)
def galleria_items(bozza, md):
    usate = pipeline.slide_usate(md)
    return [(s["img"], f"{s['didascalia']}{' ✔' if s['id'] in usate else ''}") for s in bozza.get("slides", [])]


def _info_slide(bozza, md, slide_id):
    s = next((x for x in bozza.get("slides", []) if x["id"] == slide_id), None)
    if not s:
        return "Clicca una slide nella galleria per sceglierla."
    stato = "✅ già inserita nel testo" if slide_id in pipeline.slide_usate(md) else "non ancora inserita"
    anteprima = (s["testo"].strip().replace("\n", " ")[:260] + "…") if s["testo"].strip() else "(slide senza testo)"
    return f"**{s['didascalia']}** (marcatore `[[SLIDE {slide_id}]]`) - {stato}\n\n> {anteprima}"


def _aggiorna_dd(md, bozza, slide_id):
    chunks = pipeline.chunks_md(md)
    voci = [(f"{i + 1}. {c[:70].replace(chr(10), ' ')}{'…' if len(c) > 70 else ''}", i)
            for i, c in enumerate(chunks) if not pipeline.MARK.match(c.strip())]
    valore = None
    s = next((x for x in bozza.get("slides", []) if x["id"] == slide_id), None)
    if s and s["testo"].strip() and voci:
        cand = [i for i, c in enumerate(chunks) if pipeline.e_testo(c)]
        if cand:
            riga = matrice_lessicale([s["testo"]], [chunks[i] for i in cand])[0]
            j = max(range(len(riga)), key=riga.__getitem__)
            if riga[j] > 0:
                valore = cand[j]
    return gr.update(choices=voci, value=valore)


def inserisci_slide(md, slide_id, idx, bozza):
    if not slide_id:
        raise gr.Error("Clicca prima una slide nella galleria.")
    if idx is None:
        raise gr.Error("Scegli dopo quale paragrafo inserire la slide.")
    chunks = pipeline.chunks_md(md)
    if idx >= len(chunks):
        raise gr.Error("Il testo è cambiato: riseleziona la slide e il paragrafo.")
    bersaglio = chunks[idx]
    m = pipeline.MARK.match(bersaglio.strip())
    if m and int(m.group(1)) == slide_id:
        raise gr.Error("Scegli un paragrafo diverso dal marcatore della slide stessa.")
    nuovo = []
    for i, c in enumerate(chunks):
        cm = pipeline.MARK.match(c.strip())
        if cm and int(cm.group(1)) == slide_id:
            continue                      # la sposto: tolgo il vecchio marcatore
        nuovo.append(c)
        if i == idx:
            nuovo.append(f"[[SLIDE {slide_id}]]")
    md2 = "\n\n".join(nuovo)
    return md2, galleria_items(bozza, md2), _info_slide(bozza, md2, slide_id), _aggiorna_dd(md2, bozza, slide_id)


def togli_slide(md, slide_id, bozza):
    if not slide_id:
        raise gr.Error("Clicca prima una slide nella galleria.")
    md2 = pipeline.rimuovi_marcatori(md, slide_id)
    return md2, galleria_items(bozza, md2), _info_slide(bozza, md2, slide_id), _aggiorna_dd(md2, bozza, slide_id)


def anteprima(md):
    out = []
    for riga in (md or "").splitlines():
        r = riga.strip()
        m = pipeline.MARK.match(r)
        if m:
            out.append(f"> 🖼️ **Immagine: slide {m.group(1)}**")
        elif re.match(r"^NOTA\s*:", r):
            out.append("> 📝 " + re.sub(r"^NOTA\s*:\s*", "", r))
        else:
            out.append(riga)
    return "\n".join(out)


# ---------- interfaccia
with gr.Blocks(title="Sbobina", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎓 Sbobina\nDalla registrazione alla sbobina pronta, "
                "**sul tuo computer**: l'audio non viene mai inviato a nessuno.")
    gr.Markdown(hw_text())

    gr.Markdown("### 1. Registrazione")
    audio = gr.File(label="Trascina qui l'audio (anche più parti: unite nell'ordine in cui le carichi)",
                    file_count="multiple", file_types=["audio", "video"])
    trascr_file = gr.File(label="Oppure: ho già la trascrizione grezza (.txt) e salto l'audio",
                          file_count="single", file_types=[".txt"])

    gr.Markdown("### 2. Dati della lezione")
    with gr.Row():
        materia = gr.Textbox(label="Materia", placeholder="es. Anatomia")
        numero = gr.Textbox(label="N. progressivo", placeholder="es. 12")
        data = gr.Textbox(label="Data", value=date.today().strftime("%d/%m/%Y"))
    with gr.Row():
        prof = gr.Textbox(label="Docente", placeholder="es. Prof. Rossi")
        sbob = gr.Textbox(label="Sbobinatori", value=S.get("sbobinatori", ""),
                          placeholder="es. Anna, Marco, Giulia")

    gr.Markdown("### 3. Materiali (facoltativi, ma migliorano molto il risultato)")
    slide = gr.File(label="Slide del docente (PDF o PowerPoint)", file_count="multiple",
                    file_types=[".pdf", ".pptx"])
    vecchie = gr.File(label="Sbobine degli anni scorsi sullo stesso argomento (servono da modello di stile)",
                      file_count="multiple", file_types=[".docx", ".pdf", ".txt", ".md"])
    regole_file = gr.File(label="Regole di formattazione del gruppo (file)", file_count="multiple",
                          file_types=[".docx", ".pdf", ".txt", ".md"])
    regole_testo = gr.Textbox(label="Regole di formattazione (o scrivile qui)", lines=4,
                              value=S.get("regole_testo", ""),
                              placeholder="es. Font Times New Roman 12, interlinea 1,5. Termini tecnici in "
                                          "grassetto alla prima occorrenza. Titoli numerati.")

    with gr.Accordion("Opzioni avanzate", open=False):
        riscrivi = gr.Checkbox(label="Riscrivi in forma impersonale con l'AI (se disattivato: solo trascrizione)",
                               value=S.get("riscrivi", True))
        revisione = gr.Checkbox(label="Revisione automatica (controlla omissioni e invenzioni)",
                                value=S.get("revisione", True))
        pdf = gr.Checkbox(label="Crea anche il PDF", value=S.get("pdf", True))
        immagini = gr.Dropdown(IMMAGINI, value=S.get("immagini", "figure"),
                               label="Proposta automatica delle immagini dalle slide")
        modello_w = gr.Dropdown(MODELLI_WHISPER, value="auto", label="Qualità trascrizione")
        motore = gr.Dropdown(MOTORI, value=S.get("motore", "ollama"), label="Motore AI per la riscrittura")
        modello_llm = gr.Textbox(label="Nome del modello", value=S.get("modello_llm", "qwen2.5:7b"),
                                 info="Locale: es. qwen2.5:7b, gemma3:12b, llama3.1:8b. Online: es. "
                                      "llama-3.3-70b-versatile (Groq), gemini-2.0-flash (Gemini).")
        base_url = gr.Textbox(label="Indirizzo API (solo motore online)", value=S.get("base_url", ""),
                              placeholder="https://api.groq.com/openai/v1")
        api_key = gr.Textbox(label="Chiave API (solo motore online)", type="password",
                             value=S.get("api_key", ""))
        gr.Markdown("⚠️ Con il motore online il **testo** della lezione viene inviato al servizio scelto "
                    "(l'audio resta sempre sul PC). I piani gratuiti hanno limiti giornalieri.")

    btn = gr.Button("1️⃣ Genera la bozza", variant="primary", size="lg")
    stato = gr.Markdown()

    bozza_state = gr.State({})
    sel_id = gr.State(0)

    with gr.Column(visible=False) as review:
        gr.Markdown("---\n### 4. Controlla, modifica e scegli le immagini")
        gr.Markdown(GUIDA)
        with gr.Row():
            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("✏️ Modifica"):
                        editor = gr.Textbox(label="Testo della sbobina (modificabile)", lines=28,
                                            max_lines=60, show_copy_button=True)
                    with gr.Tab("👁️ Anteprima") as tab_prev:
                        preview = gr.Markdown()
            with gr.Column(scale=2):
                gallery = gr.Gallery(label="Slide (clicca una slide per sceglierla; ✔ = già nel testo)",
                                     columns=2, height=520, object_fit="contain", allow_preview=True)
                sel_info = gr.Markdown("Clicca una slide nella galleria per sceglierla.")
                para_dd = gr.Dropdown(label="Inserisci la slide dopo il paragrafo...", choices=[], value=None)
                with gr.Row():
                    btn_ins = gr.Button("➕ Inserisci / sposta qui")
                    btn_rem = gr.Button("➖ Togli dal testo")
        btn_exp = gr.Button("2️⃣ Esporta Word e PDF", variant="primary", size="lg")
        stato_exp = gr.Markdown()
        with gr.Row():
            out_docx = gr.File(label="Word (.docx)")
            out_pdf = gr.File(label="PDF")
        with gr.Row():
            out_txt = gr.File(label="Trascrizione grezza (.txt)")
            out_rep = gr.File(label="Report della revisione")
        btn_open = gr.Button("📂 Apri la cartella dei file")


# ---------- eventi
def crea_bozza(d, progress=gr.Progress()):
    paths_audio = _paths(d[audio])
    txt = d[trascr_file]
    txt = txt if isinstance(txt, str) or txt is None else txt.name
    if not paths_audio and not txt:
        raise gr.Error("Carica almeno un file audio (oppure una trascrizione .txt).")
    cfg = pipeline.Config(
        audio=paths_audio, trascrizione_txt=txt or "", modello_whisper=d[modello_w],
        materia=d[materia] or "", numero=d[numero] or "", data=d[data] or "",
        prof=d[prof] or "", sbobinatori=d[sbob] or "",
        slide=_paths(d[slide]), vecchie=_paths(d[vecchie]), regole_files=_paths(d[regole_file]),
        regole_testo=d[regole_testo] or "", riscrivi=d[riscrivi], revisione=d[revisione],
        crea_pdf=d[pdf], immagini=d[immagini], motore=d[motore], modello_llm=d[modello_llm].strip(),
        base_url=(d[base_url] or "").strip(), api_key=(d[api_key] or "").strip(),
    )
    salva_impostazioni({
        "sbobinatori": cfg.sbobinatori, "regole_testo": cfg.regole_testo, "riscrivi": cfg.riscrivi,
        "revisione": cfg.revisione, "pdf": cfg.crea_pdf, "immagini": cfg.immagini, "motore": cfg.motore,
        "modello_llm": cfg.modello_llm, "base_url": cfg.base_url, "api_key": cfg.api_key,
    })
    try:
        b = pipeline.prepara_bozza(cfg, lambda f, desc: progress(min(f, 1.0), desc=desc))
    except ErroreMotore as e:
        raise gr.Error(str(e))
    msg = f"✅ **Bozza pronta.** {b['riepilogo']} Controlla il testo qui sotto, scegli le immagini ed esporta."
    return (b["md"], galleria_items(b, b["md"]), b, gr.update(visible=True), msg,
            b["trascrizione"], b["report_path"], _aggiorna_dd(b["md"], b, 0),
            "Clicca una slide nella galleria per sceglierla.", 0)


def scegli_slide(md, bozza, evt: gr.SelectData):
    slides = bozza.get("slides", [])
    if evt.index is None or evt.index >= len(slides):
        return 0, "Slide non trovata.", gr.update()
    sid = slides[evt.index]["id"]
    return sid, _info_slide(bozza, md, sid), _aggiorna_dd(md, bozza, sid)


def esporta_ui(md, bozza, crea_pdf, progress=gr.Progress()):
    if not bozza:
        raise gr.Error("Genera prima la bozza.")
    if not (md or "").strip():
        raise gr.Error("Il testo è vuoto.")
    try:
        e = pipeline.esporta_bozza(md, bozza, crea_pdf, lambda f, desc: progress(f, desc=desc))
    except PermissionError:
        raise gr.Error("Non riesco a scrivere il file: chiudi il Word/PDF aperto e riprova.")
    extra = f" Tolte {e['rimossi']} note di avviso ⚠️." if e["rimossi"] else ""
    msg = (f"✅ **Esportato!** {e['immagini']} immagini inserite.{extra}\n\n"
           f"File salvati in: `{bozza['cartella']}`")
    return e["docx"], (e["pdf"] or None), msg


_inputs = {audio, trascr_file, materia, numero, data, prof, sbob, slide, vecchie, regole_file,
           regole_testo, riscrivi, revisione, pdf, immagini, modello_w, motore, modello_llm,
           base_url, api_key}

with demo:
    btn.click(crea_bozza, _inputs,
              [editor, gallery, bozza_state, review, stato, out_txt, out_rep, para_dd, sel_info, sel_id])
    gallery.select(scegli_slide, [editor, bozza_state], [sel_id, sel_info, para_dd])
    editor.blur(_aggiorna_dd, [editor, bozza_state, sel_id], para_dd)
    btn_ins.click(inserisci_slide, [editor, sel_id, para_dd, bozza_state], [editor, gallery, sel_info, para_dd])
    btn_rem.click(togli_slide, [editor, sel_id, bozza_state], [editor, gallery, sel_info, para_dd])
    tab_prev.select(anteprima, editor, preview)
    btn_exp.click(esporta_ui, [editor, bozza_state, pdf], [out_docx, out_pdf, stato_exp])
    btn_open.click(apri_cartella, bozza_state, None)

if __name__ == "__main__":
    demo.launch(allowed_paths=[str(pipeline.OUT_ROOT)])
