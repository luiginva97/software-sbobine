"""Trascrizione audio: faster-whisper (CPU / GPU NVIDIA), whisper.cpp con Vulkan (GPU AMD e altre)
oppure mlx-whisper (GPU dei Mac Apple Silicon)."""
import collections
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
from pathlib import Path

_models = {}
_force_cpu = False
_mlx_fallito = False
_vulkan_fallito = False
_amd_cache = None

# Modelli GGML (whisper.cpp) dal repository ufficiale su Hugging Face
GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
GGML_MODELLI = {
    "small": "ggml-small-q5_1.bin",
    "medium": "ggml-medium-q5_0.bin",
    "large-v3": "ggml-large-v3-q5_0.bin",
    "turbo": "ggml-large-v3-turbo-q5_0.bin",
}

MLX_MODELLI = {
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


# ---------------------------------------------------------------- hardware
def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _mlx_disponibile() -> bool:
    if _mlx_fallito or not _apple_silicon():
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("mlx_whisper") is not None
    except Exception:
        return False


def gpu_available() -> bool:
    """GPU NVIDIA utilizzabile da faster-whisper."""
    if _force_cpu:
        return False
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _cartelle_vulkan() -> list:
    """Cartelle dove cercare whisper-cli (build con backend Vulkan)."""
    cartelle = []
    env = os.environ.get("SBOBINA_WHISPER_CLI")
    if env:
        cartelle.append(Path(env).parent)
    cartelle.append(Path.home() / ".sbobina" / "whisper-vulkan")
    cartelle.append(Path(__file__).resolve().parent / "vulkan")
    if getattr(sys, "frozen", False):
        cartelle.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "vulkan")
        cartelle.append(Path(sys.executable).parent / "vulkan")
    return cartelle


def vulkan_exe():
    """Percorso di whisper-cli (Vulkan) se presente, altrimenti None."""
    env = os.environ.get("SBOBINA_WHISPER_CLI")
    if env and Path(env).is_file():
        return Path(env)
    nome = "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"
    for c in _cartelle_vulkan():
        p = c / nome
        if p.is_file():
            return p
    return None


def _vulkan_disponibile() -> bool:
    return not _vulkan_fallito and vulkan_exe() is not None


def amd_gpu_rilevata() -> bool:
    """True se Windows elenca una scheda video AMD/Radeon (serve solo per i messaggi all'utente)."""
    global _amd_cache
    if _amd_cache is None:
        _amd_cache = False
        if sys.platform == "win32":
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_VideoController).Name"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                _amd_cache = bool(re.search(r"\b(AMD|Radeon)\b", r.stdout or "", re.I))
            except Exception:
                _amd_cache = False
    return _amd_cache


def accelerazione() -> str:
    """'apple' (mlx-whisper), 'cuda' (NVIDIA), 'vulkan' (AMD e altre, via whisper.cpp) oppure 'cpu'."""
    if _mlx_disponibile():
        return "apple"
    if gpu_available():
        return "cuda"
    if _vulkan_disponibile():
        return "vulkan"
    return "cpu"


def scegli_modello(scelta: str) -> str:
    if scelta != "auto":
        return scelta
    return {"cuda": "large-v3", "apple": "turbo", "vulkan": "medium"}.get(accelerazione(), "small")


# ---------------------------------------------------------------- faster-whisper
def get_model(size: str):
    from faster_whisper import WhisperModel
    if size == "turbo":          # "turbo" esiste solo per mlx: su CPU uso un modello leggero
        size = "small"
    gpu = gpu_available()
    key = (size, gpu)
    if key not in _models:
        if gpu:
            _models[key] = WhisperModel(size, device="cuda", compute_type="int8_float16")
        else:
            _models[key] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[key]


def _trascrivi_file(path, size, on_progress):
    """Se la GPU dà problemi (librerie mancanti) ripiega sulla CPU."""
    global _force_cpu
    for tentativo in range(2):
        try:
            model = get_model(size)
            segs, info = model.transcribe(path, language="it", vad_filter=True, beam_size=5)
            out = []
            for s in segs:
                out.append((s.start, s.text.strip()))
                if info.duration:
                    on_progress(min(s.end / info.duration, 1.0))
            return out, info.duration
        except RuntimeError:
            if tentativo == 0 and not _force_cpu:
                _force_cpu = True
                _models.clear()
                continue
            raise


# ---------------------------------------------------------------- mlx-whisper (Mac Apple Silicon)
def _trascrivi_mlx(path, size, on_progress):
    import mlx_whisper
    from faster_whisper.audio import decode_audio    # decodifica senza bisogno di ffmpeg
    audio = decode_audio(path, sampling_rate=16000)
    durata = len(audio) / 16000.0
    on_progress(0.0)
    res = mlx_whisper.transcribe(
        audio, path_or_hf_repo=MLX_MODELLI.get(size, MLX_MODELLI["turbo"]),
        language="it", verbose=None, condition_on_previous_text=False,
    )
    on_progress(1.0)
    out = [(float(s["start"]), s["text"].strip()) for s in res.get("segments", []) if s["text"].strip()]
    return out, durata


# ---------------------------------------------------------------- whisper.cpp + Vulkan (GPU AMD)
def _modello_ggml(size, on_progress):
    """Restituisce il percorso del modello GGML, scaricandolo la prima volta."""
    nome = GGML_MODELLI.get(size, GGML_MODELLI["medium"])
    cartella = Path.home() / ".sbobina" / "modelli-ggml"
    cartella.mkdir(parents=True, exist_ok=True)
    dest = cartella / nome
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return dest
    on_progress(0.0)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(GGML_URL + nome, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 1024)
    tmp.replace(dest)
    return dest


def _scrivi_wav(path, audio):
    """Scrive un WAV mono 16 kHz a 16 bit da un array float32 (formato richiesto da whisper-cli)."""
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())


def _trascrivi_vulkan(path, size, on_progress):
    exe = vulkan_exe()
    if exe is None:
        raise RuntimeError("whisper-cli (Vulkan) non trovato")
    modello = _modello_ggml(size, on_progress)
    from faster_whisper.audio import decode_audio    # decodifica senza bisogno di ffmpeg
    audio = decode_audio(path, sampling_rate=16000)
    durata = len(audio) / 16000.0
    on_progress(0.0)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        out = Path(tmp) / "out"
        _scrivi_wav(wav, audio)
        cmd = [str(exe), "-m", str(modello), "-f", str(wav), "-l", "it",
               "-oj", "-of", str(out), "-pp"]
        proc = subprocess.Popen(
            cmd, cwd=str(exe.parent), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        coda = collections.deque(maxlen=15)
        for riga in proc.stderr:
            m = re.search(r"progress\s*=\s*(\d+)\s*%", riga)
            if m:
                on_progress(min(int(m.group(1)) / 100.0, 1.0))
            else:
                coda.append(riga.strip())
        if proc.wait() != 0:
            raise RuntimeError("whisper-cli è terminato con errore: " + " | ".join(coda)[-400:])
        dati = json.loads((Path(str(out) + ".json")).read_text(encoding="utf-8"))
    on_progress(1.0)
    segs = [(float(s["offsets"]["from"]) / 1000.0, s["text"].strip())
            for s in dati.get("transcription", []) if s.get("text", "").strip()]
    return segs, durata


def _trascrivi_auto(path, size, on_progress):
    """Sceglie il motore migliore; se mlx o Vulkan danno errore ripiega su faster-whisper (CPU)."""
    global _mlx_fallito, _vulkan_fallito
    if _mlx_disponibile():
        try:
            return _trascrivi_mlx(path, size, on_progress)
        except Exception as e:
            print("mlx-whisper non utilizzabile, passo a faster-whisper:", repr(e))
            _mlx_fallito = True
            size = "small" if size == "turbo" else size
    elif not gpu_available() and _vulkan_disponibile():
        try:
            return _trascrivi_vulkan(path, size, on_progress)
        except Exception as e:
            print("whisper.cpp (Vulkan) non utilizzabile, passo a faster-whisper (CPU):", repr(e))
            _vulkan_fallito = True
            if size in ("turbo", "large-v3"):      # su CPU i modelli grandi sarebbero troppo lenti
                size = "small"
    return _trascrivi_file(path, size, on_progress)


# ---------------------------------------------------------------- interfaccia comune
def trascrivi(paths, size, on_progress):
    """on_progress(frazione_0_1, descrizione). Restituisce [(secondi, testo)]."""
    tutti, offset = [], 0.0
    for i, p in enumerate(paths):
        desc = f"Trascrizione parte {i + 1} di {len(paths)} (al primo avvio scarico il modello)"
        on_progress(i / len(paths), desc)
        segs, dur = _trascrivi_auto(p, size, lambda f, i=i, d=desc: on_progress((i + f) / len(paths), d))
        tutti += [(offset + t, txt) for t, txt in segs]
        offset += dur or 0.0
    return tutti


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def segmenti_a_testo(segmenti) -> str:
    return "\n".join(f"[{fmt(t)}] {txt}" for t, txt in segmenti)


def testo_a_righe(raw: str) -> list:
    """Toglie i timestamp [hh:mm:ss] e le righe vuote."""
    righe = [re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", r).strip() for r in raw.splitlines()]
    return [r for r in righe if r]
