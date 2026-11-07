@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Creazione di Sbobina.exe

call "Avvia Sbobina.bat" /setup
if not exist ".venv\setup_ok" (
  echo Configurazione non riuscita.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto errore

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --name Sbobina --windowed ^
  --collect-all gradio --collect-all gradio_client ^
  --collect-all safehttpx --collect-all groovy ^
  --collect-all faster_whisper --collect-all ctranslate2 ^
  --collect-all onnxruntime --collect-all tokenizers --collect-all av ^
  --collect-all webview ^
  --collect-all docx --collect-all pymupdf --collect-all pptx --collect-all reportlab ^
  main.py
if errorlevel 1 goto errore

rem Librerie GPU NVIDIA (se installate): le copio accanto all'exe
if exist ".venv\Lib\site-packages\nvidia" (
  xcopy ".venv\Lib\site-packages\nvidia" "dist\Sbobina\_internal\nvidia" /E /I /Q /Y >nul
)

echo.
echo ==================================================
echo  Fatto! L'app e' in: dist\Sbobina  (doppio clic su Sbobina.exe)
echo  Per creare un vero installatore (Setup.exe) apri installer.iss
echo  con Inno Setup (gratuito, jrsoftware.org) e premi Compila.
echo ==================================================
pause
exit /b 0

:errore
echo.
echo Errore durante la creazione. Copia il messaggio qui sopra per farlo correggere.
pause
exit /b 1
