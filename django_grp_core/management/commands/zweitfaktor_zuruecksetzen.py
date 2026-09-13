"""
Setzt den zweiten Faktor eines Kontos zurueck - von der Kommandozeile.

Der Weg zurueck, wenn kein zweites Verwaltungskonto mehr hilft. Bisher gab
es ihn nicht, und damit gab es eine Sackgasse: ein Traeger mit genau einem
Verwaltungskonto, dessen Telefon in der Waschmaschine liegt, kaeme an keine
Stammdaten mehr. Wiederherstellungscodes sind bewusst nicht vorgesehen
(Entscheidung vom 11. September 2026), und das Zuruecksetzen ueber die
Oberflaeche verlangt ein zweites Konto, das selbst einen Faktor hat.

**Warum die Kommandozeile der richtige Ort dafuer ist.** Wer sie erreicht,
hat Zugang zum Server, auf dem die Anwendung laeuft - er kann ohnehin die
Datenbank lesen und den Container austauschen. Ein Zettel mit
Wiederherstellungscodes waere ein schwaecherer Nachweis als dieser, und er
laege in einer Schublade.

**Warum der Superuser trotzdem nicht ausgenommen ist.** Er ist der
wertvollste Zugang; ihn auszunehmen hiesse, die schwaechste Sicherung auf
den staerksten Schluessel zu legen. Die Pflicht bleibt, und dieser Befehl
ist der Notausgang - einer, der Zugang zum Server verlangt statt nur ein
Passwort.

    docker compose exec api python manage.py zweitfaktor_zuruecksetzen m.kaltenbach
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from django_grp_backend.models import ZweiterFaktor


class Command(BaseCommand):
    help = (
        "Entfernt den zweiten Faktor eines Kontos. Danach genügt wieder das "
        "Passwort, bis er neu eingerichtet ist."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "benutzername",
            help="Das Konto, dessen zweiter Faktor entfernt werden soll.",
        )
        parser.add_argument(
            "--ja",
            action="store_true",
            help="Ohne Rueckfrage ausfuehren.",
        )

    def handle(self, *args, **options):
        name = options["benutzername"]
        konto = User.objects.filter(username=name).first()
        if konto is None:
            raise CommandError(f"Kein Konto mit dem Namen {name!r}.")

        eintrag = ZweiterFaktor.objects.filter(user=konto).first()
        if eintrag is None:
            self.stdout.write(
                f"{name} hat keinen zweiten Faktor. Nichts zu tun."
            )
            return

        if not options["ja"]:
            # Ohne Rueckfrage waere ein Tippfehler im Namen ein stiller
            # Rechteverlust an einem fremden Konto.
            self.stdout.write(
                self.style.WARNING(
                    f"Der zweite Faktor von {name} "
                    f"({konto.get_full_name() or 'ohne Namen'}) wird entfernt."
                )
            )
            self.stdout.write(
                "Danach genügt für dieses Konto wieder das Passwort allein, "
                "bis der Faktor neu eingerichtet ist."
            )
            antwort = input("Fortfahren? [nein/ja] ").strip().lower()
            if antwort not in ("ja", "j", "yes", "y"):
                self.stdout.write("Abgebrochen.")
                return

        eintrag.delete()

        self.stdout.write(
            self.style.SUCCESS(f"Der zweite Faktor von {name} ist entfernt.")
        )
        # Der Hinweis gehoert dazu: dieser Weg hinterlaesst keine Spur im
        # Aenderungsprotokoll, weil dort der handelnde Benutzer fehlt - eine
        # Kommandozeile hat keinen angemeldeten Menschen. Wer ihn benutzt,
        # sollte das im Haus festhalten.
        self.stdout.write(
            "Hinweis: Dieser Weg läuft ohne angemeldetes Konto und steht "
            "deshalb nicht im Änderungsprotokoll. Halten Sie fest, wer ihn "
            "wann benutzt hat."
        )
