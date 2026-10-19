[Italiano](#italiano) · [English](#english)

# Beckup da USB

Versione / Version 1.1

Copia una o più cartelle sul supporto dove si trova il programma, sottocartelle comprese. Aggiorna un file se manca, se la dimensione è diversa o se l'origine è più recente.

Copies one or more folders onto the drive where the program lives, including subfolders. A file is updated when it is missing, when the size differs, or when the source is newer.

Repository: [github.com/AndyDL24/Beckup-da-USB](https://github.com/AndyDL24/Beckup-da-USB)

Proprietà di AndyD. Donazioni: [ko-fi.com/andyd24](https://ko-fi.com/andyd24)

Property of AndyD. Donations: [ko-fi.com/andyd24](https://ko-fi.com/andyd24)

## Italiano

### A cosa serve

Il programma sta sulla chiavetta USB. Si scelgono una o più cartelle: il programma le copia, insieme alle sottocartelle, in una cartella `backup` accanto al programma.

`E:\COOP` finisce per esempio in `backup\E\COOP`.

Un file viene copiato se in destinazione non c'è ancora, se la dimensione è diversa, oppure se quello di origine ha una data di modifica più recente. La copia scrive prima un file temporaneo e sostituisce quello di destinazione solo a trasferimento concluso: se l'operazione si interrompe, il file precedente resta intatto. Su FAT e FAT32 la data ha una risoluzione di due secondi, quindi a parità di dimensione una differenza così piccola non viene ricopiata.

Il controllo si ripete all'intervallo scelto: 10 secondi, 30 secondi, 1 minuto o 5 minuti. **Copia ora** fa un solo passaggio. **Apri destinazione** apre la cartella sulla chiavetta. **Nascondi** toglie la finestra e lascia un'icona accanto all'orologio: da lì si riapre il programma o si esce.

Per impostazione predefinita i file tolti dall'origine restano nel backup. Con l'opzione di rispecchiamento quei file vengono spostati in `backup\_cestino`, non cancellati.

Alcuni nomi non vengono copiati, per esempio `Thumbs.db`, `desktop.ini`, `.git`, `node_modules` e i file temporanei di Office. L'elenco si modifica nella casella Esclusioni: i nomi sono separati da virgola e `*` indica una parte qualsiasi del nome. I collegamenti e le giunzioni non vengono seguiti. I percorsi più lunghi del limite storico di Windows vengono comunque copiati.

Se la chiavetta non ha spazio per un file, o viene scollegata, la copia si ferma e il registro lo segnala. Il registro tiene solo le ultime righe.

Cartelle, lingua, intervallo, esclusioni e rispecchiamento restano in `config.json`, accanto al programma. Quel file è solo locale e non fa parte della repository. Se contiene ancora la sola voce `cartella`, il programma la riutilizza.

### Usarlo senza installare Python

Sulla chiavetta basta `BeckupFileUSB.exe`. Chi inserisce la USB non installa nulla: apre l'eseguibile con un doppio clic. Windows a 64 bit non avvia il programma da solo all'inserimento della chiavetta.

L'eseguibile non è in questa repository. Si crea sul computer di chi prepara la chiavetta, come indicato più sotto. Le lingue incluse nell'eseguibile sono quelle presenti al momento della creazione. Una cartella `lingue` messa accanto all'eseguibile aggiunge o sostituisce le lingue senza doverlo ricreare.

### Usarlo con Python

Serve Python 3 su Windows, con tkinter (già incluso nell'installazione normale).

```bash
python BeckupFileUSB.py
```

### Aggiungere una lingua

Ogni lingua è un file JSON nella cartella [`lingue`](lingue). Per aggiungerne una:

1. Copia [`lingue/en.json`](lingue/en.json) in un file nuovo, per esempio `lingue/fr.json`.
2. Cambia `codice` (per esempio `fr`) e `nome` (il nome visibile nel menu, per esempio `Français`).
3. Traduci solo i valori dentro `testi`. Le chiavi restano identiche a quelle di `en.json`.
4. Lascia invariate le parole tra graffe: `{cartella}`, `{cartelle}`, `{destinazione}`, `{errore}`, `{ora}`, `{copiati}`, `{invariati}`, `{spostati}`, `{errori}`, `{file}`, `{richiesti}`, `{liberi}`, `{versione}`.
5. Salva il file in UTF-8 e apri una pull request.

Se manca una frase, il programma usa il testo italiano e poi quello inglese. All'avvio legge i JSON dentro il programma e, se c'è, anche la cartella `lingue` accanto all'eseguibile o allo script.

### Creare l'eseguibile

Sul computer usato per preparare la chiavetta, dalla cartella del progetto:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onefile --name BeckupFileUSB --add-data "lingue;lingue" BeckupFileUSB.py
```

Il file pronto è `dist\BeckupFileUSB.exe`. Vanno copiati sulla chiavetta l'eseguibile e, solo se si vogliono lingue aggiuntive, la cartella `lingue`.

## English

### What it does

The program lives on the USB drive. One or more folders can be chosen. The program copies them, including subfolders, into a `backup` folder next to the program.

For example, `E:\COOP` is stored as `backup\E\COOP`.

A file is copied when it is missing from the destination, when the size differs, or when the source file has a newer modification time. The copy is written to a temporary file first and replaces the destination only after the transfer finishes: if the operation is interrupted, the previous file stays intact. On FAT and FAT32 the modification time has a resolution of two seconds, so a difference that small is not copied again when the size is unchanged.

The check repeats at the chosen interval: 10 seconds, 30 seconds, 1 minute or 5 minutes. **Copy now** does a single pass. **Open destination** opens the folder on the USB drive. **Hide** removes the window and leaves an icon next to the clock: from there the program can be opened again or closed.

By default, files removed from the source stay in the backup. With the mirror option those files are moved to `backup\_cestino`, not deleted.

Some names are not copied, for example `Thumbs.db`, `desktop.ini`, `.git`, `node_modules` and Office temporary files. The list can be changed in the Exclusions field: names are separated by commas, and `*` stands for any part of the name. Links and junctions are not followed. Paths longer than the historical Windows limit are still copied.

If the USB drive does not have room for a file, or it is disconnected, the copy stops and the log says so. The log keeps only the latest lines.

Folders, language, interval, exclusions and mirroring are stored in `config.json`, next to the program. That file is local and is not part of the repository. If it still contains only a `cartella` entry, the program reuses it.

### Use it without installing Python

The USB drive only needs `BeckupFileUSB.exe`. Nothing has to be installed: open the executable with a double click. 64-bit Windows does not start the program by itself when the drive is plugged in.

The executable is not stored in this repository. It is built on the computer that prepares the USB drive, as described below. The languages inside the executable are the ones present at build time. A `lingue` folder placed next to the executable adds or overrides languages without a new build.

### Use it with Python

Python 3 for Windows is required, with tkinter (included in a normal install).

```bash
python BeckupFileUSB.py
```

### Add a language

Each language is a JSON file in the [`lingue`](lingue) folder. To add one:

1. Copy [`lingue/en.json`](lingue/en.json) to a new file, for example `lingue/fr.json`.
2. Change `codice` (for example `fr`) and `nome` (the name shown in the menu, for example `Français`).
3. Translate only the values inside `testi`. Keep the same keys as in `en.json`.
4. Leave the words in braces unchanged: `{cartella}`, `{cartelle}`, `{destinazione}`, `{errore}`, `{ora}`, `{copiati}`, `{invariati}`, `{spostati}`, `{errori}`, `{file}`, `{richiesti}`, `{liberi}`, `{versione}`.
5. Save the file as UTF-8 and open a pull request.

If a sentence is missing, the program uses the Italian text, then the English one. At startup it reads the JSON files shipped with the program and, when present, the `lingue` folder next to the executable or the script.

### Build the executable

On the computer that prepares the USB drive, from the project folder:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onefile --name BeckupFileUSB --add-data "lingue;lingue" BeckupFileUSB.py
```

The built file is `dist\BeckupFileUSB.exe`. Copy the executable to the USB drive. Copy the `lingue` folder too only when you want extra languages.
