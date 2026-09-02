"""
Konten und Personaldatensaetze zusammenfuehren.

Bisher waren das zwei Listen: Personalakten unter /personal, Konten unter
/admin/benutzer. Wer eine Person anlegte, legte sie zweimal an - und wer
eine vergass, hatte eine Karteileiche. Ab hier ist der Personaldatensatz
die Person, sein `user` ihr Zugang.

Die Migration ist defensiv: gibt es noch keinen Traeger, passiert nichts.
Das ist der Fall einer frischen Installation, um den sich der
Einrichtungsassistent kuemmert.
"""

from django.db import migrations


def link_accounts(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Employee = apps.get_model("django_grp_org", "Employee")
    Provider = apps.get_model("django_grp_org", "Provider")

    provider = Provider.objects.order_by("id").first()

    # Vorhandene Personaldatensaetze: Zugriff aus dem Konto ableiten.
    for employee in Employee.objects.select_related("user"):
        if employee.user_id is None:
            continue
        user = User.objects.filter(pk=employee.user_id).first()
        if user is None:
            continue
        employee.access_level = "admin" if user.is_staff else "specialist"
        employee.save(update_fields=["access_level"])

    if provider is None:
        return

    # Konten ohne Personaldatensatz bekommen einen. Ohne diesen Schritt
    # verschwaende die zusammengelegte Ansicht genau die Konten, die es
    # schon gibt - allen voran das des Administrators.
    linked = set(
        Employee.objects.exclude(user__isnull=True).values_list("user_id", flat=True)
    )
    for user in User.objects.all():
        if user.id in linked:
            continue
        Employee.objects.create(
            provider=provider,
            user=user,
            access_level="admin" if user.is_staff else "specialist",
            first_name=user.first_name or user.username,
            last_name=user.last_name or "",
            email=user.email or "",
            hired_on=user.date_joined.date(),
        )


def unlink(apps, schema_editor):
    """
    Rueckwaerts wird nichts geloescht.

    Ein Personaldatensatz kann inzwischen Vertraege, Dienste und Zeitkonten
    tragen. Die wegen eines Rueckbaus zu entfernen waere schlimmer als ein
    Datensatz zu viel.
    """
    return


class Migration(migrations.Migration):
    dependencies = [
        ("django_grp_org", "0003_employee_access_level"),
    ]

    operations = [
        migrations.RunPython(link_accounts, unlink),
    ]
