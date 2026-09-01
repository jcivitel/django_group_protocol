"""
Mandantenfähigkeit (Roadmap Phase 9).

Alle Fachdaten hängen über eine Kette an einem Träger. Diese Datei bestimmt
einmal, welche Träger ein Konto sehen darf, und liefert die passenden Filter -
damit dieselbe Regel überall gilt und nicht in jedem ViewSet neu formuliert
wird.
"""

from django.db.models import Q

from .models import Employee, Provider


def visible_provider_ids(user):
    """
    Träger, die dieses Konto sehen darf.

    - Superuser sehen alles.
    - Wer einen Personaldatensatz hat, sieht genau dessen Träger.
    - Konten ohne Personaldatensatz sehen weiterhin alles. Das ist bewusst
      so: bestehende Verwaltungskonten wären sonst nach dem Update
      ausgesperrt. Sobald einem Konto Personal zugeordnet ist, greift die
      Trennung.

    Rückgabe `None` bedeutet „keine Einschränkung".
    """
    if user.is_superuser:
        return None

    provider_ids = list(
        Employee.objects.filter(user=user).values_list("provider_id", flat=True)
    )
    return provider_ids or None


def limit_to_tenant(queryset, user, path="provider_id"):
    """
    Schränkt ein QuerySet auf die sichtbaren Träger ein.

    `path` ist der Feldpfad zum Träger, z. B. "provider_id" oder
    "department__facility__site__provider_id".
    """
    provider_ids = visible_provider_ids(user)
    if provider_ids is None:
        return queryset
    return queryset.filter(**{f"{path}__in": provider_ids})


def tenant_providers(user):
    """Die sichtbaren Träger als QuerySet."""
    provider_ids = visible_provider_ids(user)
    if provider_ids is None:
        return Provider.objects.all()
    return Provider.objects.filter(id__in=provider_ids)


def tenant_filter(user, path="provider_id") -> Q:
    """Wie limit_to_tenant, aber als Q-Objekt für zusammengesetzte Filter."""
    provider_ids = visible_provider_ids(user)
    if provider_ids is None:
        return Q()
    return Q(**{f"{path}__in": provider_ids})
