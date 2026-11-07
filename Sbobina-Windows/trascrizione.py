"""Trascrizione audio: faster-whisper (CPU / GPU NVIDIA) oppure mlx-whisper (GPU dei Mac Apple Silicon)."""
import platform
import re
import sys

_models = {}
_force_cpu = False
_mlx_fallito = False

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


def accelerazione() -> str:
    """'cuda' (NVIDIA), 'apple' (Mac Apple Silicon con mlx-whisper) oppure 'cpu'."""
    if _mlx_disponibile():
        return "apple"
    return "cuda" if gpu_available() else "cpu"


def scegli_modello(scelta: str) -> str:
    if scelta != "auto":
        return scelta
    return {"cuda": "large-v3", "apple": "turbo"}.get(accelerazione(), "small")


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


def _trascrivi_auto(path, size, on_progress):
    """Sceglie il motore migliore; se mlx dà errore ripiega su faster-whisper (CPU)."""
    global _mlx_fallito
    if _mlx_disponibile():
        try:
            return _trascrivi_mlx(path, size, on_progress)
        except Exception as e:
            print("mlx-whisper non utilizzabile, passo a faster-whisper:", repr(e))
            _mlx_fallito = True
            size = "small" if size == "turbo" else size
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
