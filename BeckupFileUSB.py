import ctypes
import errno
import fnmatch
import json
import locale
import os
import queue
import shutil
import stat
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

INTERVALLO_PREDEFINITO = 10
INTERVALLI = (10, 30, 60, 300)
MAX_RIGHE_REGISTRO = 400
TOLLERANZA_FAT = 2
NOME_BACKUP = "backup"
NOME_CESTINO = "_cestino"
NOME_CONFIG = "config.json"
NOME_LINGUE = "lingue"
LINK_KOFI = "https://ko-fi.com/andyd24"
ESCLUSIONI_PREDEFINITE = (
    "Thumbs.db",
    "desktop.ini",
    ".DS_Store",
    ".git",
    "node_modules",
    "__pycache__",
    "~$*",
    "*.tmp",
)
PREFISSO_TEMPORANEO = ".beckup-"
SUFFISSO_TEMPORANEO = ".part"


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
_CACHE_FILESYSTEM = {}


def percorso_esteso(percorso):
    """Percorso utilizzabile anche oltre il limite storico di 260 caratteri."""
    if os.name != "nt":
        return os.path.abspath(percorso)
    if str(percorso).startswith("\\\\?\\"):
        return os.path.abspath(percorso)
    assoluto = os.path.abspath(percorso)
    if assoluto.startswith("\\\\?\\"):
        return assoluto
    if assoluto.startswith("\\\\"):
        return "\\\\?\\UNC\\" + assoluto[2:]
    return "\\\\?\\" + assoluto


def percorso_normale(percorso):
    testo = str(percorso)
    if testo.startswith("\\\\?\\UNC\\"):
        return "\\\\" + testo[8:]
    if testo.startswith("\\\\?\\"):
        return testo[4:]
    return testo


def percorso_dentro(percorso, contenitore):
    """True se percorso è uguale a contenitore oppure sta al suo interno."""
    percorso = os.path.normcase(os.path.abspath(percorso))
    contenitore = os.path.normcase(os.path.abspath(contenitore))
    try:
        comune = os.path.commonpath([percorso, contenitore])
    except ValueError:
        return False
    return comune == contenitore


def cartella_consentita(cartella, cartella_backup):
    return not percorso_dentro(cartella, cartella_backup) and not percorso_dentro(cartella_backup, cartella)


def destinazione_per(sorgente, cartella_backup=None):
    """Ricostruisce il percorso sorgente dentro la cartella backup della chiavetta."""
    if cartella_backup is None:
        cartella_backup = CARTELLA_BACKUP
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
    return os.path.join(cartella_backup, *(parti or ["cartella"]))


def normalizza(percorso):
    return os.path.normcase(os.path.abspath(percorso))


def formatta(testo, valori):
    if not valori:
        return testo
    sicuri = {chiave: str(valore).replace("{", "{{").replace("}", "}}") for chiave, valore in valori.items()}
    try:
        return testo.format(**sicuri)
    except (KeyError, IndexError, ValueError):
        return testo


def formatta_byte(numero):
    numero = max(0, int(numero))
    if numero >= 1024 ** 3:
        return f"{numero / 1024 ** 3:.1f} GB"
    if numero >= 1024 ** 2:
        return f"{numero / 1024 ** 2:.1f} MB"
    if numero >= 1024:
        return f"{numero / 1024:.0f} KB"
    return f"{numero} B"


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


def scrivi_config(dati, percorso=None):
    """Scrive il config su un file temporaneo e lo sostituisce solo a scrittura conclusa."""
    percorso = FILE_CONFIG if percorso is None else percorso
    cartella = os.path.dirname(os.path.abspath(percorso)) or "."
    os.makedirs(cartella, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=cartella)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(dati, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporaneo, percorso)
    except BaseException:
        try:
            os.remove(temporaneo)
        except OSError:
            pass
        raise


def aggiorna_config(**campi):
    dati = carica_config()
    dati.update(campi)
    scrivi_config(dati)


def cartelle_da_config(dati):
    if isinstance(dati, dict) and "cartelle" in dati and isinstance(dati.get("cartelle"), list):
        viste = []
        for voce in dati["cartelle"]:
            if isinstance(voce, str) and voce.strip() and voce.strip() not in viste:
                viste.append(voce.strip())
        return viste
    vecchia = dati.get("cartella") if isinstance(dati, dict) else ""
    if isinstance(vecchia, str) and vecchia.strip():
        return [vecchia.strip()]
    return []


def intervallo_da_config(dati):
    valore = dati.get("intervallo") if isinstance(dati, dict) else None
    if isinstance(valore, str) and valore.isdigit():
        valore = int(valore)
    if isinstance(valore, int) and valore in INTERVALLI:
        return valore
    return INTERVALLO_PREDEFINITO


def analizza_esclusioni(testo):
    parti = []
    for blocco in str(testo).replace("\n", ",").split(","):
        voce = blocco.strip()
        if voce and voce not in parti:
            parti.append(voce)
    return parti


def esclusioni_da_config(dati):
    if not isinstance(dati, dict) or "esclusioni" not in dati:
        return list(ESCLUSIONI_PREDEFINITE)
    valore = dati.get("esclusioni")
    if not isinstance(valore, list):
        return list(ESCLUSIONI_PREDEFINITE)
    return analizza_esclusioni(",".join(voce for voce in valore if isinstance(voce, str)))


def rispecchia_da_config(dati):
    return isinstance(dati, dict) and dati.get("rispecchia") is True


def nome_escluso(nome, esclusioni):
    basso = nome.lower()
    for modello in esclusioni:
        modello = str(modello).strip().lower()
        if not modello:
            continue
        if any(carattere in modello for carattere in "*?["):
            if fnmatch.fnmatch(basso, modello):
                return True
        elif basso == modello:
            return True
    return False


def e_temporaneo(nome):
    return nome.startswith(PREFISSO_TEMPORANEO) and nome.endswith(SUFFISSO_TEMPORANEO)


def accoda_righe(righe, nuove, limite):
    righe.extend(nuove)
    if len(righe) > limite:
        del righe[: len(righe) - limite]
    return righe


def esiste_dir(percorso):
    try:
        return os.path.isdir(percorso_esteso(percorso))
    except OSError:
        return False


def esiste_file(percorso):
    try:
        return os.path.isfile(percorso_esteso(percorso))
    except OSError:
        return False


def supporto_disponibile(base=None):
    return esiste_dir(BASE_DIR if base is None else base)


def azzera_cache_filesystem():
    _CACHE_FILESYSTEM.clear()


def _nome_filesystem(percorso):
    if os.name != "nt":
        return ""
    unita = os.path.splitdrive(os.path.abspath(percorso))[0]
    if not unita:
        return ""
    radice = unita if unita.endswith("\\") else unita + "\\"
    if radice in _CACHE_FILESYSTEM:
        return _CACHE_FILESYSTEM[radice]
    nome = ctypes.create_unicode_buffer(256)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetVolumeInformationW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
        ]
        kernel32.GetVolumeInformationW.restype = ctypes.c_int
        ok = kernel32.GetVolumeInformationW(radice, None, 0, None, None, None, nome, len(nome))
        valore = nome.value.upper() if ok else ""
    except (OSError, AttributeError, ValueError):
        valore = ""
    _CACHE_FILESYSTEM[radice] = valore
    return valore


def destinazione_fat(percorso):
    """FAT e FAT32 registrano la data di modifica solo ogni 2 secondi. exFAT no."""
    return _nome_filesystem(percorso) in ("FAT", "FAT32")


def va_copiato(dimensione_origine, dimensione_arrivo, data_origine, data_arrivo, fat):
    """True se la dimensione è diversa oppure l'origine è più recente.

    A parità di dimensione, su FAT e FAT32 una differenza entro 2 secondi
    dipende dall'arrotondamento della data e non richiede un'altra copia.
    """
    if dimensione_origine != dimensione_arrivo:
        return True
    if data_origine <= data_arrivo:
        return False
    if fat and data_origine <= data_arrivo + TOLLERANZA_FAT:
        return False
    return True


def da_copiare(origine, arrivo):
    if not esiste_file(arrivo):
        return True
    stat_origine = os.stat(percorso_esteso(origine))
    stat_arrivo = os.stat(percorso_esteso(arrivo))
    return va_copiato(
        stat_origine.st_size,
        stat_arrivo.st_size,
        stat_origine.st_mtime,
        stat_arrivo.st_mtime,
        destinazione_fat(arrivo),
    )


def e_collegamento(percorso):
    """True per collegamenti simbolici e giunzioni, che non vanno seguiti."""
    try:
        info = os.lstat(percorso_esteso(percorso))
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    tag = getattr(info, "st_reparse_tag", 0) or 0
    mount = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
    symlink = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
    return tag in (mount, symlink)


def errore_spazio(errore):
    winerror = getattr(errore, "winerror", None)
    return winerror in (39, 112) or errore.errno == errno.ENOSPC


def errore_supporto(errore):
    if not supporto_disponibile():
        return True
    winerror = getattr(errore, "winerror", None)
    return winerror in (21, 31, 53, 54, 55, 1112, 1617)


def spazio_libero(percorso):
    candidato = os.path.abspath(percorso)
    while candidato and not esiste_dir(candidato):
        genitore = os.path.dirname(candidato)
        if genitore == candidato:
            break
        candidato = genitore
    return shutil.disk_usage(percorso_esteso(candidato)).free


def _mostra(relativo, nome):
    if relativo in (".", ""):
        return nome
    return os.path.join(relativo, nome)


class Esito:
    def __init__(self):
        self.copiati = 0
        self.invariati = 0
        self.errori = 0
        self.spostati = 0

    def somma(self, altro):
        self.copiati += altro.copiati
        self.invariati += altro.invariati
        self.errori += altro.errori
        self.spostati += altro.spostati


class CopiaInterrotta(Exception):
    def __init__(self, motivo, esito, **dettagli):
        super().__init__(motivo)
        self.motivo = motivo
        self.esito = esito
        self.dettagli = dettagli


def copia_file_atomica(origine, arrivo):
    """Copia su un file temporaneo e sostituisce la destinazione solo a trasferimento concluso."""
    cartella = os.path.dirname(os.path.abspath(arrivo))
    os.makedirs(percorso_esteso(cartella), exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(
        prefix=PREFISSO_TEMPORANEO,
        suffix=SUFFISSO_TEMPORANEO,
        dir=percorso_esteso(cartella),
    )
    os.close(fd)
    temporaneo = percorso_normale(temporaneo)
    pubblicato = False
    try:
        with open(percorso_esteso(origine), "rb") as ingresso, open(percorso_esteso(temporaneo), "wb") as uscita:
            shutil.copyfileobj(ingresso, uscita, length=1024 * 1024)
            uscita.flush()
            os.fsync(uscita.fileno())
        try:
            shutil.copystat(percorso_esteso(origine), percorso_esteso(temporaneo))
        except OSError:
            pass
        os.replace(percorso_esteso(temporaneo), percorso_esteso(arrivo))
        pubblicato = True
    finally:
        if not pubblicato:
            try:
                os.remove(percorso_esteso(temporaneo))
            except OSError:
                pass


def pulisci_temporanei(cartella):
    try:
        nomi = os.listdir(percorso_esteso(cartella))
    except OSError:
        return
    for nome in nomi:
        if not e_temporaneo(nome):
            continue
        try:
            os.remove(percorso_esteso(os.path.join(cartella, nome)))
        except OSError:
            pass


def visita(radice):
    for dirpath, dirnames, filenames in os.walk(percorso_esteso(radice)):
        yield percorso_normale(dirpath), dirnames, filenames


def _cartella_da_visitare(percorso, nome, esclusioni, backup_abs, registra, traduci, relativo):
    if nome_escluso(nome, esclusioni) or e_temporaneo(nome):
        return False
    if e_collegamento(percorso):
        registra(traduci("log_collegamento", file=_mostra(relativo, nome)))
        return False
    if percorso_dentro(percorso, backup_abs):
        return False
    return True


def copia_albero(sorgente, destinazione, ferma, registra, traduci, esclusioni=(), cartella_backup=None):
    """Copia file e sottocartelle. Aggiorna se la dimensione differisce o l'origine è più recente."""
    if cartella_backup is None:
        cartella_backup = CARTELLA_BACKUP
    sorgente = os.path.abspath(sorgente)
    destinazione = os.path.abspath(destinazione)
    esito = Esito()
    if not supporto_disponibile():
        raise CopiaInterrotta("supporto", esito)
    if not esiste_dir(sorgente):
        raise CopiaInterrotta("cartelle", esito)
    backup_abs = os.path.abspath(cartella_backup)
    try:
        os.makedirs(percorso_esteso(destinazione), exist_ok=True)
    except OSError as errore:
        if errore_supporto(errore):
            raise CopiaInterrotta("supporto", esito) from errore
        esito.errori += 1
        registra(traduci("errore_cartella", cartella=".", errore=errore))
        return esito

    for radice, cartelle, file_nomi in visita(sorgente):
        if ferma.is_set() or not supporto_disponibile():
            if not supporto_disponibile():
                raise CopiaInterrotta("supporto", esito)
            break
        if not esiste_dir(sorgente):
            raise CopiaInterrotta("cartelle", esito)
        relativo = os.path.relpath(radice, sorgente)
        cartelle[:] = [
            nome
            for nome in cartelle
            if _cartella_da_visitare(
                os.path.join(radice, nome),
                nome,
                esclusioni,
                backup_abs,
                registra,
                traduci,
                relativo,
            )
        ]
        cartella_dest = destinazione if relativo == "." else os.path.join(destinazione, relativo)
        try:
            os.makedirs(percorso_esteso(cartella_dest), exist_ok=True)
            pulisci_temporanei(cartella_dest)
        except OSError as errore:
            if errore_supporto(errore):
                raise CopiaInterrotta("supporto", esito) from errore
            esito.errori += 1
            registra(traduci("errore_cartella", cartella=relativo, errore=errore))
            continue

        for nome in file_nomi:
            if ferma.is_set():
                break
            if nome_escluso(nome, esclusioni) or e_temporaneo(nome):
                continue
            origine = os.path.join(radice, nome)
            mostra = _mostra(relativo, nome)
            if e_collegamento(origine):
                registra(traduci("log_collegamento", file=mostra))
                continue
            if percorso_dentro(origine, backup_abs):
                continue
            arrivo = os.path.join(cartella_dest, nome)
            if normalizza(origine) == normalizza(arrivo):
                continue
            try:
                if not da_copiare(origine, arrivo):
                    esito.invariati += 1
                    continue
                dimensione = os.path.getsize(percorso_esteso(origine))
                libero = spazio_libero(cartella_dest)
                if dimensione > libero:
                    raise CopiaInterrotta(
                        "spazio",
                        esito,
                        file=mostra,
                        richiesti=formatta_byte(dimensione),
                        liberi=formatta_byte(libero),
                    )
                copia_file_atomica(origine, arrivo)
            except CopiaInterrotta:
                raise
            except OSError as errore:
                if errore_spazio(errore):
                    raise CopiaInterrotta("spazio", esito, file=mostra) from errore
                if errore_supporto(errore):
                    raise CopiaInterrotta("supporto", esito) from errore
                esito.errori += 1
                registra(traduci("errore_file", file=nome, errore=errore))
                continue
            esito.copiati += 1
            registra(traduci("copiato", file=mostra))
    return esito


def sposta_nel_cestino(percorso, destinazione, cartella_backup, cestino):
    prefisso = os.path.relpath(destinazione, cartella_backup)
    relativo = os.path.relpath(percorso, destinazione)
    arrivo = os.path.join(cestino, relativo) if prefisso == "." else os.path.join(cestino, prefisso, relativo)
    os.makedirs(percorso_esteso(os.path.dirname(arrivo)), exist_ok=True)
    candidato = arrivo
    indice = 1
    while os.path.exists(percorso_esteso(candidato)):
        base, estensione = os.path.splitext(arrivo)
        candidato = f"{base}_{indice}{estensione}"
        indice += 1
    shutil.move(percorso_esteso(percorso), percorso_esteso(candidato))


def sposta_extra(sorgente, destinazione, cestino, ferma, registra, traduci, esclusioni=(), cartella_backup=None):
    """Sposta nel cestino i file della destinazione che non sono più nell'origine."""
    if cartella_backup is None:
        cartella_backup = CARTELLA_BACKUP
    sorgente = os.path.abspath(sorgente)
    destinazione = os.path.abspath(destinazione)
    cartella_backup = os.path.abspath(cartella_backup)
    spostati = 0
    errori = 0
    try:
        if not esiste_dir(sorgente) or not esiste_dir(destinazione):
            if not supporto_disponibile() or not esiste_dir(sorgente):
                raise CopiaInterrotta("supporto" if not supporto_disponibile() else "cartelle", Esito())
            return spostati, errori
        for radice, cartelle, file_nomi in visita(destinazione):
            if ferma.is_set():
                break
            if not esiste_dir(sorgente) or not supporto_disponibile():
                motivo = "supporto" if not supporto_disponibile() else "cartelle"
                raise CopiaInterrotta(motivo, Esito())
            tenute = []
            for nome in cartelle:
                percorso = os.path.join(radice, nome)
                if nome_escluso(nome, esclusioni) or e_temporaneo(nome) or e_collegamento(percorso):
                    continue
                origine = os.path.join(sorgente, os.path.relpath(percorso, destinazione))
                if esiste_dir(origine):
                    tenute.append(nome)
                    continue
                if not esiste_dir(sorgente):
                    raise CopiaInterrotta("cartelle", Esito())
                try:
                    sposta_nel_cestino(percorso, destinazione, cartella_backup, cestino)
                    spostati += 1
                    registra(traduci("log_spostato", file=os.path.relpath(percorso, destinazione)))
                except OSError as errore:
                    if errore_supporto(errore):
                        raise CopiaInterrotta("supporto", Esito()) from errore
                    errori += 1
                    registra(traduci("errore_file", file=nome, errore=errore))
            cartelle[:] = tenute
            for nome in file_nomi:
                if ferma.is_set():
                    break
                if nome_escluso(nome, esclusioni) or e_temporaneo(nome):
                    continue
                percorso = os.path.join(radice, nome)
                if e_collegamento(percorso):
                    continue
                origine = os.path.join(sorgente, os.path.relpath(percorso, destinazione))
                if esiste_file(origine) or esiste_dir(origine):
                    continue
                if not esiste_dir(sorgente):
                    raise CopiaInterrotta("cartelle", Esito())
                try:
                    sposta_nel_cestino(percorso, destinazione, cartella_backup, cestino)
                    spostati += 1
                    registra(traduci("log_spostato", file=os.path.relpath(percorso, destinazione)))
                except OSError as errore:
                    if errore_supporto(errore):
                        raise CopiaInterrotta("supporto", Esito()) from errore
                    errori += 1
                    registra(traduci("errore_file", file=nome, errore=errore))
    except CopiaInterrotta as interruzione:
        interruzione.esito.spostati += spostati
        interruzione.esito.errori += errori
        raise
    return spostati, errori


def attendi(secondi, ferma):
    scadenza = time.monotonic() + secondi
    while not ferma.is_set():
        resto = scadenza - time.monotonic()
        if resto <= 0:
            return False
        time.sleep(min(0.1, resto))
    return True


class IconaTray:
    """Icona nell'area di notifica, solo Windows, senza librerie aggiuntive."""

    _pronto = False
    _user32 = None
    _shell32 = None
    _kernel32 = None
    _wndproc_tipo = None
    _classe_finestra = None
    _nid = None

    def __init__(self, suggerimento):
        if os.name != "nt":
            raise OSError("icona disponibile solo su Windows")
        self._hwnd = None
        self._aggiunta = False
        self._eventi = []
        self._proc = None
        self._classe = f"BeckupFileUSBTray{os.getpid()}_{id(self)}"
        self._istanza = None
        try:
            self._crea(suggerimento[:127])
        except OSError:
            self.chiudi()
            raise
        except Exception as errore:
            self.chiudi()
            raise OSError(str(errore)) from errore

    @classmethod
    def _prepara(cls):
        if cls._pronto:
            return
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wndproc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HICON),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_ubyte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        user32.LoadIconW.restype = wintypes.HICON
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            ctypes.c_void_p,
        ]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        cls._user32 = user32
        cls._shell32 = shell32
        cls._kernel32 = kernel32
        cls._wndproc_tipo = wndproc
        cls._classe_finestra = WNDCLASSW
        cls._nid = NOTIFYICONDATAW
        cls._pronto = True

    def _crea(self, suggerimento):
        self._prepara()
        user32 = self._user32
        self._istanza = self._kernel32.GetModuleHandleW(None)
        self._proc = self._wndproc_tipo(self._wndproc)
        finestra = self._classe_finestra()
        finestra.lpfnWndProc = self._proc
        finestra.hInstance = self._istanza
        finestra.lpszClassName = self._classe
        if not user32.RegisterClassW(ctypes.byref(finestra)) and ctypes.get_last_error() not in (0, 1410):
            raise OSError(f"RegisterClass ({ctypes.get_last_error()})")
        self._hwnd = user32.CreateWindowExW(
            0x00000080 | 0x08000000,
            self._classe,
            "BeckupFileUSB",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._istanza,
            None,
        )
        if not self._hwnd:
            raise OSError(f"CreateWindow ({ctypes.get_last_error()})")
        icona = user32.LoadIconW(None, ctypes.c_void_p(32512))
        if not icona:
            raise OSError("icona di sistema non disponibile")
        dati = self._nid()
        dati.cbSize = ctypes.sizeof(self._nid)
        dati.hWnd = self._hwnd
        dati.uID = 1
        dati.uFlags = 1 | 2 | 4
        dati.uCallbackMessage = 0x8001
        dati.hIcon = icona
        dati.szTip = suggerimento
        if not self._shell32.Shell_NotifyIconW(0, ctypes.byref(dati)):
            raise OSError(f"Shell_NotifyIcon ({ctypes.get_last_error()})")
        self._dati = dati
        self._aggiunta = True

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == 0x8001:
                codice = int(lparam) & 0xFFFFFFFF
                if codice == 0x0205:
                    self._eventi.append("menu")
                elif codice in (0x0202, 0x0203):
                    self._eventi.append("apri")
                return 0
        except Exception:
            return 0
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def preleva(self):
        user32 = self._user32
        messaggio = wintypes_msg()
        for _ in range(20):
            if not user32.PeekMessageW(ctypes.byref(messaggio), self._hwnd, 0, 0, 1):
                break
            user32.TranslateMessage(ctypes.byref(messaggio))
            user32.DispatchMessageW(ctypes.byref(messaggio))
        eventi = list(self._eventi)
        self._eventi.clear()
        return eventi

    def menu(self, voci):
        user32 = self._user32
        handle = user32.CreatePopupMenu()
        if not handle:
            raise OSError("menu non disponibile")
        try:
            for identificativo, testo in voci:
                user32.AppendMenuW(handle, 0, identificativo, testo)
            punto = wintypes_point()
            user32.GetCursorPos(ctypes.byref(punto))
            user32.SetForegroundWindow(self._hwnd)
            comando = user32.TrackPopupMenu(handle, 0x0002 | 0x0080 | 0x0100, punto.x, punto.y, 0, self._hwnd, None)
            user32.PostMessageW(self._hwnd, 0, 0, 0)
            return int(comando)
        finally:
            user32.DestroyMenu(handle)

    def chiudi(self):
        if self._aggiunta and self._hwnd and self._shell32 is not None:
            try:
                self._shell32.Shell_NotifyIconW(2, ctypes.byref(self._dati))
            except (OSError, AttributeError):
                pass
            self._aggiunta = False
        if self._hwnd and self._user32 is not None:
            self._user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._istanza and self._user32 is not None:
            self._user32.UnregisterClassW(self._classe, self._istanza)
            self._istanza = None


def wintypes_msg():
    from ctypes import wintypes

    return wintypes.MSG()


def wintypes_point():
    from ctypes import wintypes

    return wintypes.POINT()


class BackupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("940x760")
        self.minsize(860, 680)
        self._ferma = threading.Event()
        self._thread = None
        self._motivo = ""
        self._dettagli = {}
        self._una_volta = False
        self._ultimo_riepilogo = {"ora": "--:--:--", "copiati": 0, "invariati": 0, "spostati": 0, "errori": 0}
        self._stato_chiave = "stato_attesa"
        self._stato_args = {}
        self._codici_lingua = []
        self._secondi = INTERVALLO_PREDEFINITO
        self._pronto = False
        self._blocco_eventi = False
        self._in_chiusura = False
        self._tray = None
        self._dopo_log = None
        self._coda = queue.Queue()
        self._righe_log = []

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
        self._secondi = intervallo_da_config(dati)
        self.rispecchia = tk.BooleanVar(value=rispecchia_da_config(dati))
        self.esclusioni = tk.StringVar(value=", ".join(esclusioni_da_config(dati)))
        self.campo_nuovo = tk.StringVar()
        self.destinazione = tk.StringVar(value=CARTELLA_BACKUP)
        self.stato = tk.StringVar(value="")

        self._costruisci()
        for cartella in cartelle_da_config(dati):
            self.lista.insert("end", cartella)
        if self.lista.size():
            self.lista.selection_set(0)
        self._aggiorna_destinazione()
        self.applica_lingua(self.codice_lingua, salva=False)
        self.protocol("WM_DELETE_WINDOW", self._chiudi)
        self.bind("<Configure>", self._adatta_testo)
        self._dopo_log = self.after(200, self._svuota_log)
        self._pronto = True

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

    def _costruisci(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        contenitore = ttk.Frame(self, padding=16)
        contenitore.grid(row=0, column=0, sticky="nsew")
        contenitore.columnconfigure(0, weight=1)
        contenitore.rowconfigure(8, weight=1)

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
        self.bottone_about = ttk.Button(lingua, command=self._mostra_about)
        self.bottone_about.grid(row=0, column=2, padx=(8, 0))

        self.etichetta_descrizione = ttk.Label(contenitore, wraplength=860)
        self.etichetta_descrizione.grid(row=1, column=0, sticky="w", pady=(4, 12))

        self.riquadro_scelta = ttk.LabelFrame(contenitore, padding=10)
        self.riquadro_scelta.grid(row=2, column=0, sticky="ew")
        self.riquadro_scelta.columnconfigure(0, weight=1)
        self.campo_cartella = ttk.Entry(self.riquadro_scelta, textvariable=self.campo_nuovo)
        self.campo_cartella.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.campo_cartella.bind("<Return>", lambda _evento: self._aggiungi_cartella())
        self.bottone_sfoglia = ttk.Button(self.riquadro_scelta, command=self._scegli_cartella)
        self.bottone_sfoglia.grid(row=0, column=1, padx=(0, 8))
        self.bottone_aggiungi = ttk.Button(self.riquadro_scelta, command=self._aggiungi_cartella)
        self.bottone_aggiungi.grid(row=0, column=2)

        elenco = ttk.Frame(self.riquadro_scelta)
        elenco.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        elenco.columnconfigure(0, weight=1)
        self.lista = tk.Listbox(elenco, height=4, activestyle="dotbox", exportselection=False)
        barra_lista = ttk.Scrollbar(elenco, command=self.lista.yview)
        self.lista.configure(yscrollcommand=barra_lista.set)
        self.lista.grid(row=0, column=0, sticky="ew")
        barra_lista.grid(row=0, column=1, sticky="ns")
        self.lista.bind("<<ListboxSelect>>", self._aggiorna_destinazione)
        self.bottone_rimuovi = ttk.Button(elenco, command=self._rimuovi_cartella)
        self.bottone_rimuovi.grid(row=0, column=2, padx=(8, 0), sticky="n")

        self.etichetta_destinazione = ttk.Label(contenitore)
        self.etichetta_destinazione.grid(row=3, column=0, sticky="w", pady=(12, 2))
        self.etichetta_percorso = ttk.Label(contenitore, textvariable=self.destinazione, wraplength=860)
        self.etichetta_percorso.grid(row=4, column=0, sticky="ew")

        opzioni = ttk.Frame(contenitore)
        opzioni.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        opzioni.columnconfigure(1, weight=1)
        self.etichetta_intervallo = ttk.Label(opzioni)
        self.etichetta_intervallo.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.combo_intervallo = ttk.Combobox(opzioni, state="readonly", width=16)
        self.combo_intervallo.grid(row=0, column=1, sticky="w")
        self.combo_intervallo.bind("<<ComboboxSelected>>", self._on_intervallo)
        self.check_rispecchia = ttk.Checkbutton(opzioni, variable=self.rispecchia, command=self._on_rispecchia)
        self.check_rispecchia.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.etichetta_esclusioni = ttk.Label(opzioni)
        self.etichetta_esclusioni.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.campo_esclusioni = ttk.Entry(opzioni, textvariable=self.esclusioni)
        self.campo_esclusioni.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        self.campo_esclusioni.bind("<FocusOut>", lambda _evento: self._on_esclusioni())
        self.etichetta_esclusioni_aiuto = ttk.Label(opzioni, wraplength=700)
        self.etichetta_esclusioni_aiuto.grid(row=3, column=1, sticky="w")

        comandi = ttk.Frame(contenitore)
        comandi.grid(row=6, column=0, sticky="w", pady=(14, 8))
        self.bottone_avvia = ttk.Button(comandi, command=lambda: self._avvia(False))
        self.bottone_avvia.grid(row=0, column=0, padx=(0, 8), pady=(0, 8))
        self.bottone_copia = ttk.Button(comandi, command=lambda: self._avvia(True))
        self.bottone_copia.grid(row=0, column=1, padx=(0, 8), pady=(0, 8))
        self.bottone_ferma = ttk.Button(comandi, command=self._ferma_monitoraggio, state="disabled")
        self.bottone_ferma.grid(row=0, column=2, padx=(0, 8), pady=(0, 8))
        self.bottone_apri = ttk.Button(comandi, command=self._apri_destinazione)
        self.bottone_apri.grid(row=0, column=3, padx=(0, 8), pady=(0, 8))
        self.bottone_nascondi = ttk.Button(comandi, command=self._nascondi)
        self.bottone_nascondi.grid(row=0, column=4, pady=(0, 8))

        self.etichetta_stato = ttk.Label(contenitore, textvariable=self.stato, wraplength=860)
        self.etichetta_stato.grid(row=7, column=0, sticky="w", pady=(4, 8))

        self.riquadro_registro = ttk.LabelFrame(contenitore, padding=8)
        self.riquadro_registro.grid(row=8, column=0, sticky="nsew")
        self.riquadro_registro.columnconfigure(0, weight=1)
        self.riquadro_registro.rowconfigure(0, weight=1)
        self.testo = tk.Text(self.riquadro_registro, height=10, wrap="word", state="disabled", font=("Segoe UI", 9))
        barra = ttk.Scrollbar(self.riquadro_registro, command=self.testo.yview)
        self.testo.configure(yscrollcommand=barra.set)
        self.testo.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")

        self._blocca = [
            self.campo_cartella,
            self.bottone_sfoglia,
            self.bottone_aggiungi,
            self.bottone_rimuovi,
            self.lista,
            self.check_rispecchia,
            self.campo_esclusioni,
            self.bottone_avvia,
            self.bottone_copia,
        ]

    def _adatta_testo(self, _evento=None):
        larghezza = max(320, self.winfo_width() - 52)
        for etichetta in (
            self.etichetta_descrizione,
            self.etichetta_percorso,
            self.etichetta_stato,
            self.etichetta_esclusioni_aiuto,
        ):
            etichetta.configure(wraplength=larghezza)

    def _leggi_cartelle(self):
        return list(self.lista.get(0, "end"))

    def _cartelle_selezionate(self):
        return [self.lista.get(indice) for indice in self.lista.curselection()]

    def _aggiorna_destinazione(self, _evento=None):
        selezionate = self._cartelle_selezionate()
        if len(selezionate) == 1:
            self.destinazione.set(destinazione_per(selezionate[0]))
            return
        cartelle = self._leggi_cartelle()
        if len(cartelle) == 1:
            self.destinazione.set(destinazione_per(cartelle[0]))
            return
        self.destinazione.set(CARTELLA_BACKUP)

    def _aggiorna_combo(self):
        self._blocco_eventi = True
        try:
            self._codici_lingua = sorted(self.lingue, key=lambda codice: self.lingue[codice]["nome"].lower())
            self.combo_lingua["values"] = [self.lingue[codice]["nome"] for codice in self._codici_lingua]
            self.combo_lingua.current(self._codici_lingua.index(self.codice_lingua))
            self.combo_intervallo["values"] = [self.t(f"intervallo_{secondi}") for secondi in INTERVALLI]
            if self._secondi not in INTERVALLI:
                self._secondi = INTERVALLO_PREDEFINITO
            self.combo_intervallo.current(INTERVALLI.index(self._secondi))
        finally:
            self._blocco_eventi = False

    def applica_lingua(self, codice, salva):
        if codice not in self.lingue:
            return
        self.codice_lingua = codice
        self.title(self.t("titolo_finestra"))
        self.etichetta_titolo.configure(text=self.t("titolo"))
        self.etichetta_descrizione.configure(text=self.t("descrizione"))
        self.etichetta_lingua.configure(text=self.t("lingua"))
        self.bottone_about.configure(text=self.t("about"))
        self.riquadro_scelta.configure(text=self.t("cartelle_da_monitorare"))
        self.bottone_sfoglia.configure(text=self.t("sfoglia"))
        self.bottone_aggiungi.configure(text=self.t("aggiungi"))
        self.bottone_rimuovi.configure(text=self.t("rimuovi"))
        self.etichetta_destinazione.configure(text=self.t("destinazione"))
        self.etichetta_intervallo.configure(text=self.t("intervallo"))
        self.check_rispecchia.configure(text=self.t("rispecchia"))
        self.etichetta_esclusioni.configure(text=self.t("esclusioni"))
        self.etichetta_esclusioni_aiuto.configure(text=self.t("esclusioni_aiuto"))
        self.bottone_avvia.configure(text=self.t("avvia"))
        self.bottone_copia.configure(text=self.t("copia_ora"))
        self.bottone_ferma.configure(text=self.t("ferma"))
        self.bottone_apri.configure(text=self.t("apri_destinazione"))
        self.bottone_nascondi.configure(text=self.t("nascondi"))
        self.riquadro_registro.configure(text=self.t("registro"))
        self.imposta_stato(self._stato_chiave, **self._stato_args)
        self._aggiorna_combo()
        if salva:
            self._salva_preferenze()

    def _salva_preferenze(self, avvisa=True):
        cartelle = self._leggi_cartelle()
        try:
            aggiorna_config(
                lingua=self.codice_lingua,
                cartelle=cartelle,
                cartella=cartelle[0] if cartelle else "",
                intervallo=self._secondi,
                rispecchia=bool(self.rispecchia.get()),
                esclusioni=analizza_esclusioni(self.esclusioni.get()),
            )
        except OSError as errore:
            if avvisa and self.winfo_exists():
                messagebox.showerror(self.t("titolo_finestra"), self.t("errore_salva_preferenze", errore=errore))
            return False
        return True

    def _on_lingua(self, _evento=None):
        if self._blocco_eventi or not self._pronto:
            return
        selezione = self.combo_lingua.current()
        if selezione < 0 or selezione >= len(self._codici_lingua):
            return
        codice = self._codici_lingua[selezione]
        if codice != self.codice_lingua:
            self.applica_lingua(codice, salva=True)

    def _on_intervallo(self, _evento=None):
        if self._blocco_eventi or not self._pronto:
            return
        indice = self.combo_intervallo.current()
        if indice < 0 or indice >= len(INTERVALLI):
            return
        self._secondi = INTERVALLI[indice]
        self._salva_preferenze()

    def _on_rispecchia(self):
        if self._blocco_eventi or not self._pronto:
            return
        self._salva_preferenze()

    def _on_esclusioni(self):
        if self._blocco_eventi or not self._pronto:
            return
        self._salva_preferenze()

    def _apri_kofi(self):
        webbrowser.open(LINK_KOFI)

    def _mostra_about(self):
        finestra = tk.Toplevel(self)
        finestra.title(self.t("about_titolo"))
        finestra.transient(self)
        finestra.resizable(False, False)
        cornice = ttk.Frame(finestra, padding=18)
        cornice.grid(row=0, column=0, sticky="nsew")

        ttk.Label(cornice, text=self.t("titolo"), font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(cornice, text=self.t("about_proprieta"), wraplength=420).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(cornice, text=self.t("about_donazione"), wraplength=420).grid(row=2, column=0, sticky="w", pady=(8, 0))

        link = tk.Label(cornice, text=LINK_KOFI, fg="#1a5fb4", cursor="hand2")
        link.grid(row=3, column=0, sticky="w", pady=(8, 0))
        link.bind("<Button-1>", lambda _evento: self._apri_kofi())

        comandi = ttk.Frame(cornice)
        comandi.grid(row=4, column=0, sticky="e", pady=(16, 0))
        ttk.Button(comandi, text=self.t("about_apri_kofi"), command=self._apri_kofi).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(comandi, text=self.t("chiudi"), command=finestra.destroy).grid(row=0, column=1)

        finestra.update_idletasks()
        larghezza = finestra.winfo_reqwidth()
        altezza = finestra.winfo_reqheight()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - larghezza) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - altezza) // 2)
        finestra.geometry(f"+{x}+{y}")
        finestra.grab_set()
        finestra.focus_set()

    def _inserisci_cartella(self, cartella):
        cartella = cartella.strip()
        if not cartella or not esiste_dir(cartella):
            messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_cartella_mancante"))
            return False
        if not cartella_consentita(cartella, CARTELLA_BACKUP):
            messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_cartella_backup", cartella=cartella))
            return False
        chiave = normalizza(cartella)
        for indice, voce in enumerate(self._leggi_cartelle()):
            if normalizza(voce) == chiave:
                self.lista.selection_clear(0, "end")
                self.lista.selection_set(indice)
                self.lista.see(indice)
                self._aggiorna_destinazione()
                return True
        self.lista.insert("end", os.path.abspath(cartella))
        indice = self.lista.size() - 1
        self.lista.selection_clear(0, "end")
        self.lista.selection_set(indice)
        self.lista.see(indice)
        self._aggiorna_destinazione()
        self._salva_preferenze()
        return True

    def _scegli_cartella(self):
        iniziale = self.campo_nuovo.get().strip()
        if not esiste_dir(iniziale):
            selezionate = self._cartelle_selezionate()
            iniziale = selezionate[0] if selezionate and esiste_dir(selezionate[0]) else os.path.expanduser("~")
        scelta = filedialog.askdirectory(title=self.t("titolo_dialogo_cartella"), initialdir=iniziale)
        if not scelta:
            return
        self.campo_nuovo.set(scelta)
        if self._inserisci_cartella(scelta):
            self.campo_nuovo.set("")

    def _aggiungi_cartella(self):
        testo = self.campo_nuovo.get().strip()
        if testo:
            if self._inserisci_cartella(testo):
                self.campo_nuovo.set("")
            return
        self._scegli_cartella()

    def _rimuovi_cartella(self):
        selezionati = list(self.lista.curselection())
        if not selezionati:
            return
        for indice in reversed(selezionati):
            self.lista.delete(indice)
        self._aggiorna_destinazione()
        self._salva_preferenze()

    def _apri_destinazione(self):
        percorso = CARTELLA_BACKUP
        selezionate = self._cartelle_selezionate()
        if len(selezionate) == 1:
            candidato = destinazione_per(selezionate[0])
            if esiste_dir(candidato):
                percorso = candidato
        try:
            if not esiste_dir(percorso):
                os.makedirs(percorso_esteso(percorso), exist_ok=True)
            os.startfile(percorso)
        except OSError as errore:
            messagebox.showerror(self.t("titolo_finestra"), self.t("errore_apri_destinazione", errore=errore))

    def _registra(self, messaggio):
        ora = datetime.now().strftime("%H:%M:%S")
        self._coda.put(f"[{ora}] {messaggio}")

    def _svuota_log(self):
        self._dopo_log = None
        if self._in_chiusura or not self.winfo_exists():
            return
        nuove = []
        while True:
            try:
                nuove.append(self._coda.get_nowait())
            except queue.Empty:
                break
        if nuove:
            accoda_righe(self._righe_log, nuove, MAX_RIGHE_REGISTRO)
            self.testo.configure(state="normal")
            self.testo.delete("1.0", "end")
            self.testo.insert("1.0", "\n".join(self._righe_log) + "\n")
            self.testo.see("end")
            self.testo.configure(state="disabled")
        self._dopo_log = self.after(200, self._svuota_log)

    def _blocca_comandi(self, attivo):
        stato = "disabled" if attivo else "normal"
        for widget in self._blocca:
            widget.configure(state=stato)
        self.combo_lingua.configure(state="disabled" if attivo else "readonly")
        self.combo_intervallo.configure(state="disabled" if attivo else "readonly")
        self.bottone_ferma.configure(state="normal" if attivo else "disabled")

    def _avvia(self, una_volta):
        testo = self.campo_nuovo.get().strip()
        if testo and not self._inserisci_cartella(testo):
            return
        if testo:
            self.campo_nuovo.set("")
        cartelle = self._leggi_cartelle()
        if not cartelle:
            messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_nessuna_cartella"))
            return
        valide = []
        mancanti = []
        for cartella in cartelle:
            if not esiste_dir(cartella):
                mancanti.append(cartella)
                continue
            if not cartella_consentita(cartella, CARTELLA_BACKUP):
                messagebox.showwarning(self.t("titolo_finestra"), self.t("avviso_cartella_backup", cartella=cartella))
                return
            valide.append(cartella)
        if not valide:
            messagebox.showwarning(
                self.t("titolo_finestra"),
                self.t("avviso_cartelle_mancanti", cartelle="\n".join(mancanti)),
            )
            return
        if mancanti:
            messagebox.showwarning(
                self.t("titolo_finestra"),
                self.t("avviso_cartelle_mancanti", cartelle="\n".join(mancanti)),
            )
        try:
            os.makedirs(percorso_esteso(CARTELLA_BACKUP), exist_ok=True)
        except OSError as errore:
            messagebox.showerror(self.t("titolo_finestra"), self.t("errore_prepara", errore=errore))
            return
        if not self._salva_preferenze():
            return

        self._ferma.clear()
        self._motivo = ""
        self._dettagli = {}
        self._una_volta = una_volta
        self._blocca_comandi(True)
        self.imposta_stato("copia_avviata" if una_volta else "monitoraggio_avviato")
        esclusioni = tuple(analizza_esclusioni(self.esclusioni.get()))
        self._thread = threading.Thread(
            target=self._ciclo,
            args=(list(valide), una_volta, self._secondi, esclusioni, bool(self.rispecchia.get())),
            daemon=True,
        )
        self._thread.start()

    def _ferma_monitoraggio(self):
        self._ferma.set()
        self.imposta_stato("arresto")
        self.bottone_ferma.configure(state="disabled")

    def _ciclo(self, cartelle, una_volta, secondi, esclusioni, rispecchia):
        try:
            self._esegui_cicli(cartelle, una_volta, secondi, esclusioni, rispecchia)
        except CopiaInterrotta as interruzione:
            self._motivo = interruzione.motivo
            esito = interruzione.esito
            self._dettagli = {
                "file": str(interruzione.dettagli.get("file", "")),
                "richiesti": str(interruzione.dettagli.get("richiesti", "")),
                "liberi": str(interruzione.dettagli.get("liberi", "")),
                "ora": datetime.now().strftime("%H:%M:%S"),
                "copiati": esito.copiati,
                "invariati": esito.invariati,
                "spostati": esito.spostati,
                "errori": esito.errori,
                "errore": "",
            }
        except Exception as errore:
            self._motivo = "errore"
            self._dettagli = {"errore": errore}
        self.after(0, self._monitoraggio_fermato)

    def _esegui_cicli(self, cartelle, una_volta, secondi, esclusioni, rispecchia):
        azzera_cache_filesystem()
        for cartella in cartelle:
            self._registra(self.t("log_monitoraggio", cartella=cartella))
            self._registra(self.t("log_destinazione", destinazione=destinazione_per(cartella)))
        while not self._ferma.is_set():
            if not supporto_disponibile():
                raise CopiaInterrotta("supporto", Esito())
            azzera_cache_filesystem()
            self.after(0, lambda: self.imposta_stato("stato_controllo"))
            totale = Esito()
            presenti = 0
            cestino = os.path.join(CARTELLA_BACKUP, NOME_CESTINO, datetime.now().strftime("%Y%m%d-%H%M%S"))
            for cartella in cartelle:
                if self._ferma.is_set():
                    break
                if not esiste_dir(cartella):
                    self._registra(self.t("log_cartella_assente", cartella=cartella))
                    continue
                presenti += 1
                try:
                    esito = copia_albero(
                        cartella,
                        destinazione_per(cartella),
                        self._ferma,
                        self._registra,
                        self.t,
                        esclusioni,
                        CARTELLA_BACKUP,
                    )
                    totale.somma(esito)
                    if rispecchia and not self._ferma.is_set():
                        spostati, errori_spostamento = sposta_extra(
                            cartella,
                            destinazione_per(cartella),
                            cestino,
                            self._ferma,
                            self._registra,
                            self.t,
                            esclusioni,
                            CARTELLA_BACKUP,
                        )
                        totale.spostati += spostati
                        totale.errori += errori_spostamento
                except CopiaInterrotta as interruzione:
                    totale.somma(interruzione.esito)
                    interruzione.esito = totale
                    raise
            if self._ferma.is_set():
                self._registra_riepilogo(totale)
                return
            if presenti == 0:
                raise CopiaInterrotta("cartelle", totale)
            self._registra_riepilogo(totale)
            if una_volta:
                return
            if attendi(secondi, self._ferma):
                return

    def _registra_riepilogo(self, esito):
        valori = {
            "ora": datetime.now().strftime("%H:%M:%S"),
            "copiati": esito.copiati,
            "invariati": esito.invariati,
            "spostati": esito.spostati,
            "errori": esito.errori,
        }
        self._ultimo_riepilogo = valori
        self._registra(self.t("riepilogo", **valori))
        self.after(0, lambda dati=valori: self.imposta_stato("riepilogo", **dati))

    def _monitoraggio_fermato(self):
        if self._in_chiusura or not self.winfo_exists():
            return
        self._blocca_comandi(False)
        self._thread = None
        motivo = self._motivo
        self._motivo = ""
        dettagli = dict(self._dettagli)
        if motivo == "spazio":
            if dettagli.get("richiesti"):
                self.imposta_stato("stato_spazio", **dettagli)
                self._registra(self.t("log_spazio", **dettagli))
            else:
                self.imposta_stato("stato_spazio_generico")
                self._registra(self.t("log_spazio_generico"))
        elif motivo == "supporto":
            self.imposta_stato("stato_chiavetta")
            self._registra(self.t("log_chiavetta"))
        elif motivo == "cartelle":
            self.imposta_stato("stato_cartella_persa")
            self._registra(self.t("log_cartella_persa"))
        elif motivo == "errore":
            self.imposta_stato("stato_errore")
            self._registra(self.t("errore_imprevisto", errore=dettagli.get("errore", "")))
        elif self._stato_chiave == "arresto":
            self.imposta_stato("monitoraggio_fermato")
            self._registra(self.t("log_fermato"))
        elif self._una_volta:
            self.imposta_stato("copia_completata", **self._ultimo_riepilogo)
            self._registra(self.t("log_copia_completata"))
        else:
            self.imposta_stato("monitoraggio_fermato")
            self._registra(self.t("log_fermato"))

    def _nascondi(self):
        if self.state() == "withdrawn":
            return
        if self._tray is None:
            try:
                self._tray = IconaTray(self.t("titolo"))
            except OSError as errore:
                messagebox.showerror(self.t("titolo_finestra"), self.t("errore_tray", errore=errore))
                return
            self.after(150, self._poll_tray)
        self.withdraw()
        self._registra(self.t("log_nascosto"))

    def _mostra_finestra(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        tray = self._tray
        self._tray = None
        if tray is not None:
            tray.chiudi()

    def _poll_tray(self):
        if self._in_chiusura or self._tray is None or not self.winfo_exists():
            return
        try:
            eventi = self._tray.preleva()
        except OSError:
            eventi = []
        for evento in eventi:
            if self._tray is None:
                return
            if evento == "apri":
                self._mostra_finestra()
            elif evento == "menu":
                try:
                    scelta = self._tray.menu(((1, self.t("tray_apri")), (2, self.t("tray_esci"))))
                except OSError:
                    scelta = 0
                if scelta == 1:
                    self._mostra_finestra()
                elif scelta == 2:
                    self._chiudi()
                    return
        if self._tray is not None and self.winfo_exists() and not self._in_chiusura:
            self.after(150, self._poll_tray)

    def _chiudi(self):
        if self._in_chiusura:
            return
        self._in_chiusura = True
        self._ferma.set()
        if self._dopo_log is not None:
            try:
                self.after_cancel(self._dopo_log)
            except tk.TclError:
                pass
            self._dopo_log = None
        try:
            if self.winfo_exists() and getattr(self, "lista", None) is not None:
                self._salva_preferenze(avvisa=False)
        except (OSError, tk.TclError):
            pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        tray = self._tray
        self._tray = None
        if tray is not None:
            tray.chiudi()
        self.destroy()


if __name__ == "__main__":
    BackupApp().mainloop()
