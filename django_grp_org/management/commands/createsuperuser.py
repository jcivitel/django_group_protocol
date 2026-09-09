"""
`manage.py createsuperuser` legt jetzt auch den Personaldatensatz an.

Django legt nur den Zugang an — das ist richtig so, Django weiss nichts von
Wohngruppen. In dieser Anwendung ist ein Konto ohne Personaldatensatz aber
ein halbes Konto: kein Foto, kein Dienstplan, keine Zeitbuchung. Wer sich
das erste Mal einen Superuser anlegt, steht danach vor genau dieser Haelfte
und sieht nur den Hinweis, dass etwas fehlt.

Warum eine ueberschriebene Kommandozeile und kein Signal auf User: ein
Signal feuert bei jedem gespeicherten Superuser, auch beim Umbenennen einer
bestehenden Person, und es feuert an Stellen, an denen niemand einen neuen
Personaldatensatz erwartet. Hier greift es genau einmal, an der Stelle, an
der jemand ausdruecklich ein Konto anlegt.

Das Konto entsteht in Djangos `handle()`, und das gibt es nicht zurueck.
Deshalb haengt sich das Kommando fuer die Dauer des Aufrufs an `post_save`
statt hinterher zu raten, welches der Konten gerade entstanden ist.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.management.commands import createsuperuser
from django.db.models.signals import post_save

from django_grp_org.personal import personaldatensatz_anlegen


class Command(createsuperuser.Command):
    help = (
        "Legt einen Superuser an - samt Personaldatensatz, sofern bereits "
        "ein Traeger eingerichtet ist."
    )

    def handle(self, *args, **options):
        angelegt = []

        def merken(sender, instance, created, **kwargs):
            if created:
                angelegt.append(instance)

        User = get_user_model()
        post_save.connect(merken, sender=User, dispatch_uid="gp-createsuperuser")
        try:
            ergebnis = super().handle(*args, **options)
        finally:
            post_save.disconnect(sender=User, dispatch_uid="gp-createsuperuser")

        for user in angelegt:
            employee = personaldatensatz_anlegen(user)
            if employee is None:
                self.stdout.write(
                    self.style.WARNING(
                        "Kein Personaldatensatz angelegt: es gibt noch keinen "
                        "Traeger. Nach der Einrichtung der Organisation laesst "
                        "sich das Konto unter Personal verknuepfen."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Personaldatensatz angelegt: {employee.get_full_name()}."
                    )
                )

        return ergebnis
