from django.contrib import admin

from .models import MailMessage, MailSettings


@admin.register(MailSettings)
class MailSettingsAdmin(admin.ModelAdmin):
    list_display = ["host", "port", "from_address", "enabled"]


@admin.register(MailMessage)
class MailMessageAdmin(admin.ModelAdmin):
    list_display = ["created_at", "to_address", "subject", "kind", "status"]
    list_filter = ["status", "kind"]
    search_fields = ["to_address", "subject"]
    # Der Postausgang ist ein Beleg. Wer hier etwas aendert, faelscht ihn.
    readonly_fields = [feld.name for feld in MailMessage._meta.fields]
