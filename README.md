# Sbobina

Dalla registrazione di una lezione alla sbobina pronta, **sul tuo computer**: l'audio non viene mai inviato a nessuno.

Sbobina trascrive l'audio, riscrive il testo in forma impersonale con un'AI, lo controlla automaticamente (omissioni, invenzioni, forma non impersonale), ti lascia modificarlo e scegliere le slide da inserire, ed esporta in Word e PDF.

## Come funziona

1. Carichi l'audio (anche più parti) oppure una trascrizione `.txt` già pronta.
2. Compili i dati della lezione: materia, numero, data, docente, sbobinatori.
3. Facoltativo: carichi le slide del docente (PDF o PowerPoint), vecchie sbobine come modello di stile e le regole di formattazione del gruppo.
4. **Genera la bozza**, poi modifichi il testo e scegli dove mettere le slide.
5. **Esporta Word e PDF**. I file finiscono in `Documenti/Sbobine/<materia_numero_data>`.

Una sbobina generata dall'AI va sempre riletta prima di usarla.

## Scarica e usa

Il repository contiene due pacchetti, uno per sistema operativo. Scarica la cartella che ti serve:

| Sistema | Cartella | Si avvia con |
| --- | --- | --- |
| Windows | [`Sbobina-Windows`](Sbobina-Windows) | `Avvia Sbobina.bat` |
| macOS | [`Sbobina-Mac`](Sbobina-Mac) | `Avvia Sbobina.command` |

La prima volta l'avvio configura tutto da solo (Python, librerie, Ollama): serve internet e qualche minuto. Le istruzioni complete sono nel file `LEGGIMI.txt` di ogni cartella.

### Note per sistema

- **Windows**: se c'è una scheda video NVIDIA, la trascrizione usa la GPU. Con `build_exe.bat` si crea `Sbobina.exe`, e con `installer.iss` (Inno Setup) un installatore.
- **macOS**: sui Mac con chip Apple la trascrizione è accelerata con `mlx-whisper`; sui Mac Intel si usa la CPU. Con `build_app_mac.command` si crea `Sbobina.app` e un `.dmg`.

## Motore AI

- **Locale con Ollama** (consigliato): gratuito e privato, tutto resta sul tuo computer.
- **Online** (opzionale): API compatibile OpenAI (Groq, Gemini, OpenRouter...) con una tua chiave. In questo caso il *testo* della lezione viene inviato al servizio scelto; l'audio resta sempre sul PC.

## Struttura del codice

I moduli Python sono identici nei due pacchetti:

- `main.py`: avvio dell'app in una finestra propria
- `app.py`: interfaccia (Gradio)
- `pipeline.py`: flusso in due fasi, bozza ed esportazione
- `trascrizione.py`: trascrizione audio (faster-whisper, mlx-whisper)
- `riscrittura.py`, `llm.py`: riscrittura, revisione e client del motore AI
- `slides.py`, `similarita.py`: lettura delle slide e abbinamento al testo
- `esporta.py`, `documenti.py`: creazione di Word e PDF, lettura dei documenti

## Licenza

[MIT](Sbobina-Windows/LICENSE)
