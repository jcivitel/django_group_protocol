import os
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from functools import wraps
from django.contrib.auth.models import Group


# Groesste Datei, die die Upload-Endpunkte annehmen. Das Frontend
# verkleinert Bilder schon im Browser; diese Grenze faengt alles ab, was
# daran vorbeikommt. Sie gehoert zusammen mit MAX_UPLOAD_BYTES in
# nextjs_group_protocol/src/lib/uploads.ts und serverActions.bodySizeLimit
# in next.config.ts - wer eine davon aendert, aendert alle drei.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def upload_too_large(file):
    """Lesbare Meldung, wenn die Datei zu gross ist - sonst None."""
    if file.size > MAX_UPLOAD_BYTES:
        return (
            f"Die Datei ist {file.size / 1024 / 1024:.1f} MB gross. "
            f"Erlaubt sind {MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )
    return None


def validate_image(file):
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = [".jpg", ".jpeg", ".png", ".gif"]
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file extension.")

    message = upload_too_large(file)
    if message:
        raise ValidationError(message)


def group_required(group_name):
    """
    Decorator to check if the user belongs to a specific group.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated:
                if (
                    request.user.is_staff
                    or request.user.groups.filter(name=group_name).exists()
                ):
                    return view_func(request, *args, **kwargs)
                else:
                    return HttpResponseForbidden(
                        "You do not have access to this resource."
                    )
            return HttpResponseForbidden("Authentication required.")

        return _wrapped_view

    return decorator
