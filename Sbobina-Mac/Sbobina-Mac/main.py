"""Avvio dell'app Sbobina in una finestra propria (niente terminale, niente browser)."""
import os
import sys
import time
import traceback
from pathlib import Path

# Privacy: nessuna telemetria
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

try:
    from documenti import cartella_documenti
    LOG_DIR = cartella_documenti() / "Sbobine"
except Exception:
    LOG_DIR = Path.home() / "Documents" / "Sbobine"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Senza console (pythonw / exe) stdout non esiste: scrivo su un file di log
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(LOG_DIR / "sbobina.log", "a", encoding="utf-8", buffering=1)


def setup_cuda_dlls():
    """Rende visibili le DLL NVIDIA (cuBLAS/cuDNN) installate via pip o incluse nell'exe."""
    if sys.platform != "win32":
        return
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    else:
        import site
        bases += [Path(p) for p in site.getsitepackages()]
    for base in bases:
        for b in (base / "nvidia").glob("*/bin"):
            os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(str(b))
            except Exception:
                pass


def mostra_errore(msg: str):
    print(msg)
    dettagli = msg + f"\n\nDettagli in: {LOG_DIR / 'sbobina.log'}"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, dettagli, "Sbobina - errore", 0x10)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess
            testo = dettagli.replace("\\", "\\\\").replace('"', "'")[:900]
            subprocess.run(["osascript", "-e",
                            f'display dialog "{testo}" with title "Sbobina - errore" buttons {{"OK"}} with icon stop'])
        except Exception:
            pass


def main():
    setup_cuda_dlls()
    from app import demo

    demo.queue()
    import pipeline
    pipeline.OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _, url, _ = demo.launch(
        server_name="127.0.0.1", inbrowser=False, prevent_thread_lock=True, quiet=True,
        allowed_paths=[str(pipeline.OUT_ROOT)],   # permette a Gradio di mostrare/scaricare i file in Documenti\Sbobine
    )

    try:
        import webview
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True
        except Exception:
            pass
        webview.create_window("Sbobina", url, width=1100, height=860, min_size=(800, 600))
        webview.start()
    except Exception:
        print("pywebview non disponibile, apro il browser:\n" + traceback.format_exc())
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    demo.close()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        mostra_errore("Errore all'avvio:\n" + traceback.format_exc()[-1200:])
        sys.exit(1)
