"""
Die Rechtematrix je Person.

    GET  /api/v1/rechte/vorlagen/     die neun Vorlagen und die Gliederung
    GET  /api/v1/rechte/{user_id}/    die Matrix einer Person
    PUT  /api/v1/rechte/{user_id}/    sie setzen

Wer hier schreiben darf, kann sich anschliessend alles Uebrige selbst geben.
Deshalb haengt der Zugang an `PERSONAL_ROLLEN` und nicht an einer der
weicheren Fragen, und deshalb steht jede Aenderung im Aenderungsprotokoll.

**Vier Sperren, und jede hat einen Grund:**

1. Nur wer `PERSONAL_ROLLEN` schreiben darf.
2. Der zweite Faktor muss erfuellt sein - dieselbe Pflicht wie fuer die
   uebrige Verwaltung. Ohne sie waere ein gestohlenes Passwort ein Weg zu
   allen Rechten.
3. Niemand aendert die eigene Matrix. Sonst waere jede Beschraenkung eine,
   die sich in derselben Sitzung wieder aufheben laesst.
4. Ein Superuser laesst sich hier nicht beschneiden. Sein Generalschluessel
   greift ohnehin vor der Matrix; eine Oberflaeche, die etwas anderes
   verspricht, waere eine Luege.
"""

from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend import rechte
from django_grp_backend.models import Rechtezuweisung


def _darf_vergeben(user) -> bool:
    return rechte.darf(user, rechte.PERSONAL_ROLLEN, schreiben=True) and (
        rechte.zweitfaktor_erfuellt(user)
    )


def _person(konto) -> dict:
    name = konto.get_full_name().strip() or konto.username
    return {"id": konto.id, "username": konto.username, "name": name}


class VorlagenView(APIView):
    """
    Die Vorlagen und die Gliederung der Matrix.

    Beides kommt aus derselben Quelle wie die Rechnung dahinter. Eine
    Oberflaeche, die ihre eigene Liste der Merkmale mitbraechte, waere beim
    naechsten Zusatz genau eine Zeile hinterher - und niemand merkte es,
    weil eine fehlende Zeile aussieht wie ein Recht, das niemand hat.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "gruppen": [
                    {
                        "name": name,
                        "merkmale": [
                            {
                                "kennung": aktion,
                                "name": rechte.AKTION_LABEL[aktion],
                                "hinweis": rechte.AKTION_HINWEIS.get(aktion, ""),
                            }
                            for aktion in zeilen
                        ],
                    }
                    for name, zeilen in rechte.AKTION_GRUPPEN
                ],
                "vorlagen": rechte.vorlagen(),
                "stufen": [
                    {"wert": rechte.KEIN, "name": "Kein Zugriff"},
                    {"wert": rechte.LESEN, "name": "Lesen"},
                    {"wert": rechte.SCHREIBEN, "name": "Lesen und schreiben"},
                ],
            },
            status=status.HTTP_200_OK,
        )


class MatrixView(APIView):
    """Die Matrix einer Person lesen und setzen."""

    permission_classes = [IsAuthenticated]

    def get(self, request, user_id: int):
        if not _darf_vergeben(request.user):
            return Response(
                {"success": False, "error": "Dafür fehlen die Rechte."},
                status=status.HTTP_403_FORBIDDEN,
            )

        konto = User.objects.filter(id=user_id).first()
        if konto is None:
            return Response(
                {"success": False, "error": "Konto nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "person": _person(konto),
                "rechte": rechte.matrix_von(konto),
                # Ohne diese Angabe sieht die Oberflaeche beim ersten
                # Oeffnen eine gefuellte Matrix und haelt sie fuer gesetzt.
                # Sie ist aber nur die Zeile der bisherigen Stufe.
                "eigene_matrix": rechte.hat_eigene_matrix(konto),
                # Ein Superuser laesst sich hier nicht beschneiden. Die
                # Oberflaeche soll das sagen, statt eine Matrix anzubieten,
                # die nichts bewirkt.
                "generalschluessel": rechte.generalschluessel(konto),
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def put(self, request, user_id: int):
        if not _darf_vergeben(request.user):
            return Response(
                {
                    "success": False,
                    "error": (
                        "Rechte vergeben darf nur, wer das Recht dazu hat und "
                        "einen zweiten Faktor eingerichtet."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        konto = User.objects.filter(id=user_id).first()
        if konto is None:
            return Response(
                {"success": False, "error": "Konto nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if konto == request.user:
            return Response(
                {
                    "success": False,
                    "error": (
                        "Die eigenen Rechte lassen sich hier nicht ändern. "
                        "Sonst wäre jede Beschränkung eine, die sich sofort "
                        "wieder aufheben lässt."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if rechte.generalschluessel(konto):
            return Response(
                {
                    "success": False,
                    "error": (
                        "Dieses Konto trägt den Generalschlüssel und darf "
                        "ohnehin alles. Eine Matrix hätte hier keine Wirkung."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        gewuenscht = request.data.get("rechte")
        if not isinstance(gewuenscht, dict):
            return Response(
                {"success": False, "error": "Es fehlt die Matrix."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        unbekannt = sorted(set(gewuenscht) - set(rechte.ALLE_AKTIONEN))
        if unbekannt:
            # Lieber abweisen als stillschweigend uebergehen: ein Tippfehler
            # in der Kennung waere sonst ein Recht, das niemand vergibt und
            # das trotzdem in der Tabelle steht.
            return Response(
                {
                    "success": False,
                    "error": f"Unbekannte Merkmale: {', '.join(unbekannt)}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        erlaubt = {rechte.KEIN, rechte.LESEN, rechte.SCHREIBEN}
        wer = request.user.get_full_name() or request.user.username

        for aktion in rechte.ALLE_AKTIONEN:
            stufe = gewuenscht.get(aktion, rechte.KEIN)
            if not isinstance(stufe, int) or stufe not in erlaubt:
                return Response(
                    {
                        "success": False,
                        "error": f"Ungültige Stufe bei {aktion}: {stufe!r}",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # update_or_create und nicht loeschen-und-neu-anlegen: sonst
            # stuende im Aenderungsprotokoll bei jedem Speichern die ganze
            # Matrix zweimal, einmal geloescht und einmal angelegt, und die
            # eine Zeile, die sich wirklich geaendert hat, ginge darin unter.
            Rechtezuweisung.objects.update_or_create(
                user=konto,
                aktion=aktion,
                defaults={"stufe": stufe, "geaendert_von": wer},
            )

        return Response(
            {
                "success": True,
                "data": {
                    "person": _person(konto),
                    "rechte": rechte.matrix_von(konto),
                    "eigene_matrix": True,
                },
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, user_id: int):
        """
        Die Matrix entfernen; danach entscheidet wieder die Zugriffsstufe.

        Der Weg zurueck, wenn sich jemand vertan hat. Er ist nicht dasselbe
        wie "alles auf kein Zugriff" - das eine gibt das Konto an die alte
        Regelung zurueck, das andere sperrt es aus.
        """
        if not _darf_vergeben(request.user):
            return Response(
                {"success": False, "error": "Dafür fehlen die Rechte."},
                status=status.HTTP_403_FORBIDDEN,
            )

        konto = User.objects.filter(id=user_id).first()
        if konto is None:
            return Response(
                {"success": False, "error": "Konto nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if konto == request.user:
            return Response(
                {"success": False, "error": "Nicht am eigenen Konto."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Rechtezuweisung.objects.filter(user=konto).delete()
        return Response(
            {
                "success": True,
                "data": {
                    "person": _person(konto),
                    "rechte": rechte.matrix_von(konto),
                    "eigene_matrix": False,
                },
            },
            status=status.HTTP_200_OK,
        )
