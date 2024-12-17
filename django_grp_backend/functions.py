import os
from django.core.exceptions import ValidationError


def validate_image(file):
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = [".jpg", ".jpeg", ".png", ".gif"]
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file extension.")
