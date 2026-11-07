@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sbobina

if exist ".venv\setup_ok" goto run

echo ==================================================
echo  Prima configurazione di Sbobina (solo la prima volta)
echo  Serve internet e qualche minuto. Non chiudere la finestra.
echo ==================================================
echo.

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if defined PY goto haspython

echo Python non trovato: provo a installarlo automaticamente...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto nopython
echo.
echo Python installato. CHIUDI questa finestra e fai di nuovo doppio clic su "Avvia Sbobina".
pause
exit /b 0

:haspython
if exist ".venv" rmdir /s /q ".venv"
%PY% -m venv .venv
if errorlevel 1 goto errore
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto errore

rem Se c'e' una scheda video NVIDIA installo anche le librerie per usarla
nvidia-smi >nul 2>nul
if not errorlevel 1 (
  echo Scheda NVIDIA trovata: installo le librerie GPU...
  ".venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
)

rem Motore AI locale gratuito (Ollama), se manca
where ollama >nul 2>nul
if errorlevel 1 (
  echo Installo Ollama, il motore AI locale gratuito...
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
)

echo ok> ".venv\setup_ok"
echo.
echo Configurazione completata!

:run
if /i "%~1"=="/setup" exit /b 0
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:nopython
echo.
echo Non sono riuscito a installare Python da solo.
echo Scaricalo da https://www.python.org/downloads/ e durante l'installazione
echo spunta la casella "Add Python to PATH". Poi riapri questo file.
pause
exit /b 1

:errore
echo.
echo Si e' verificato un errore durante la configurazione.
echo Controlla la connessione internet e riprova.
pause
exit /b 1
