import os
import random
import uuid

from PIL import Image
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.deconstruct import deconstructible

from django_grp_backend.functions import validate_image


# ============ CUSTOM QUERYSETS ============

class GroupQuerySet(models.QuerySet):
    """Custom QuerySet for Group model."""
    
    def for_user(self, user):
        """Return groups accessible to the user."""
        if user.is_staff:
            return self
        return self.filter(group_members=user)


class ResidentQuerySet(models.QuerySet):
    """Custom QuerySet for Resident model."""
    
    def for_user(self, user):
        """Return residents accessible to the user."""
        if user.is_staff:
            return self
        return self.filter(group__group_members=user)
    
    def active(self):
        """Return only active residents (not moved out)."""
        return self.filter(moved_out_since__isnull=True)


class ProtocolQuerySet(models.QuerySet):
    """Custom QuerySet for Protocol model."""
    
    def for_user(self, user):
        """Return protocols accessible to the user."""
        if user.is_staff:
            return self
        return self.filter(group__group_members=user)
    
    def current_month(self):
        """Return protocols from current month."""
        from django.utils.timezone import now
        today = now().date()
        return self.filter(protocol_date__year=today.year, protocol_date__month=today.month)


# ============ CUSTOM MANAGERS ============

class GroupManager(models.Manager):
    """Custom manager for Group model."""
    
    def get_queryset(self):
        return GroupQuerySet(self.model, using=self._db)
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)


class ResidentManager(models.Manager):
    """Custom manager for Resident model."""
    
    def get_queryset(self):
        return ResidentQuerySet(self.model, using=self._db)
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def active(self):
        return self.get_queryset().active()


class ProtocolManager(models.Manager):
    """Custom manager for Protocol model."""
    
    def get_queryset(self):
        return ProtocolQuerySet(self.model, using=self._db)
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def current_month(self):
        return self.get_queryset().current_month()


class Group(models.Model):
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=100)
    postalcode = models.CharField(max_length=10)
    city = models.CharField(max_length=100)
    color = models.CharField(max_length=9, default="#ffffff")
    group_members = models.ManyToManyField(User, blank=True)
    pdf_template = models.FileField(upload_to=f"docs/", blank=True)
    
    objects = GroupManager()

    def get_full_address(self):
        return f"{self.address},\n{self.postalcode}, {self.city}"

    def __str__(self):
        return self.name


@deconstructible
class RandomizedFileName:
    def __call__(self, instance, filename):
        ext = os.path.splitext(filename)[1]  # Get file extension
        random_name = uuid.uuid4().hex  # Generate random string
        return f"images/{random_name}{ext.lower()}"


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
    
    objects = ResidentManager()

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
    STATUS_CHOICES = [
        ("draft", "Entwurf"),
        ("ready", "Bereit zum Export"),
        ("exported", "Exportiert"),
    ]
    
    protocol_date = models.DateField()
    date_added = models.DateField(auto_now_add=True)
    last_updated = models.DateField(auto_now=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    exported = models.BooleanField(default=False)
    exported_file = models.FileField(upload_to="exports/", blank=True, null=True)
    
    objects = ProtocolManager()

    def __str__(self):
        return f"{self.group.name} - {self.protocol_date}"
    
    @property
    def is_exported(self):
        """Check if protocol is exported (read-only)."""
        return self.status == "exported"


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


class UserPermission(models.Model):
    """
    Fine-grained permissions for users on specific resources.
    
    Allows staff to assign specific read/write permissions on:
    - Residents (create, read, update, delete)
    - Protocols (create, read, update, delete)
    - Groups (read, update)
    """
    PERMISSION_CHOICES = [
        ("read", "Lesezugriff"),
        ("write", "Schreibzugriff"),
        ("delete", "Löschzugriff"),
    ]
    
    RESOURCE_CHOICES = [
        ("resident", "Bewohner"),
        ("protocol", "Protokolle"),
        ("group", "Gruppen"),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permissions")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    resource = models.CharField(max_length=20, choices=RESOURCE_CHOICES)
    permission = models.CharField(max_length=20, choices=PERMISSION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ("user", "group", "resource", "permission")
        ordering = ["user", "group", "resource"]
    
    def __str__(self):
        return f"{self.user.username} - {self.group.name} - {self.resource}: {self.permission}"


@receiver(post_save, sender=Protocol)
def create_protocol_presence(sender, instance, created, **kwargs):
    if created:
        users_in_group = instance.group.group_members.all()
        for user in users_in_group:
            ProtocolPresence.objects.create(protocol=instance, user=user)
