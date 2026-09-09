"""
Token mit Ablaufdatum.

DRF-Token laufen von Haus aus nie ab. Wer sich einmal angemeldet hat, bleibt
angemeldet — bis jemand den Datensatz löscht. Auf einem Diensthandy, das
liegen bleibt, oder nach einem Personalwechsel ist das genau das Falsche.

Die Frist steht in TOKEN_MAX_AGE_HOURS und passt zur Lebensdauer des Cookies
im Frontend (12 h). Damit endet beides zusammen, statt dass ein serverseitig
gültiges Token übrig bleibt, an das niemand mehr denkt.

Was hier bewusst NICHT passiert: eine Verlängerung bei jedem Zugriff. Eine
gleitende Frist heißt in der Praxis „läuft nie ab", solange der Tab offen
ist — und der Tab ist immer offen.

TOKEN_MAX_AGE_HOURS = 0 schaltet die Frist ab und stellt das alte Verhalten
wieder her.
"""

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class AblaufendeTokenAuthentication(TokenAuthentication):
    """Wie TokenAuthentication, verwirft aber zu alte Token."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)

        stunden = getattr(settings, "TOKEN_MAX_AGE_HOURS", 0)
        if stunden:
            alter = timezone.now() - token.created
            if alter > timezone.timedelta(hours=stunden):
                # Aufräumen und ablehnen. Der nächste Anmeldeversuch legt ein
                # frisches an; ein abgelaufenes stehen zu lassen hieße, es
                # später doch noch irgendwo zu akzeptieren.
                token.delete()
                raise AuthenticationFailed(
                    "Die Sitzung ist abgelaufen. Bitte erneut anmelden."
                )

        return user, token
