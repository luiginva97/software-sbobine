"""Riscrittura in forma impersonale, revisione automatica ed estrazione dello stile dalle regole."""
import json
import re

STILE_DEFAULT = {"font": "Times New Roman", "dimensione": 12, "interlinea": 1.15,
                 "giustificato": True, "margini_cm": 2.5}

SYSTEM_RISCRITTURA = """Sei un esperto sbobinatore universitario. Trasformi la trascrizione letterale di una lezione in appunti ben scritti, in italiano corretto.

REGOLE FONDAMENTALI
1. Fedeltà: usa SOLO ciò che il docente dice nella trascrizione. Non aggiungere informazioni, esempi, numeri, nomi o definizioni non presenti. Non omettere concetti, esempi, dati o numeri citati.
2. Forma impersonale: mai prima o seconda persona (niente "io", "noi", "vi", "ragazzi", "come vedete", "dicevo", "abbiamo visto"). Scrivi ad esempio "Il docente spiega che...", "Si osserva che...", "È importante notare che...", oppure usa il passivo.
3. Elimina intercalari, ripetizioni, false partenze, battute, appello, comunicazioni organizzative e discorsi estranei alla materia.
4. Per i termini tecnici usa la grafia delle slide, se fornite.
5. Se un passaggio è incomprensibile scrivi [inc.] invece di inventare.
6. Formato di uscita (Markdown semplice): titoli di sezione con "## ", paragrafi separati da una riga vuota, elenchi con "- ", parole chiave in **grassetto** con moderazione. Una nota va su una riga che inizia con "NOTA:" e si usa solo per chiarimenti presi dalle slide o dal materiale di riferimento, oppure per segnalare un passaggio dubbio.
7. Scrivi SOLO il testo della sbobina: niente introduzioni, commenti o spiegazioni tue."""

SYSTEM_REVISORE = """Sei un revisore di sbobine universitarie. Confronti la TRASCRIZIONE ORIGINALE con la SBOBINA e cerchi problemi concreti:
- concetti, esempi o dati importanti della trascrizione omessi;
- informazioni, numeri o nomi inventati che non compaiono nella trascrizione;
- uso della prima o seconda persona (non impersonale);
- termini tecnici sbagliati.
Rispondi SOLO con JSON: {"ok": true oppure false, "problemi": ["descrizione breve", ...]}. Massimo 6 problemi, brevi e specifici. Se tutto va bene: {"ok": true, "problemi": []}."""

_PERSONA = re.compile(
    r"\b(io|noi|voi|ragazzi|ragazze|vedete|vediamo|dicevo|dicevamo|ricordate|ricordo|facciamo|abbiamo)\b",
    re.I)


def blocchi_da_righe(righe, parole_max=650):
    blocchi, cur, n = [], [], 0
    for r in righe:
        w = len(r.split())
        if cur and n + w > parole_max:
            blocchi.append(" ".join(cur))
            cur, n = [], 0
        cur.append(r)
        n += w
    if cur:
        blocchi.append(" ".join(cur))
    return blocchi


def _pulisci(out: str) -> str:
    out = out.strip()
    out = re.sub(r"^```[a-z]*\n?|\n?```$", "", out).strip()
    righe = out.splitlines()
    if righe and re.match(r"^(ecco|certo|di seguito)\b.*:\s*$", righe[0], re.I):
        righe = righe[1:]
    return "\n".join(righe).strip()


def riscrivi_blocco(llm, blocco, ctx, feedback=None, precedente=None):
    system = SYSTEM_RISCRITTURA
    if ctx.get("regole"):
        system += "\n\nREGOLE DI FORMATTAZIONE DEL GRUPPO (da rispettare):\n" + ctx["regole"][:3000]
    parti = [f"MATERIA: {ctx.get('materia', '')}   DOCENTE: {ctx.get('prof', '')}"]
    if ctx.get("esempi"):
        parti.append("ESEMPI DI STILE tratti da sbobine precedenti (imita stile e struttura, NON il contenuto):\n"
                     + "\n---\n".join(ctx["esempi"]))
    if ctx.get("slide"):
        parti.append("TESTO DELLE SLIDE PERTINENTI (per la grafia dei termini):\n" + "\n---\n".join(ctx["slide"]))
    if ctx.get("coda"):
        parti.append("FINE DEL TESTO GIÀ SCRITTO (per continuità, non ripeterlo):\n" + ctx["coda"])
    parti.append("TRASCRIZIONE DA RISCRIVERE:\n" + blocco)
    if feedback:
        parti.append("VERSIONE PRECEDENTE DA CORREGGERE:\n" + (precedente or "")
                     + "\n\nPROBLEMI SEGNALATI (correggili senza introdurre altri errori):\n- "
                     + "\n- ".join(feedback))
    return _pulisci(llm.chat(system, "\n\n".join(parti), temperature=0.2))


def controlli_deterministici(raw, out, extra_testo=""):
    problemi = []
    trovate = sorted({m.group(0).lower() for m in _PERSONA.finditer(out)})
    if trovate:
        problemi.append("Forma non impersonale (parole: " + ", ".join(trovate) + ")")
    base = raw + " " + extra_testo
    nums_base = set(re.findall(r"\d+(?:[.,]\d+)?", base))
    out_senza_elenchi = re.sub(r"(?m)^\s*\d+[.)]\s+", "", out)
    nuovi = sorted({n for n in re.findall(r"\d+(?:[.,]\d+)?", out_senza_elenchi) if n not in nums_base})
    if nuovi:
        problemi.append("Numeri non presenti nella trascrizione: " + ", ".join(nuovi[:8]))
    if len(raw.split()) > 150 and len(out.split()) < 0.3 * len(raw.split()):
        problemi.append("Testo molto più corto dell'originale: possibili omissioni")
    return problemi


def _json_tollerante(testo):
    m = re.search(r"\{.*\}", testo, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def rivedi_blocco(llm, raw, out, extra_testo=""):
    problemi = controlli_deterministici(raw, out, extra_testo)
    try:
        r = llm.chat(SYSTEM_REVISORE,
                     f"TRASCRIZIONE ORIGINALE:\n{raw}\n\nSBOBINA:\n{out}", temperature=0, json_mode=True)
        j = _json_tollerante(r)
        if j and isinstance(j.get("problemi"), list):
            problemi += [str(p) for p in j["problemi"][:6] if str(p).strip()]
    except Exception:
        pass
    return problemi


def estrai_stile(llm, regole: str) -> dict:
    """Legge dalle regole eventuali impostazioni di formattazione (font, dimensione, interlinea...)."""
    stile = dict(STILE_DEFAULT)
    if not regole.strip():
        return stile
    try:
        r = llm.chat(
            "Estrai da un testo le impostazioni di formattazione del documento. Rispondi SOLO con JSON "
            'con chiavi opzionali: "font" (stringa), "dimensione" (numero in pt), "interlinea" (numero), '
            '"giustificato" (true/false), "margini_cm" (numero). Ometti le chiavi non specificate.',
            regole[:3000], temperature=0, json_mode=True)
        j = _json_tollerante(r) or {}
        if isinstance(j.get("font"), str) and 2 < len(j["font"]) < 40:
            stile["font"] = j["font"]
        if isinstance(j.get("dimensione"), (int, float)) and 8 <= j["dimensione"] <= 18:
            stile["dimensione"] = j["dimensione"]
        if isinstance(j.get("interlinea"), (int, float)) and 1 <= j["interlinea"] <= 3:
            stile["interlinea"] = j["interlinea"]
        if isinstance(j.get("giustificato"), bool):
            stile["giustificato"] = j["giustificato"]
        if isinstance(j.get("margini_cm"), (int, float)) and 1 <= j["margini_cm"] <= 5:
            stile["margini_cm"] = j["margini_cm"]
    except Exception:
        pass
    return stile
