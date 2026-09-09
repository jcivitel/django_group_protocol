"""
Seitenweise Antworten.

Die Form ist die von DRF: {count, next, previous, results}. Das Frontend hat
sie schon immer akzeptiert (unwrapList in lib/api/client.ts) - nur geliefert
wurde sie nie, weil keine Pagination gesetzt war.

Die Seitengroesse ist gross gewaehlt und laesst sich je Anfrage bis zu einer
Obergrenze anheben. Beides zusammen ist der Punkt: der uebliche Fall kommt
mit einer Anfrage aus, und die eine Anfrage, die alles will, bekommt es
trotzdem nicht.
"""

from django.conf import settings
from rest_framework.pagination import PageNumberPagination


class Seitenweise(PageNumberPagination):
    page_size_query_param = "page_size"

    @property
    def max_page_size(self):
        return getattr(settings, "API_PAGE_SIZE_MAX", 1000)
