"""
Legt die gesetzlichen Feiertage eines Jahres an.

    python manage.py seed_holidays --year 2026 --state NW
    python manage.py seed_holidays --year 2026 --year 2027 --state NW

Wiederholbar: was schon steht, bleibt unangetastet. Wer einen Tag geloescht
hat, weil im Haus durchgearbeitet wird, bekommt ihn nicht zurueck.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from django_grp_org.holiday_service import jahr_anlegen
from django_grp_org.holidays import ALLE_LAENDER, BUNDESLAENDER
from django_grp_org.models import Provider


class Command(BaseCommand):
    help = "Legt die gesetzlichen Feiertage eines Jahres an."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            action="append",
            help="Jahr; mehrfach angebbar. Ohne Angabe: das laufende und das nächste.",
        )
        parser.add_argument(
            "--state",
            required=True,
            help="Bundesland als Kürzel, etwa NW. "
            + ", ".join(kuerzel for kuerzel, _ in BUNDESLAENDER),
        )
        parser.add_argument(
            "--ohne-halbe-tage",
            action="store_true",
            help="Heiligabend und Silvester nicht vorschlagen.",
        )

    def handle(self, *args, **options):
        land = options["state"].upper()
        if land not in ALLE_LAENDER:
            raise CommandError(f"„{land}“ ist kein gültiges Bundesland-Kürzel.")

        provider = Provider.objects.order_by("id").first()
        if provider is None:
            raise CommandError(
                "Es gibt keinen Träger. Bitte zuerst seed_organisation ausführen."
            )

        jahre = options["year"] or [date.today().year, date.today().year + 1]

        for jahr in jahre:
            bericht = jahr_anlegen(
                provider,
                jahr,
                land,
                mit_halben_tagen=not options["ohne_halbe_tage"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{jahr} ({land}): {bericht['created']} angelegt, "
                    f"{bericht['existing']} waren schon da."
                )
            )
