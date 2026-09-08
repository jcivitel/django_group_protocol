"""
Erzeugt Schluessel fuer die .env.

Die Anwendung startet mit DEBUG=False nicht mehr, solange SECRET_KEY die
eingebaute Vorgabe traegt - aus gutem Grund, denn aus diesem Wert leitet sich
auch die Verschluesselung der SMTP-Zugangsdaten ab. Damit niemand dafuer erst
nach einem Einzeiler suchen muss, steht er hier.
"""

from django.core.management.base import BaseCommand
from django.utils.crypto import get_random_string

ZEICHEN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&()*+,-./:;<=>?@[]^_{|}~"


class Command(BaseCommand):
    help = "Erzeugt SECRET_KEY und FIELD_ENCRYPTION_KEY fuer die .env."

    def add_arguments(self, parser):
        parser.add_argument(
            "--nur-wert",
            action="store_true",
            help="Nur den SECRET_KEY ausgeben, ohne Erklaerung - zum Weiterleiten.",
        )

    def handle(self, *args, **options):
        secret = get_random_string(64, ZEICHEN)

        if options["nur_wert"]:
            self.stdout.write(secret)
            return

        feld = get_random_string(64, ZEICHEN)

        self.stdout.write("Diese beiden Zeilen gehoeren in die .env:")
        self.stdout.write("")
        self.stdout.write(f"SECRET_KEY={secret}")
        self.stdout.write(f"FIELD_ENCRYPTION_KEY={feld}")
        self.stdout.write("")
        self.stdout.write(
            "Loest ein bestehender Aufbau ab: den bisherigen SECRET_KEY in "
            "SECRET_KEY_FALLBACKS eintragen, sonst laesst sich das "
            "gespeicherte Mailserver-Passwort nicht mehr entschluesseln."
        )
