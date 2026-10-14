import json
import locale
import os
import shutil
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

INTERVALLO_SECONDI = 10
NOME_BACKUP = "backup"
NOME_CONFIG = "config.json"
NOME_LINGUE = "lingue"


def cartella_programma():
    """Cartella della chiavetta: accanto all'exe se il programma è impacchettato, altrimenti accanto allo script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def cartelle_lingue():
    """Prima le lingue incluse nel programma, poi quelle accanto all'exe o allo script."""
    candidati = []
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", "")
        if bundle:
            candidati.append(os.path.join(bundle, NOME_LINGUE))
    candidati.append(os.path.join(cartella_programma(), NOME_LINGUE))
    cartelle = []
    for cartella in candidati:
        assoluta = os.path.abspath(cartella)
        if assoluta not in cartelle:
            cartelle.append(assoluta)
    return cartelle


BASE_DIR = cartella_programma()
CARTELLA_BACKUP = os.path.join(BASE_DIR, NOME_BACKUP)
FILE_CONFIG = os.path.join(BASE_DIR, NOME_CONFIG)


def percorso_dentro(percorso, contenitore):
    """True se percorso è uguale a contenitore oppure sta al suo interno."""
    percorso = os.path.abspath(percorso)
    contenitore = os.path.abspath(contenitore)
    try:
        comune = os.path.commonpath([percorso, contenitore])
    except ValueError:
        return False
    return comune == contenitore


def destinazione_per(sorgente):
    """Ricostruisce il percorso sorgente dentro la cartella backup della chiavetta."""
    assoluto = os.path.abspath(sorgente)
    unita, resto = os.path.splitdrive(assoluto)
    parti = []
    if unita:
        nome_unita = unita.replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
        if nome_unita:
            parti.append(nome_unita)
    for parte in resto.replace("/", "\\").split("\\"):
        if parte and parte not in (".", ".."):
            parti.append(parte)
    return os.path.join(CARTELLA_BACKUP, *(parti or ["cartella"]))


def formatta(testo, valori):
    if not valori:
        return testo
    sicuri = {chiave: str(valore).replace("{", "{{").replace("}", "}}") for chiave, valore in valori.items()}
    try:
        return testo.format(**sicuri)
    except (KeyError, IndexError, ValueError):
        return testo


def carica_lingue():
    lingue = {}
    for cartella in cartelle_lingue():
        if not os.path.isdir(cartella):
            continue
        for nome_file in sorted(os.listdir(cartella)):
            if not nome_file.lower().endswith(".json"):
                continue
            percorso = os.path.join(cartella, nome_file)
            try:
                with open(percorso, encoding="utf-8-sig") as file:
                    dati = json.load(file)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(dati, dict) or not isinstance(dati.get("testi"), dict):
                continue
            codice = str(dati.get("codice") or os.path.splitext(nome_file)[0])
            codice = "".join(carattere for carattere in codice.lower() if carattere.isalnum() or carattere in "_-")
            if not codice:
                continue
            testi = {str(chiave): valore for chiave, valore in dati["testi"].items() if isinstance(valore, str)}
            if codice in lingue:
                lingue[codice]["testi"].update(testi)
                if isinstance(dati.get("nome"), str) and dati["nome"].strip():
                    lingue[codice]["nome"] = dati["nome"].strip()
            else:
                nome = dati.get("nome")
                lingue[codice] = {
                    "codice": codice,
                    "nome": nome.strip() if isinstance(nome, str) and nome.strip() else codice,
                    "testi": testi,
                }
    return lingue


def lingua_iniziale(lingue):
    codice = ""
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            codice = locale.windows_locale.get(lang_id, "")
        except (OSError, AttributeError):
            codice = ""
    if not codice:
        try:
            codice = locale.getlocale()[0] or ""
        except (TypeError, ValueError):
            codice = ""
    primario = codice.replace("-", "_").split("_")[0].lower()
    if primario in lingue:
        return primario
    if "it" in lingue:
        return "it"
    return next(iter(lingue))


def carica_config():
    try:
        with open(FILE_CONFIG, encoding="utf-8") as file:
            dati = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return dati if isinstance(dati, dict) else {}


def aggiorna_config(**campi):
    dati = carica_config()
    dati.update(campi)
    with open(FILE_CONFIG, "w", encoding="utf-8") as file:
        json.dump(dati, file, ensure_ascii=False, indent=2)


def copia_albero(sorgente, destinazione, ferma, registra, traduci):
    """Copia file e sottocartelle. Sovrascrive solo se l'origine è più recente."""
    copiati = 0
    invariati = 0
    errori = 0
    backup_abs = os.path.abspath(CARTELLA_BACKUP)

    for radice, cartelle, file_nomi in os.walk(sorgente):
        if ferma.is_set():
            break
        cartelle[:] = [
            nome
            for nome in cartelle
            if not percorso_dentro(os.path.join(radice, nome), backup_abs)
        ]
        relativo = os.path.relpath(radice, sorgente)
        cartella_dest = destinazione if relativo == "." else os.path.join(destinazione, relativo)
        try:
            os.makedirs(cartella_dest, exist_ok=True)
        except OSError as errore:
            errori += 1
            registra(traduci("errore_cartella", cartella=relativo, errore=errore))
            continue

        for nome in file_nomi:
            if ferma.is_set():
                break
            origine = os.path.join(radice, nome)
            if percorso_dentro(origine, backup_abs):
                continue
            arrivo = os.path.join(cartella_dest, nome)
            if os.path.abspath(origine) == os.path.abspath(arrivo):
                continue
            try:
                if os.path.isfile(arrivo) and os.path.getmtime(origine) <= os.path.getmtime(arrivo):
                    invariati += 1
                    continue
                shutil.copy2(origine, arrivo)
                copiati += 1
                mostra = nome if relativo == "." else os.path.join(relativo, nome)
                registra(traduci("copiato", file=mostra))
            except OSError as errore:
                errori += 1
                registra(traduci("errore_file", file=nome, errore=errore))

    return copiati, invariati, errori


class BackupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("720x520")
        self.minsize(640, 460)
        self._ferma = threading.Event()
        self._thread = None
        self._stato_chiave = "stato_attesa"
        self._stato_args = {}
        self._codici_lingua = []

        self.lingue = carica_lingue()
        if not self.lingue:
            messagebox.showerror(
                "Backup file su USB",
                "Nessun file di lingua trovato nella cartella lingue.\n"
                "No language file found in the lingue folder.",
            )
            self.destroy()
            return

        dati = carica_config()
        codice = dati.get("lingua") if isinstance(dati.get("lingua"), str) else ""
        self.codice_lingua = codice if codice in self.lingue else lingua_iniziale(self.lingue)
        cartella = dati.get("cartella") if isinstance(dati.get("cartella"), str) else ""

        self.cartella = tk.StringVar(value=cartella)
        self.destinazione = tk.StringVar(value=self._testo_destinazione())
        self.stato = tk.StringVar(value="")
        self.cartella.trace_add("write", lambda *_: self.destinazione.set(self._testo_destinazione()))

        self._costruisci()
        self.applica_lingua(self.codice_lingua, salva=False)
        self.protocol("WM_DELETE_WINDOW", self._chiudi)

    def t(self, chiave, **valori):
        for codice in (self.codice_lingua, "it", "en"):
            pacchetto = self.lingue.get(codice)
            if not pacchetto:
                continue
            testo = pacchetto["testi"].get(chiave)
            if isinstance(testo, str):
                return formatta(testo, valori)
        return formatta(chiave, valori) if valori else chiave

    def imposta_stato(self, chiave, **valori):
        self._stato_chiave = chiave
        self._stato_args = valori
        self.stato.set(self.t(chiave, **valori))

    def _testo_destinazione(self):
        cartella = self.cartella.get().strip()
        if not cartella:
            return os.path.join(CARTELLA_BACKUP, "...")
        return destinazione_per(cartella)

    def _costruisci(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        contenitore = ttk.Frame(self, padding=16)
        contenitore.grid(row=0, column=0, sticky="nsew")
        contenitore.columnconfigure(0, weight=1)
        contenitore.rowconfigure(7, weight=1)

        intestazione = ttk.Frame(contenitore)
        intestazione.grid(row=0, column=0, sticky="ew")
        intestazione.columnconfigure(0, weight=1)
        self.etichetta_titolo = ttk.Label(intestazione, font=("Segoe UI", 16, "bold"))
        self.etichetta_titolo.grid(row=0, column=0, sticky="w")
        lingua = ttk.Frame(intestazione)
        lingua.grid(row=0, column=1, sticky="e")
        self.etichetta_lingua = ttk.Label(lingua)
        self.etichetta_lingua.grid(row=0, column=0, padx=(0, 6))
        self.combo_lingua = ttk.Combobox(lingua, state="readonly", width=16)
        self.combo_lingua.grid(row=0, column=1)
        self.combo_lingua.bind("<<ComboboxSelected>>", self._on_lingua)

        self.etichetta_descrizione = ttk.Label(contenitore, wraplength=660)
        self.etichetta_descrizione.grid(row=1, column=0, sticky="w", pady=(4, 14))

        self.riquadro_scelta = ttk.LabelFrame(contenitore, padding=10)
        self.riquadro_scelta.grid(row=2, column=0, sticky="ew")
        self.riquadro_scelta.columnconfigure(0, weight=1)
        self.campo_cartella = ttk.Entry(self.riquadro_scelta, textvariable=self.cartella)
        self.campo_cartella.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.bottone_sfoglia = ttk.Button(self.riquadro_scelta, command=self._scegli_cartella)
        self.bottone_sfoglia.grid(row=0, column=1)

        self.etichetta_destinazione = ttk.Label(contenitore)
        self.etichetta_destinazione.grid(row=3, column=0, sticky="w", pady=(12, 2))
        ttk.Label(contenitore, textvariable=self.destinazione, wraplength=660).grid(row=4, column=0, sticky="ew")

        comandi = ttk.Frame(contenitore)
        comandi.grid(row=5, column=0, sticky="w", pady=(14, 8))
        self.bottone_avvia = ttk.Button(comandi, command=self._avvia)
        self.bottone_avvia.grid(row=0, column=0, padx=(0, 8))
        self.bottone_ferma = ttk.Button(comandi, command=self._ferma_monitoraggio, state="disabled")
        self.bottone_ferma.grid(row=0, column=1)

        ttk.Label(contenitore, textvariable=self.stato, wraplength=660).grid(row=6, column=0, sticky="w", pady=(4, 8))

        self.riquadro_registro = ttk.LabelFrame(contenitore, padding=8)
        self.riquadro_registro.grid(row=7, column=0, sticky="nsew", pady=(4, 0))
        self.riquadro_registro.columnconfigure(0, weight=1)
        self.riquadro_registro.rowconfigure(0, weight=1)
        self.testo = tk.Text(self.riquadro_registro, height=12, wrap="word", state="disabled")
        barra = ttk.Scrollbar(self.riquadro_registro, command=self.testo.yview)
        self.testo.configure(yscrollcommand=barra.set)
        self.testo.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")

    def _aggiorna_combo(self):
        self._codici_lingua = sorted(self.lingue, key=lambda codice: self.lingue[codice]["nome"].lower())
        self.combo_lingua["values"] = [self.lingue[codice]["nome"] for codice in self._codici_lingua]
        self.combo_lingua.current(self._codici_lingua.index(self.codice_lingua))

    def applica_lingua(self, codice, salva):
        if codice not in self.lingue:
            return
        self.codice_lingua = codice
        self.title(self.t("titolo_finestra"))
        self.etichetta_titolo.configure(text=self.t("titolo"))
        self.etichetta_descrizione.configure(text=self.t("descrizione"))
        self.etichetta_lingua.configure(text=self.t("lingua"))
        self.riquadro_scelta.configure(text=self.t("cartella_da_monitorare"))
        self.bottone_sfoglia.configure(text=self.t("sfoglia"))
        self.etichetta_destinazione.configure(text=self.t("destinazione"))
        self.bottone_avvia.configure(text=self.t("avvia"))
        self.bottone_ferma.configure(text=self.t("ferma"))
        self.riquadro_registro.configure(text=self.t("registro"))
        self.imposta_stato(self._stato_chiave, **self._stato_args)
        self._aggiorna_combo()
        if salva:
            try:
                aggiorna_config(lingua=codice)
            except OSError as errore:
                messagebox.showerror(self.t("titolo_finestra"), self.t("errore_salva_lingua", errore=errore))

    def _on_lingua(self, _evento=None):
        selezione = self.combo_lingua.current()
        if selezione < 0 or selezione >= len(self._codici_lingua):
            return
        codice = self._codici_lingua[selezione]
        if codice != self.codice_lingua:
            self.applica_lingua(codice, salva=True)

    def _scegli_cartella(self):
        iniziale = self.cartella.get().strip()
        if not os.path.isdir(iniziale):
            iniziale = os.path.expanduser("~")
        scelta = filedialog.askdirectory(title=self.t("titolo_dialogo_cartella"), initialdir=iniziale)
        if scelta:
            self.cartella.set(scelta)
            try:
                aggiorna_config(cartella=scelta)
            except OSError as errore:
                messagebox.showerror(self.t("titolo_finestra"), self.t("errore_salva_scelta", errore=errore))

    def _registra(self, messaggio):
        def aggiungi():
            ora = datetime.now().strftime("%H:%M:%S")
            self.testo.configure(state="normal")
            self.testo.insert("end", f"[{ora}] {messaggio}\n")
            self.testo.see("end")
            self.testo.configure(state="disabled")

        self.after(0, aggiungi)

    def _avvia(self):
        cartella = self.cartella.get().strip()
        if not cartella or not os.path.isdir(cartella):
            messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_cartella_mancante"))
            return
        if percorso_dentro(cartella, CARTELLA_BACKUP) or percorso_dentro(CARTELLA_BACKUP, cartella):
            messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_cartella_backup"))
            return
        try:
            aggiorna_config(cartella=cartella)
            os.makedirs(CARTELLA_BACKUP, exist_ok=True)
        except OSError as errore:
            messagebox.showerror(self.t("titolo_finestra"), self.t("errore_prepara", errore=errore))
            return

        self._ferma.clear()
        self.bottone_avvia.configure(state="disabled")
        self.bottone_ferma.configure(state="normal")
        self.bottone_sfoglia.configure(state="disabled")
        self.campo_cartella.configure(state="disabled")
        self.imposta_stato("monitoraggio_avviato")
        self._registra(self.t("log_monitoraggio", cartella=cartella))
        self._registra(self.t("log_destinazione", destinazione=destinazione_per(cartella)))
        self._thread = threading.Thread(target=self._ciclo, args=(cartella,), daemon=True)
        self._thread.start()

    def _ferma_monitoraggio(self):
        self._ferma.set()
        self.imposta_stato("arresto")
        self.bottone_ferma.configure(state="disabled")

    def _ciclo(self, cartella):
        destinazione = destinazione_per(cartella)
        while not self._ferma.is_set():
            if not os.path.isdir(cartella):
                self._registra(self.t("log_cartella_persa"))
                self.after(0, lambda: self.imposta_stato("stato_cartella_persa"))
                break
            self.after(0, lambda: self.imposta_stato("stato_controllo"))
            copiati, invariati, errori = copia_albero(cartella, destinazione, self._ferma, self._registra, self.t)
            if self._ferma.is_set():
                break
            valori = {
                "ora": datetime.now().strftime("%H:%M:%S"),
                "copiati": copiati,
                "invariati": invariati,
                "errori": errori,
            }
            self._registra(self.t("riepilogo", **valori))
            self.after(0, lambda dati=valori: self.imposta_stato("riepilogo", **dati))
            for _ in range(INTERVALLO_SECONDI * 10):
                if self._ferma.is_set():
                    break
                time.sleep(0.1)
        self.after(0, self._monitoraggio_fermato)

    def _monitoraggio_fermato(self):
        self.bottone_avvia.configure(state="normal")
        self.bottone_ferma.configure(state="disabled")
        self.bottone_sfoglia.configure(state="normal")
        self.campo_cartella.configure(state="normal")
        if self._stato_chiave == "arresto":
            self.imposta_stato("monitoraggio_fermato")
        self._registra(self.t("log_fermato"))

    def _chiudi(self):
        self._ferma.set()
        self.destroy()


if __name__ == "__main__":
    BackupApp().mainloop()
