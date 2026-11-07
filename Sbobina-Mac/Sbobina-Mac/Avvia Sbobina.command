#!/bin/bash
# Avvio di Sbobina su Mac. La prima volta configura tutto da solo.
cd "$(dirname "$0")" || exit 1
# toglie il blocco "scaricato da internet" dai file della cartella
xattr -dr com.apple.quarantine . 2>/dev/null

if [ ! -f ".venv/setup_ok" ]; then
  echo "=================================================="
  echo " Prima configurazione di Sbobina (solo la prima volta)"
  echo " Serve internet e qualche minuto. Non chiudere la finestra."
  echo "=================================================="
  echo

  # 1) Python 3.10-3.13
  PY=""
  for c in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ] && command -v brew >/dev/null 2>&1; then
    echo "Installo Python con Homebrew..."
    brew install python@3.12 && PY="$(brew --prefix python@3.12)/bin/python3.12"
  fi
  if [ -z "$PY" ]; then
    echo
    echo "Non ho trovato Python 3.10-3.13."
    echo "Scaricalo da https://www.python.org/downloads/macos/ , installalo e riapri questo file."
    open "https://www.python.org/downloads/macos/"
    read -n 1 -s -r -p "Premi un tasto per chiudere..."
    exit 1
  fi

  # 2) ambiente e librerie
  rm -rf .venv
  "$PY" -m venv .venv || { echo "Errore nella creazione dell'ambiente."; read -n 1 -s -r -p "Premi un tasto..."; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "Errore durante l'installazione: controlla internet e riprova."; read -n 1 -s -r -p "Premi un tasto..."; exit 1; }

  # 3) Mac Apple Silicon: trascrizione accelerata con mlx-whisper (se fallisce, si usa la CPU)
  if [ "$(uname -m)" = "arm64" ]; then
    echo "Chip Apple Silicon: installo la trascrizione accelerata..."
    .venv/bin/python -m pip install -r requirements-mac.txt || echo "(non installata: userò la CPU)"
  fi

  # 4) Ollama (motore AI locale gratuito)
  if ! command -v ollama >/dev/null 2>&1 && [ ! -d "/Applications/Ollama.app" ]; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installo Ollama, il motore AI locale gratuito..."
      brew install ollama || echo "(Ollama non installato: scaricalo da https://ollama.com/download)"
    else
      echo "Ollama non trovato: scaricalo da https://ollama.com/download e installalo."
    fi
  fi

  echo ok > .venv/setup_ok
  echo
  echo "Configurazione completata!"
fi

if [ "$1" = "/setup" ]; then exit 0; fi

nohup .venv/bin/python main.py > /dev/null 2>&1 &
disown
echo "Sbobina si sta aprendo: puoi chiudere questa finestra."
sleep 2
exit 0
