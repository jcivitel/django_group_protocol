from django.urls import re_path

from django_grp_backend.views import serve_file

urlpatterns = [
    re_path(r"(?P<path>.*)$", serve_file)
]
