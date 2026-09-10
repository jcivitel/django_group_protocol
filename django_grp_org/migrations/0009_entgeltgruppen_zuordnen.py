"""
Vorgaben anlegen und den freien Text zuordnen.

Die Entgeltgruppe stand bisher als freier Text am Vertrag. Diese Migration
legt je Träger die Vorgaben an und ordnet zu, was sich zuordnen lässt —
„S 8b", „S8b" und „s 8 b" meinen dasselbe und werden zusammengeführt.

Was sich nicht zuordnen lässt, bleibt als Text stehen. Es wegzuwerfen wäre
bequem und würde eine Angabe vernichten, die jemand einmal eingetragen hat.
"""

from django.db import migrations

from django_grp_org.entgelt import DEFAULT_PAY_GRADES, DEFAULT_SURCHARGES


def schluessel(text: str) -> str:
    """„S 8b", „S8b" und „s 8 b" auf denselben Wert bringen."""
    return "".join(text.split()).lower()


def vorwaerts(apps, schema_editor):
    Provider = apps.get_model("django_grp_org", "Provider")
    PayGrade = apps.get_model("django_grp_org", "PayGrade")
    SurchargeRate = apps.get_model("django_grp_org", "SurchargeRate")
    Contract = apps.get_model("django_grp_org", "Contract")

    for provider in Provider.objects.all():
        for platz, (name, beschreibung) in enumerate(DEFAULT_PAY_GRADES):
            PayGrade.objects.get_or_create(
                provider=provider,
                name=name,
                defaults={"description": beschreibung, "position": platz},
            )
        for kind, percent, note in DEFAULT_SURCHARGES:
            SurchargeRate.objects.get_or_create(
                provider=provider,
                kind=kind,
                defaults={"percent": percent, "note": note},
            )

        # Was im Text steht und keiner Vorgabe entspricht, wird zur eigenen
        # Gruppe. Ein Haustarif mit "EG 9c" soll nicht verloren gehen, bloss
        # weil er nicht im TVöD SuE steht.
        vorhanden = {
            schluessel(eintrag.name): eintrag
            for eintrag in PayGrade.objects.filter(provider=provider)
        }
        naechste = len(DEFAULT_PAY_GRADES)
        for vertrag in Contract.objects.filter(
            employee__provider=provider, pay_grade_ref__isnull=True
        ).exclude(pay_grade=""):
            treffer = vorhanden.get(schluessel(vertrag.pay_grade))
            if treffer is None:
                treffer = PayGrade.objects.create(
                    provider=provider,
                    name=vertrag.pay_grade.strip(),
                    description="Aus dem freien Text übernommen",
                    position=naechste,
                )
                vorhanden[schluessel(treffer.name)] = treffer
                naechste += 1
            vertrag.pay_grade_ref = treffer
            vertrag.save(update_fields=["pay_grade_ref"])


def rueckwaerts(apps, schema_editor):
    """
    Nur die Zuordnung lösen, nicht die Stammdaten löschen.

    Wer die Migration zurücknimmt, will die Spalte los — nicht die
    Entgelttabelle, die inzwischen jemand gepflegt hat.
    """
    Contract = apps.get_model("django_grp_org", "Contract")
    Contract.objects.update(pay_grade_ref=None)


class Migration(migrations.Migration):
    dependencies = [
        ("django_grp_org", "0008_entgeltgruppen_und_zuschlaege"),
    ]

    operations = [
        migrations.RunPython(vorwaerts, rueckwaerts),
    ]
