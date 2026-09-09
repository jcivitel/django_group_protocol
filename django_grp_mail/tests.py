"""
Tests fuer die Mail- und Push-Einstellungen.

Der Schwerpunkt liegt auf dem Schluesselpaar: es entsteht von selbst, es
entsteht genau einmal, und es zu wechseln bleibt eine ausdrueckliche
Handlung mit Folgen.
"""

from django.test import TestCase

from django_grp_mail.models import MailSettings


class VapidSchluesselTest(TestCase):
    def test_laden_erzeugt_das_schluesselpaar(self):
        """Ohne Zutun der Verwaltung: der erste Zugriff legt es an."""
        einstellungen = MailSettings.laden()

        self.assertTrue(einstellungen.has_vapid_keys)
        self.assertTrue(einstellungen.vapid_public_key)
        # Der private Schluessel liegt verschluesselt und laesst sich lesen.
        self.assertTrue(einstellungen.vapid_private_key)
        self.assertNotEqual(
            einstellungen.vapid_private_key,
            einstellungen.vapid_private_key_encrypted,
        )

    def test_laden_wechselt_das_schluesselpaar_nicht(self):
        """
        Sonst waere jede Anmeldung nach einem Seitenaufruf wertlos — und
        `laden()` wird auf jedem Lesepfad aufgerufen.
        """
        erst = MailSettings.laden().vapid_public_key
        zweit = MailSettings.laden().vapid_public_key

        self.assertEqual(erst, zweit)

    def test_leeres_schluesselpaar_wird_ersetzt(self):
        """Der Fall aus dem Bestand: Datensatz da, Schluessel noch nicht."""
        einstellungen = MailSettings.laden()
        alt = einstellungen.vapid_public_key
        einstellungen.vapid_public_key = ""
        einstellungen.vapid_private_key_encrypted = ""
        einstellungen.save(
            update_fields=["vapid_public_key", "vapid_private_key_encrypted"]
        )

        neu = MailSettings.laden()

        self.assertTrue(neu.has_vapid_keys)
        self.assertNotEqual(neu.vapid_public_key, alt)

    def test_push_ready_haengt_am_schalter(self):
        """
        Schluessel allein reichen nicht. `push_enabled` bleibt der eine
        Schalter, den die Verwaltung umlegt — er ist die Entscheidung,
        das Schluesselpaar war nur die Voraussetzung.
        """
        einstellungen = MailSettings.laden()

        self.assertTrue(einstellungen.has_vapid_keys)
        self.assertFalse(einstellungen.push_enabled)
        self.assertFalse(einstellungen.push_ready)

        einstellungen.push_enabled = True
        self.assertTrue(einstellungen.push_ready)
