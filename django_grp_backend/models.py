import os
import uuid

from PIL import Image
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.deconstruct import deconstructible

from django_grp_backend.functions import validate_image


class Group(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=100)
    postalcode = models.CharField(max_length=10)
    city = models.CharField(max_length=100)
    group_members = models.ManyToManyField(User, blank=True)
    pdf_template = models.FileField(upload_to=f"docs/", blank=True)

    def get_full_address(self):
        return f"{self.address},\n{self.postalcode}, {self.city}"

    def __str__(self):
        return self.name


@deconstructible
class RandomizedFileName:
    def __call__(self, instance, filename):
        ext = os.path.splitext(filename)[1]  # Get file extension
        random_name = uuid.uuid4().hex  # Generate random string
        return f"images/{random_name}{ext}"


class Resident(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    picture = models.ImageField(
        blank=True,
        null=True,
        upload_to=RandomizedFileName(),
        validators=[validate_image],
    )
    moved_in_since = models.DateField()
    moved_out_since = models.DateField(default=None, null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.picture:
            img = Image.open(self.picture.path)
            if img.height > 800 or img.width > 800:
                output_size = (800, 800)
                img.thumbnail(output_size)
                img.save(self.picture.path)

    def __str__(self):
        return self.get_full_name()


class Protocol(models.Model):
    protocol_date = models.DateField()
    date_added = models.DateField(auto_now_add=True)
    last_updated = models.DateField(auto_now=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    exported = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.group.name} - {self.protocol_date}"


class ProtocolPresence(models.Model):
    protocol = models.ForeignKey(
        Protocol,
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    was_present = models.BooleanField(default=False)

    class Meta:
        unique_together = ("protocol", "user")


class ProtocolItem(models.Model):
    protocol = models.ForeignKey(
        Protocol, related_name="items", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100)
    position = models.IntegerField(default=0)
    value = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.protocol} - {self.name}"


@receiver(post_save, sender=Protocol)
def create_protocol_presence(sender, instance, created, **kwargs):
    if created:
        users_in_group = instance.group.group_members.all()
        for user in users_in_group:
            ProtocolPresence.objects.create(protocol=instance, user=user)
