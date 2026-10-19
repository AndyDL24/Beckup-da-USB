import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import BeckupFileUSB as app


def traduci(chiave, **valori):
    if not valori:
        return chiave
    dettaglio = ",".join(f"{nome}={valore}" for nome, valore in sorted(valori.items()))
    return f"{chiave}:{dettaglio}"


class FunzioniPure(unittest.TestCase):
    def test_destinazione_ricostruisce_unita_e_cartelle(self):
        ottenuto = app.destinazione_per(r"E:\COOP\documenti", r"D:\chiavetta\backup")
        self.assertEqual(ottenuto, os.path.join(r"D:\chiavetta\backup", "E", "COOP", "documenti"))

    def test_percorso_dentro_ignora_maiuscole(self):
        self.assertTrue(app.percorso_dentro(r"D:\Backup\E\file.txt", r"d:\backup"))
        self.assertTrue(app.percorso_dentro(r"D:\backup", r"D:\backup"))
        self.assertFalse(app.percorso_dentro(r"D:\backup2\file.txt", r"D:\backup"))

    def test_cartella_che_contiene_il_backup_non_e_consentita(self):
        self.assertFalse(app.cartella_consentita("E:\\", os.path.join("E:\\", "backup")))
        self.assertFalse(app.cartella_consentita(os.path.join("E:\\", "backup", "foto"), os.path.join("E:\\", "backup")))
        self.assertTrue(app.cartella_consentita(r"C:\Utenti\foto", os.path.join("E:\\", "backup")))

    def test_percorso_esteso_e_reversibile(self):
        normale = os.path.abspath(r"C:\cartella\file.txt")
        esteso = app.percorso_esteso(normale)
        self.assertTrue(esteso.startswith("\\\\?\\"))
        self.assertEqual(app.percorso_normale(esteso), normale)
        self.assertEqual(app.percorso_esteso(esteso), esteso)

    def test_va_copiato(self):
        self.assertTrue(app.va_copiato(10, 8, 100, 200, False))
        self.assertFalse(app.va_copiato(10, 10, 100, 100, False))
        self.assertFalse(app.va_copiato(10, 10, 100, 150, False))
        self.assertTrue(app.va_copiato(10, 10, 101, 100, False))
        self.assertFalse(app.va_copiato(10, 10, 101, 100, True))
        self.assertTrue(app.va_copiato(10, 10, 103, 100, True))

    def test_esclusioni_e_config(self):
        self.assertTrue(app.nome_escluso("Thumbs.db", app.ESCLUSIONI_PREDEFINITE))
        self.assertTrue(app.nome_escluso("~$lettera.docx", app.ESCLUSIONI_PREDEFINITE))
        self.assertTrue(app.nome_escluso("node_modules", ["node_modules"]))
        self.assertFalse(app.nome_escluso("foto.txt", app.ESCLUSIONI_PREDEFINITE))
        self.assertEqual(app.analizza_esclusioni(" .git, Thumbs.db, .git "), [".git", "Thumbs.db"])
        self.assertEqual(app.cartelle_da_config({"cartella": r"C:\dati"}), [r"C:\dati"])
        self.assertEqual(app.cartelle_da_config({"cartelle": [], "cartella": r"C:\dati"}), [])
        self.assertEqual(app.cartelle_da_config({"cartelle": [r"C:\a", r"C:\a", "  "]}), [r"C:\a"])
        self.assertEqual(app.intervallo_da_config({"intervallo": 60}), 60)
        self.assertEqual(app.intervallo_da_config({"intervallo": 15}), app.INTERVALLO_PREDEFINITO)
        self.assertTrue(app.rispecchia_da_config({"rispecchia": True}))
        self.assertFalse(app.rispecchia_da_config({"rispecchia": "si"}))
        self.assertEqual(app.esclusioni_da_config({}), list(app.ESCLUSIONI_PREDEFINITE))
        self.assertEqual(app.esclusioni_da_config({"esclusioni": []}), [])

    def test_registro_mantiene_le_ultime_righe(self):
        righe = []
        app.accoda_righe(righe, [str(numero) for numero in range(10)], 4)
        self.assertEqual(righe, ["6", "7", "8", "9"])

    def test_formatta_byte(self):
        self.assertEqual(app.formatta_byte(512), "512 B")
        self.assertEqual(app.formatta_byte(2048), "2 KB")
        self.assertEqual(app.formatta_byte(1024 * 1024), "1.0 MB")


class ConfigAtomico(unittest.TestCase):
    def setUp(self):
        self.temporanea = tempfile.TemporaryDirectory()
        self.percorso = os.path.join(self.temporanea.name, "config.json")
        self.config_originale = app.FILE_CONFIG
        app.FILE_CONFIG = self.percorso

    def tearDown(self):
        app.FILE_CONFIG = self.config_originale
        self.temporanea.cleanup()

    def test_aggiorna_senza_perdere_le_chiavi_e_senza_temporanei(self):
        app.scrivi_config({"lingua": "it", "extra": 1}, self.percorso)
        app.aggiorna_config(cartelle=[r"C:\dati"])
        with open(self.percorso, encoding="utf-8") as file:
            dati = json.load(file)
        self.assertEqual(dati["lingua"], "it")
        self.assertEqual(dati["extra"], 1)
        self.assertEqual(dati["cartelle"], [r"C:\dati"])
        self.assertFalse(any(nome.startswith(".config_") for nome in os.listdir(self.temporanea.name)))

    def test_se_la_sostituzione_fallisce_il_file_precedente_resta(self):
        app.scrivi_config({"lingua": "it"}, self.percorso)
        with open(self.percorso, encoding="utf-8") as file:
            originale = file.read()
        with mock.patch.object(app.os, "replace", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                app.scrivi_config({"lingua": "en"}, self.percorso)
        with open(self.percorso, encoding="utf-8") as file:
            self.assertEqual(file.read(), originale)
        self.assertFalse(any(nome.startswith(".config_") for nome in os.listdir(self.temporanea.name)))


class Copia(unittest.TestCase):
    def setUp(self):
        self.temporanea = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.origine = os.path.join(self.temporanea.name, "origine")
        self.backup = os.path.join(self.temporanea.name, "backup")
        self.destinazione = os.path.join(self.backup, "origine")
        os.makedirs(self.origine)
        self.ferma = threading.Event()
        self.messaggi = []

    def tearDown(self):
        try:
            shutil.rmtree(app.percorso_esteso(self.temporanea.name))
        except OSError:
            pass
        self.temporanea.cleanup()

    def registra(self, messaggio):
        self.messaggi.append(messaggio)

    def copia(self, esclusioni=()):
        return app.copia_albero(
            self.origine,
            self.destinazione,
            self.ferma,
            self.registra,
            traduci,
            esclusioni,
            self.backup,
        )

    def scrivi(self, relativo, contenuto):
        percorso = os.path.join(self.origine, relativo)
        os.makedirs(os.path.dirname(percorso), exist_ok=True)
        with open(percorso, "w", encoding="utf-8") as file:
            file.write(contenuto)
        return percorso

    def leggi_dest(self, relativo):
        with open(os.path.join(self.destinazione, relativo), encoding="utf-8") as file:
            return file.read()

    def test_copia_e_secondo_passaggio_invariato(self):
        self.scrivi("nota.txt", "ciao")
        self.scrivi(os.path.join("foto", "a.txt"), "a")
        primo = self.copia()
        self.assertEqual(primo.copiati, 2)
        self.assertEqual(self.leggi_dest("nota.txt"), "ciao")
        secondo = self.copia()
        self.assertEqual(secondo.copiati, 0)
        self.assertEqual(secondo.invariati, 2)
        self.assertFalse(any(app.e_temporaneo(nome) for _, _, nomi in os.walk(self.backup) for nome in nomi))

    def test_dimensione_diversa_viene_copiata_anche_se_la_destinazione_e_piu_recente(self):
        origine = self.scrivi("nota.txt", "ciao")
        self.copia()
        arrivo = os.path.join(self.destinazione, "nota.txt")
        with open(arrivo, "w", encoding="utf-8") as file:
            file.write("contenuto piu lungo")
        os.utime(arrivo, (1893456000, 1893456000))
        os.utime(origine, (1577836800, 1577836800))
        esito = self.copia()
        self.assertEqual(esito.copiati, 1)
        self.assertEqual(self.leggi_dest("nota.txt"), "ciao")

    def test_origine_piu_recente_viene_copiata(self):
        origine = self.scrivi("nota.txt", "vecchio")
        self.copia()
        with open(origine, "w", encoding="utf-8") as file:
            file.write("nuovo")
        os.utime(os.path.join(self.destinazione, "nota.txt"), (1577836800, 1577836800))
        os.utime(origine, (1893456000, 1893456000))
        esito = self.copia()
        self.assertEqual(esito.copiati, 1)
        self.assertEqual(self.leggi_dest("nota.txt"), "nuovo")

    def test_sostituzione_fallita_non_corrompe_il_file_precedente(self):
        self.scrivi("nota.txt", "nuovo")
        os.makedirs(self.destinazione)
        arrivo = os.path.join(self.destinazione, "nota.txt")
        with open(arrivo, "w", encoding="utf-8") as file:
            file.write("vecchio")
        with mock.patch.object(app.os, "replace", side_effect=OSError("interrotto")):
            esito = self.copia()
        self.assertEqual(esito.errori, 1)
        self.assertEqual(esito.copiati, 0)
        with open(arrivo, encoding="utf-8") as file:
            self.assertEqual(file.read(), "vecchio")
        self.assertFalse(any(app.e_temporaneo(nome) for _, _, nomi in os.walk(self.backup) for nome in nomi))

    def test_esclusioni(self):
        self.scrivi("ok.txt", "ok")
        self.scrivi("Thumbs.db", "x")
        self.scrivi(os.path.join("node_modules", "lib.js"), "js")
        self.scrivi(os.path.join("lettere", "~$segreto.docx"), "lock")
        esito = self.copia(app.ESCLUSIONI_PREDEFINITE)
        self.assertEqual(esito.copiati, 1)
        self.assertTrue(os.path.isfile(os.path.join(self.destinazione, "ok.txt")))
        self.assertFalse(os.path.isfile(os.path.join(self.destinazione, "Thumbs.db")))
        self.assertFalse(os.path.isdir(os.path.join(self.destinazione, "node_modules")))
        self.assertFalse(os.path.isfile(os.path.join(self.destinazione, "lettere", "~$segreto.docx")))

    def test_non_rientra_nella_cartella_backup(self):
        self.scrivi("ok.txt", "ok")
        interno = os.path.join(self.origine, "backup")
        os.makedirs(interno)
        with open(os.path.join(interno, "segreto.txt"), "w", encoding="utf-8") as file:
            file.write("segreto")
        esito = app.copia_albero(
            self.origine,
            os.path.join(interno, "copia"),
            self.ferma,
            self.registra,
            traduci,
            (),
            interno,
        )
        self.assertEqual(esito.copiati, 1)
        self.assertTrue(os.path.isfile(os.path.join(interno, "copia", "ok.txt")))
        self.assertFalse(os.path.isfile(os.path.join(interno, "copia", "segreto.txt")))

    def test_spazio_insufficiente_non_crea_il_file(self):
        self.scrivi("grande.txt", "dati")
        with mock.patch.object(app, "spazio_libero", return_value=0):
            with self.assertRaises(app.CopiaInterrotta) as contesto:
                self.copia()
        self.assertEqual(contesto.exception.motivo, "spazio")
        self.assertFalse(os.path.isfile(os.path.join(self.destinazione, "grande.txt")))

    def test_chiavetta_assente(self):
        self.scrivi("nota.txt", "ciao")
        with mock.patch.object(app, "supporto_disponibile", return_value=False):
            with self.assertRaises(app.CopiaInterrotta) as contesto:
                self.copia()
        self.assertEqual(contesto.exception.motivo, "supporto")

    def test_rispecchia_sposta_gli_extra_nel_cestino(self):
        self.scrivi("tiene.txt", "si")
        self.copia()
        extra = os.path.join(self.destinazione, "vecchio.txt")
        with open(extra, "w", encoding="utf-8") as file:
            file.write("via")
        os.makedirs(os.path.join(self.destinazione, "vecchia"))
        with open(os.path.join(self.destinazione, "vecchia", "a.txt"), "w", encoding="utf-8") as file:
            file.write("a")
        cestino = os.path.join(self.backup, app.NOME_CESTINO, "20261019")
        spostati, errori = app.sposta_extra(
            self.origine,
            self.destinazione,
            cestino,
            self.ferma,
            self.registra,
            traduci,
            (),
            self.backup,
        )
        self.assertEqual(errori, 0)
        self.assertEqual(spostati, 2)
        self.assertTrue(os.path.isfile(os.path.join(self.destinazione, "tiene.txt")))
        self.assertFalse(os.path.exists(extra))
        self.assertFalse(os.path.exists(os.path.join(self.destinazione, "vecchia")))
        self.assertEqual(self.leggi_dest("tiene.txt"), "si")
        with open(os.path.join(self.origine, "tiene.txt"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "si")
        trovati = []
        for radice, _, nomi in os.walk(cestino):
            trovati.extend(nomi)
        self.assertIn("vecchio.txt", trovati)
        self.assertIn("a.txt", trovati)

    def test_percorso_lungo(self):
        pezzo = "cartella_" + ("n" * 30)
        profondo = os.path.join(self.origine, *([pezzo] * 8))
        try:
            os.makedirs(app.percorso_esteso(profondo))
            with open(app.percorso_esteso(os.path.join(profondo, "nota.txt")), "w", encoding="utf-8") as file:
                file.write("lungo")
        except OSError as errore:
            self.skipTest(f"percorso lungo non disponibile: {errore}")
        esito = self.copia()
        self.assertEqual(esito.copiati, 1)
        trovato = None
        for radice, _, nomi in os.walk(app.percorso_esteso(self.destinazione)):
            if "nota.txt" in nomi:
                trovato = os.path.join(radice, "nota.txt")
        self.assertIsNotNone(trovato)
        with open(trovato, encoding="utf-8") as file:
            self.assertEqual(file.read(), "lungo")


if __name__ == "__main__":
    unittest.main()
