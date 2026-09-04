"""
Anmeldung mit Benutzername oder E-Mail.

Als Backend und nicht als Sonderfall in der Login-Ansicht: `authenticate()`
wird an mehreren Stellen aufgerufen - vom API-Endpunkt, vom Django-Admin, vom
Einrichtungsassistenten. Wer das nur an einer davon einbaut, hat eine
Anmeldung, die je nach Tuer anders funktioniert.

**Zur Mehrdeutigkeit.** Djangos User-Modell erzwingt keine eindeutige
E-Mail-Adresse. Tragen zwei Konten dieselbe ein, laesst sich nicht
entscheiden, wer gemeint ist - dann wird niemand angemeldet. Das erste
passende Konto zu nehmen waere die bequeme Variante und zugleich eine Luecke:
wer die Adresse einer Kollegin kennt und sich selbst ein Konto damit anlegt,
koennte je nach Sortierung deren Platz einnehmen.

Der Benutzername hat immer Vorrang. Nur wenn keiner passt, wird die Eingabe
als E-Mail gelesen.
"""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

logger = logging.getLogger("django_grp.auth")


class UsernameOrEmailBackend(ModelBackend):
    """Nimmt im Feld "Benutzername" auch eine E-Mail-Adresse an."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()

        eingabe = username or kwargs.get(User.USERNAME_FIELD) or kwargs.get("email")
        if not eingabe or not password:
            return None
        eingabe = eingabe.strip()

        benutzer = User.objects.filter(**{User.USERNAME_FIELD: eingabe}).first()

        if benutzer is None and "@" in eingabe:
            # E-Mail ohne Ruecksicht auf Gross- und Kleinschreibung: niemand
            # tippt seine Adresse zweimal gleich, und kein Mailserver
            # unterscheidet danach.
            treffer = list(User.objects.filter(email__iexact=eingabe)[:2])
            if len(treffer) > 1:
                logger.warning(
                    "Anmeldung abgelehnt: %s gehoert zu mehreren Konten", eingabe
                )
                return None
            benutzer = treffer[0] if treffer else None

        if benutzer is None:
            # Dieselbe Rechenzeit wie bei einem echten Konto verbrauchen.
            # Ohne das verraet die Antwortzeit, welche Namen es gibt.
            User().set_password(password)
            return None

        if benutzer.check_password(password) and self.user_can_authenticate(benutzer):
            return benutzer
        return None
