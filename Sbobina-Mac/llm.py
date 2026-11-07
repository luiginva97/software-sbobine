"""Client per il motore AI: Ollama locale (gratis, privato) oppure API online compatibile OpenAI
(Groq, Gemini, OpenRouter, ecc.). Solo libreria standard."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://127.0.0.1:11434"
MODELLO_EMBED = "bge-m3"


class ErroreMotore(Exception):
    pass


def _post(url, payload, headers=None, timeout=900):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _ollama_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    base = os.environ.get("LOCALAPPDATA")
    if base:
        c = Path(base) / "Programs" / "Ollama" / "ollama.exe"
        if c.exists():
            return str(c)
    for c in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
              "/Applications/Ollama.app/Contents/Resources/ollama"):
        if Path(c).exists():
            return c
    return None


class Llm:
    def __init__(self, tipo="ollama", modello="qwen2.5:7b", base_url="", api_key=""):
        self.tipo = tipo
        self.modello = modello
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.embed_ok = False

    # ---------- preparazione (solo Ollama) ----------
    def prepara(self, progress=lambda f, d: None):
        if self.tipo != "ollama":
            if not self.base_url or not self.api_key:
                raise ErroreMotore("Per il motore online servono indirizzo API e chiave API (Opzioni avanzate).")
            return
        self._avvia_ollama()
        self._scarica_se_manca(self.modello, progress, obbligatorio=True)
        try:
            self._scarica_se_manca(MODELLO_EMBED, progress, obbligatorio=False)
            self.embed_ok = True
        except Exception:
            self.embed_ok = False

    def _ollama_attivo(self):
        try:
            _get(OLLAMA_HOST + "/api/tags")
            return True
        except Exception:
            return False

    def _avvia_ollama(self):
        if self._ollama_attivo():
            return
        exe = _ollama_exe()
        if not exe:
            raise ErroreMotore(
                "Ollama (il motore AI locale e gratuito) non è installato. "
                "Scaricalo da https://ollama.com/download, installalo e riprova."
            )
        flags = 0x08000000 if sys.platform == "win32" else 0
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags)
        for _ in range(40):
            time.sleep(1)
            if self._ollama_attivo():
                return
        raise ErroreMotore("Non riesco ad avviare Ollama. Aprilo manualmente dal menu Start e riprova.")

    def _scarica_se_manca(self, nome, progress, obbligatorio):
        nomi = [m["name"] for m in _get(OLLAMA_HOST + "/api/tags").get("models", [])]
        if nome in nomi or nome + ":latest" in nomi:
            return
        try:
            with _post(OLLAMA_HOST + "/api/pull", {"model": nome, "stream": True}, timeout=7200) as r:
                for riga in r:
                    try:
                        d = json.loads(riga)
                    except ValueError:
                        continue
                    if d.get("error"):
                        raise ErroreMotore(d["error"])
                    if d.get("total"):
                        progress(d.get("completed", 0) / d["total"],
                                 f"Scarico il modello {nome} (una volta sola)")
        except ErroreMotore:
            raise
        except Exception as e:
            if obbligatorio:
                raise ErroreMotore(f"Non riesco a scaricare il modello {nome}: {e}")
            raise

    # ---------- chiamate ----------
    def _retry(self, fn):
        for i in range(5):
            try:
                return fn()
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and i < 4:
                    time.sleep(2 ** (i + 1))
                    continue
                corpo = e.read().decode(errors="ignore")[:300]
                raise ErroreMotore(f"Errore dal servizio AI ({e.code}): {corpo}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if i < 2:
                    time.sleep(3)
                    continue
                raise ErroreMotore(f"Servizio AI non raggiungibile: {e}")

    def chat(self, system, user, temperature=0.2, json_mode=False) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.tipo == "ollama":
            payload = {"model": self.modello, "messages": msgs, "stream": False,
                       "options": {"temperature": temperature, "num_ctx": 8192}}
            if json_mode:
                payload["format"] = "json"

            def f():
                with _post(OLLAMA_HOST + "/api/chat", payload) as r:
                    return json.load(r)["message"]["content"]
        else:
            payload = {"model": self.modello, "messages": msgs, "temperature": temperature}

            def f():
                with _post(self.base_url + "/chat/completions", payload,
                           {"Authorization": f"Bearer {self.api_key}"}) as r:
                    return json.load(r)["choices"][0]["message"]["content"]
        return self._retry(f)

    def embed(self, testi) -> list:
        if self.tipo != "ollama" or not self.embed_ok:
            raise ErroreMotore("Embeddings non disponibili")
        out = []
        for i in range(0, len(testi), 16):
            lotto = [t[:2000] for t in testi[i:i + 16]]

            def f(lotto=lotto):
                with _post(OLLAMA_HOST + "/api/embed", {"model": MODELLO_EMBED, "input": lotto}) as r:
                    return json.load(r)["embeddings"]

            out += self._retry(f)
        return out
