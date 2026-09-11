"""
Der zweite Faktor, gegen die Testvektoren aus dem Standard.

Der Grund, warum der Algorithmus in diesem Projekt steht und nicht aus einer
Bibliothek kommt: RFC 4226 und RFC 6238 liefern Vektoren, die ihn
vollstaendig festnageln. Stimmen die, stimmt die Rechnung - und zwar
gegenueber jeder Authenticator-App auf der Welt, nicht nur gegenueber
unserer eigenen.
"""

import base64

from django.test import SimpleTestCase

from django_grp_backend import zweitfaktor


def _base32(ascii_geheimnis: bytes) -> str:
    return base64.b32encode(ascii_geheimnis).decode().rstrip("=")


class RfcVektorenTestCase(SimpleTestCase):
    """
    RFC 6238, Anhang B, und RFC 4226, Anhang D.

    Die Vektoren aus 6238 stehen dort mit acht Stellen; diese Anwendung
    rechnet mit sechs, also die letzten sechs.
    """

    # "12345678901234567890" - das Geheimnis aus beiden Anhaengen.
    GEHEIMNIS = _base32(b"12345678901234567890")

    def test_rfc6238_sha1(self):
        # (Unixzeit, achtstelliger Code aus dem Anhang)
        vektoren = [
            (59, "94287082"),
            (1111111109, "07081804"),
            (1111111111, "14050471"),
            (1234567890, "89005924"),
            (2000000000, "69279037"),
            (20000000000, "65353130"),
        ]
        for zeit, erwartet in vektoren:
            with self.subTest(zeit=zeit):
                schritt = zweitfaktor.schritt_jetzt(zeit)
                self.assertEqual(
                    zweitfaktor.code(self.GEHEIMNIS, schritt),
                    erwartet[-6:],
                )

    def test_rfc4226_zaehler(self):
        """
        Anhang D: dieselbe Kuerzung, nur mit dem Zaehler statt der Zeit.
        Schlaegt das hier fehl und 6238 nicht, sitzt der Fehler in der
        Zeitscheibe und nicht in der Rechnung.
        """
        erwartet = [
            "755224",
            "287082",
            "359152",
            "969429",
            "338314",
            "254676",
            "287922",
            "162583",
            "399871",
            "520489",
        ]
        for zaehler, wert in enumerate(erwartet):
            with self.subTest(zaehler=zaehler):
                self.assertEqual(zweitfaktor.code(self.GEHEIMNIS, zaehler), wert)


class PruefungTestCase(SimpleTestCase):
    GEHEIMNIS = _base32(b"12345678901234567890")

    def test_code_der_laufenden_scheibe_gilt(self):
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)
        richtig = zweitfaktor.code(self.GEHEIMNIS, schritt)

        self.assertEqual(
            zweitfaktor.pruefen(self.GEHEIMNIS, richtig, zeitpunkt=jetzt),
            schritt,
        )

    def test_eine_scheibe_nachsicht_in_beide_richtungen(self):
        """
        Die Uhr eines Telefons weicht ab, und zwischen Ablesen und Tippen
        vergehen Sekunden.
        """
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)

        for versatz in (-1, 0, 1):
            with self.subTest(versatz=versatz):
                self.assertIsNotNone(
                    zweitfaktor.pruefen(
                        self.GEHEIMNIS,
                        zweitfaktor.code(self.GEHEIMNIS, schritt + versatz),
                        zeitpunkt=jetzt,
                    )
                )

    def test_zwei_scheiben_daneben_gelten_nicht(self):
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)

        for versatz in (-2, 2):
            with self.subTest(versatz=versatz):
                self.assertIsNone(
                    zweitfaktor.pruefen(
                        self.GEHEIMNIS,
                        zweitfaktor.code(self.GEHEIMNIS, schritt + versatz),
                        zeitpunkt=jetzt,
                    )
                )

    def test_ein_verbrauchter_code_gilt_kein_zweites_mal(self):
        """
        Wer einer Fachkraft ueber die Schulter sieht, koennte sich sonst in
        denselben dreissig Sekunden mit demselben Code anmelden.
        """
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)
        code = zweitfaktor.code(self.GEHEIMNIS, schritt)

        self.assertEqual(
            zweitfaktor.pruefen(self.GEHEIMNIS, code, zeitpunkt=jetzt), schritt
        )
        self.assertIsNone(
            zweitfaktor.pruefen(
                self.GEHEIMNIS, code, zeitpunkt=jetzt, zuletzt=schritt
            )
        )

    def test_nach_dem_verbrauchen_geht_die_naechste_scheibe(self):
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)
        naechster = zweitfaktor.code(self.GEHEIMNIS, schritt + 1)

        self.assertEqual(
            zweitfaktor.pruefen(
                self.GEHEIMNIS, naechster, zeitpunkt=jetzt, zuletzt=schritt
            ),
            schritt + 1,
        )

    def test_unsinn_wird_abgewiesen(self):
        jetzt = 1_700_000_000
        for eingabe in ("", None, "12345", "1234567", "abcdef", "   "):
            with self.subTest(eingabe=eingabe):
                self.assertIsNone(
                    zweitfaktor.pruefen(self.GEHEIMNIS, eingabe, zeitpunkt=jetzt)
                )

    def test_leerzeichen_im_code_stoeren_nicht(self):
        """
        Manche Apps zeigen "123 456". Wer das so abtippt, meint denselben
        Code, und eine Fehlermeldung dafuer waere Schikane.
        """
        jetzt = 1_700_000_000
        schritt = zweitfaktor.schritt_jetzt(jetzt)
        code = zweitfaktor.code(self.GEHEIMNIS, schritt)
        mit_luecke = f"{code[:3]} {code[3:]}"

        self.assertEqual(
            zweitfaktor.pruefen(self.GEHEIMNIS, mit_luecke, zeitpunkt=jetzt),
            schritt,
        )


class GeheimnisTestCase(SimpleTestCase):
    def test_erzeugt_160_bit_in_base32(self):
        geheimnis = zweitfaktor.geheimnis_erzeugen()
        self.assertEqual(len(geheimnis), 32)
        self.assertNotIn("=", geheimnis)
        self.assertEqual(len(zweitfaktor._entschluesseln_base32(geheimnis)), 20)

    def test_zwei_geheimnisse_sind_verschieden(self):
        self.assertNotEqual(
            zweitfaktor.geheimnis_erzeugen(), zweitfaktor.geheimnis_erzeugen()
        )

    def test_klein_getippt_und_ohne_fuellzeichen_geht_auch(self):
        geheimnis = zweitfaktor.geheimnis_erzeugen()
        schritt = zweitfaktor.schritt_jetzt(1_700_000_000)

        self.assertEqual(
            zweitfaktor.code(geheimnis.lower(), schritt),
            zweitfaktor.code(geheimnis, schritt),
        )


class OtpauthTestCase(SimpleTestCase):
    def test_adresse_traegt_alles_was_eine_app_braucht(self):
        adresse = zweitfaktor.otpauth("ABC234", "m.kaltenbach", "Gruppenprotokoll")

        self.assertTrue(adresse.startswith("otpauth://totp/"))
        self.assertIn("secret=ABC234", adresse)
        self.assertIn("issuer=Gruppenprotokoll", adresse)
        self.assertIn("digits=6", adresse)
        self.assertIn("period=30", adresse)

    def test_sonderzeichen_im_namen_brechen_die_adresse_nicht(self):
        adresse = zweitfaktor.otpauth("ABC234", "a b/c?d", "Träger & Co")

        self.assertNotIn(" ", adresse)
        self.assertNotIn("otpauth://totp/Träger", adresse)
