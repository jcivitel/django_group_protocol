import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404


# Create your views here.
@login_required
def serve_file(request, path):
    file_path = os.path.join(settings.MEDIA_ROOT, path)

    if not os.path.abspath(file_path).startswith(os.path.abspath(settings.MEDIA_ROOT)):
        raise Http404("Invalid file path")

    if not os.path.exists(file_path):
        raise Http404("File does not exist")

    # Serve the file
    return FileResponse(open(file_path, 'rb'))
