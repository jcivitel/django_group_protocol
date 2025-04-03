import os
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from functools import wraps
from django.contrib.auth.models import Group


def validate_image(file):
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = [".jpg", ".jpeg", ".png", ".gif"]
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file extension.")


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
