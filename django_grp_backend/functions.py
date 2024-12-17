import os
from django.core.exceptions import ValidationError


def validate_image(file):
    ext = os.path.splitext(file.name)[1]
    valid_extensions = [".jpg", ".jpeg", ".png", ".gif"]
    if ext.lower() not in valid_extensions:
        raise ValidationError("Unsupported file extension.")
