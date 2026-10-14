[Italiano](#italiano) · [English](#english)

# Beckup da USB

Copia una cartella sul supporto dove si trova il programma, sottocartelle comprese, e aggiorna solo i file più recenti.

Copies a folder onto the drive where the program lives, including subfolders, and updates only newer files.

Repository: [github.com/AndyDL24/Beckup-da-USB](https://github.com/AndyDL24/Beckup-da-USB)

## Italiano

### A cosa serve

Il programma sta sulla chiavetta USB. Chi la usa sceglie la cartella da tenere d'occhio: il programma la copia, insieme alle sottocartelle, in una cartella `backup` accanto al programma.

`E:\COOP` finisce per esempio in `backup\E\COOP`.

Un file viene copiato se in destinazione non c'è ancora, oppure se quello di origine ha una data di modifica più recente. I file già aggiornati restano com'è. I file tolti dalla cartella di origine non vengono cancellati dal backup.

Il controllo si ripete ogni 10 secondi, finché non si preme **Ferma**. L'ultima cartella e l'ultima lingua restano in `config.json`, accanto al programma. Quel file è solo locale e non fa parte della repository.

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
4. Lascia invariate le parole tra graffe: `{cartella}`, `{destinazione}`, `{errore}`, `{ora}`, `{copiati}`, `{invariati}`, `{errori}`, `{file}`.
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

The program lives on the USB drive. The person using it chooses a folder to watch. The program copies that folder, including subfolders, into a `backup` folder next to the program.

For example, `E:\COOP` is stored as `backup\E\COOP`.

A file is copied when it is missing from the destination, or when the source file has a newer modification time. Files that are already up to date are left unchanged. Files removed from the source folder are not deleted from the backup.

The check repeats every 10 seconds until **Stop** is pressed. The last folder and language are stored in `config.json` next to the program. That file is local and is not part of the repository.

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
4. Leave the words in braces unchanged: `{cartella}`, `{destinazione}`, `{errore}`, `{ora}`, `{copiati}`, `{invariati}`, `{errori}`, `{file}`.
5. Save the file as UTF-8 and open a pull request.

If a sentence is missing, the program uses the Italian text, then the English one. At startup it reads the JSON files shipped with the program and, when present, the `lingue` folder next to the executable or the script.

### Build the executable

On the computer that prepares the USB drive, from the project folder:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onefile --name BeckupFileUSB --add-data "lingue;lingue" BeckupFileUSB.py
```

The built file is `dist\BeckupFileUSB.exe`. Copy the executable to the USB drive. Copy the `lingue` folder too only when you want extra languages.
