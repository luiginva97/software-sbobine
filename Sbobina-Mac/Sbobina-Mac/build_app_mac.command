#!/bin/bash
# Crea Sbobina.app e un file .dmg da condividere. Va eseguito su un Mac.
cd "$(dirname "$0")" || exit 1
bash "./Avvia Sbobina.command" /setup || exit 1

.venv/bin/python -m pip install pyinstaller || exit 1

EXTRA=""
if [ "$(uname -m)" = "arm64" ]; then
  EXTRA="--collect-all mlx --collect-all mlx_whisper"
fi

.venv/bin/python -m PyInstaller --noconfirm --clean --name Sbobina --windowed \
  --osx-bundle-identifier it.sbobina.app \
  --collect-all gradio --collect-all gradio_client \
  --collect-all safehttpx --collect-all groovy \
  --collect-all faster_whisper --collect-all ctranslate2 \
  --collect-all onnxruntime --collect-all tokenizers --collect-all av \
  --collect-all webview \
  --collect-all docx --collect-all pymupdf --collect-all pptx --collect-all reportlab \
  $EXTRA \
  main.py || { echo "Errore durante la creazione."; read -n 1 -s -r -p "Premi un tasto..."; exit 1; }

# firma "ad hoc" (necessaria perche' l'app parta sui Mac con chip Apple)
codesign --force --deep --sign - dist/Sbobina.app 2>/dev/null

DMG="dist/Sbobina-mac-$(uname -m).dmg"
rm -f "$DMG"
hdiutil create -volname "Sbobina" -srcfolder dist/Sbobina.app -ov -format UDZO "$DMG"

echo
echo "=================================================="
echo " Fatto!"
echo "   App:        dist/Sbobina.app"
echo "   Da condividere: $DMG"
echo " Il file funziona solo su Mac con lo stesso tipo di chip di questo"
echo " (Apple Silicon oppure Intel). Chi lo scarica deve fare clic destro >"
echo " Apri la prima volta (l'app non e' firmata con un account Apple Developer)."
echo "=================================================="
read -n 1 -s -r -p "Premi un tasto per chiudere..."
