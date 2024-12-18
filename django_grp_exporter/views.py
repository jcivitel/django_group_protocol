from django.http import HttpResponse

from django_grp_backend.models import Protocol
from django_grp_exporter.func import gen_export


# Create your views here.
def view_protocol(request, protocol_id):
    pdf = gen_export(Protocol.objects.get(pk=protocol_id))

    response = HttpResponse(pdf, content_type="application/pdf")  # Beispiel: PDF-Datei
    response["Content-Disposition"] = 'inline; filename="output_file_name.pdf"'
    return response
