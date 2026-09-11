from rest_framework import serializers
from django.contrib.auth.models import User

from django_grp_backend.access import ADMIN, SPECIALIST, access_level, employee_of
from django_grp_backend.models import (
    ChecklistItem,
    Incident,
    Medication,
    MedicationAdministration,
    PocketMoneyEntry,
    ResidentAbsence,
    Allergy,
    Consent,
    Protocol,
    ProtocolAttendance,
    ProtocolItem,
    ProtocolObservation,
    ProtocolTemplate,
    ProtocolTemplateItem,
    ProtocolTodo,
    Group,
    Resident,
    ResidentContact,
    ProtocolPresence,
)


class EigeneGruppeMixin:
    """
    Bindet ein schreibbares `group`-Feld an die Gruppen des Kontos.

    Ohne das laesst sich ein Protokoll oder ein Bewohner beim Anlegen einer
    fremden Gruppe zuordnen - die Nummer steht im Rumpf der Anfrage, und
    niemand hat sie geprueft. Das ViewSet filtert nur, was es HERAUSgibt
    (get_queryset), nicht was hineingeschrieben wird. Genau diese Luecke
    waren S1 und S2 der Analyse.

    Die Pruefung sitzt im Serializer und nicht im View, weil sie damit fuer
    jeden Weg gilt: anlegen, aendern, Sammelimport.
    """

    def validate_group(self, group):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            raise serializers.ValidationError("Nicht angemeldet.")

        if not Group.objects.for_user(user).filter(id=group.id).exists():
            raise serializers.ValidationError(
                "Diese Gruppe steht dir nicht offen."
            )
        return group


class ProtocolItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "name", "position", "value", "kind", "data"]


class ProtocolTodoSerializer(serializers.ModelSerializer):
    """
    Eine Aufgabe aus einem Protokoll.

    `done_by` kommt aus der Anmeldung und nicht aus dem Formular: wer
    abgehakt hat, gehoert zur Dokumentation und nicht in ein freies Feld.
    """

    protocol = serializers.IntegerField(source="protocol.id", read_only=True)
    is_done = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProtocolTodo
        fields = [
            "id",
            "protocol",
            "what",
            "who",
            "when",
            "done_at",
            "done_by",
            "is_done",
            "is_overdue",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "protocol",
            "done_by",
        ]


class ProtocolSerializer(EigeneGruppeMixin, serializers.ModelSerializer):
    items = ProtocolItemSerializer(many=True, required=False)
    exported_file = serializers.SerializerMethodField()

    class Meta:
        model = Protocol
        fields = [
            "id",
            "protocol_date",
            "group",
            "items",
            "exported",
            "status",
            "exported_file",
            "template",
            "topic",
        ]
        # `exported` ist eine Folge des Status, keine Eingabe. Schreibbar
        # liess sich ein Entwurf als exportiert kennzeichnen, ohne dass die
        # Sperre gegriffen haette - die prueft `status`. Zwei Felder, die
        # dasselbe meinen und auseinanderlaufen koennen, sind eine Luecke,
        # auch wenn sie erst der uebernaechste Codepfad aufreisst.
        read_only_fields = ["exported"]

    def get_exported_file(self, obj):
        """Return full URL for exported file if available."""
        try:
            if obj.exported_file:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.exported_file.url)
                return obj.exported_file.url
        except (AttributeError, TypeError):
            pass
        return None


class ProtocolSummarySerializer(serializers.ModelSerializer):
    """Serializer for protocol summary without items (list view)."""

    class Meta:
        model = Protocol
        fields = [
            "id",
            "protocol_date",
            "group",
            "exported",
            "status",
            "template",
            "topic",
        ]

    def get_group_name(self, obj):
        """Get group name from the related group object."""
        try:
            return obj.group.name if obj.group else None
        except (AttributeError, TypeError):
            return None


class GroupSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField(source="get_members", read_only=True)
    pdf_template = serializers.FileField(required=False, allow_null=True)
    # Zwei Felder, die zusammengehoeren: short_name ist das gepflegte
    # Kuerzel und darf leer sein, short_label ist das, was angezeigt wird -
    # notfalls aus dem Namen abgeleitet. So bleibt "nichts eingetragen"
    # unterscheidbar von einer bewussten Eingabe.
    short_label = serializers.CharField(read_only=True)

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "short_name",
            "short_label",
            "address",
            "postalcode",
            "city",
            "members",
            "pdf_template",
            "color",
        ]

    def get_members(self, obj):
        """
        Bewohner dieser Gruppe.

        Ueber die Rueckbeziehung statt ueber eine eigene Abfrage: das ViewSet
        laedt sie mit prefetch_related("resident_set") vor, und damit kostet
        die Liste eine Abfrage statt einer je Gruppe (Analyse 6.7, N+1).
        """
        try:
            return ResidentSerializer(
                obj.resident_set.all(), many=True, context=self.context
            ).data
        except (AttributeError, TypeError):
            return []

    def update(self, instance, validated_data):
        """
        Update group with only non-null fields.
        Null fields remain unchanged.
        """
        # Only update fields that are present in the request
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class ResidentSerializer(EigeneGruppeMixin, serializers.ModelSerializer):
    picture = serializers.SerializerMethodField()
    # Zwei knappe Angaben statt der ganzen Liste. Sie stehen auch in der
    # Uebersicht, und dort waeren vollstaendige Allergien je Zeile ein
    # Vielfaches an Daten fuer eine Angabe, die man nur ueberfliegt.
    critical_allergies = serializers.SerializerMethodField()
    allergy_count = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    # Gerechnet und nicht gespeichert - ein Alter altert, waehrend niemand
    # hinsieht.
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Resident
        fields = [
            "id",
            "first_name",
            "last_name",
            "birth_date",
            "gender",
            "gender_display",
            "age",
            "moved_in_since",
            "moved_out_since",
            "group",
            "school",
            "school_class",
            "school_contact",
            "picture",
            "critical_allergies",
            "allergy_count",
        ]

    def get_critical_allergies(self, obj) -> list[str]:
        """Nur die schweren, und nur ihre Bezeichnung."""
        return [
            allergie.name
            for allergie in obj.allergies.all()
            if allergie.severity == "severe"
        ]

    def get_allergy_count(self, obj) -> int:
        return len(obj.allergies.all())

    def get_picture(self, obj):
        """Return full URL for resident picture if available."""
        try:
            if obj.picture:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.picture.url)
                return obj.picture.url
        except (AttributeError, TypeError):
            pass
        return None


class AllergySerializer(serializers.ModelSerializer):
    """Allergien und Unvertraeglichkeiten einer Bewohnerin oder eines Bewohners."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    severity_display = serializers.CharField(
        source="get_severity_display", read_only=True
    )
    is_critical = serializers.BooleanField(read_only=True)

    class Meta:
        model = Allergy
        fields = [
            "id",
            "resident",
            "kind",
            "kind_display",
            "name",
            "severity",
            "severity_display",
            "is_critical",
            "reaction",
            "note",
        ]
        read_only_fields = ["resident"]


class ConsentSerializer(serializers.ModelSerializer):
    """
    Einwilligungen der Sorgeberechtigten.

    `status` kommt vom Modell und wird nicht gespeichert: eine Einwilligung
    laeuft ab, waehrend niemand hinsieht, und ein gespeicherter Stand waere
    am Tag danach falsch.
    """

    subject_display = serializers.CharField(
        source="get_subject_display", read_only=True
    )
    status = serializers.CharField(read_only=True)
    status_display = serializers.CharField(read_only=True)

    class Meta:
        model = Consent
        fields = [
            "id",
            "resident",
            "subject",
            "subject_display",
            "granted",
            "granted_by",
            "granted_on",
            "valid_until",
            "revoked_on",
            "note",
            "status",
            "status_display",
        ]
        read_only_fields = ["resident"]


class ResidentAbsenceSerializer(serializers.ModelSerializer):
    """Wann ein Kind nicht da war."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = ResidentAbsence
        fields = [
            "id",
            "resident",
            "kind",
            "kind_display",
            "start_date",
            "end_date",
            "counts_as_occupied",
            "note",
            "is_running",
        ]
        read_only_fields = ["resident"]


class MedicationAdministrationSerializer(serializers.ModelSerializer):
    """
    Eine Gabe. Nur anlegen und lesen - aendern und loeschen sperrt das Modell.
    """

    class Meta:
        model = MedicationAdministration
        fields = [
            "id",
            "medication",
            "scheduled_for",
            "given_at",
            "given_by",
            "given_by_name",
            "amount",
            "skipped",
            "reason",
            "corrects",
            "created_at",
        ]
        read_only_fields = ["given_by", "given_by_name", "created_at"]

    def validate(self, attrs):
        # Eine ausgelassene Gabe ohne Grund beantwortet die Frage nicht, um
        # die es geht.
        if attrs.get("skipped") and not (attrs.get("reason") or "").strip():
            raise serializers.ValidationError(
                {"reason": "Bei einer ausgelassenen Gabe gehört der Grund dazu."}
            )
        return attrs


class MedicationSerializer(serializers.ModelSerializer):
    """Ein Medikament mit den Gaben der letzten Tage."""

    is_current = serializers.BooleanField(read_only=True)
    administrations = serializers.SerializerMethodField()

    class Meta:
        model = Medication
        fields = [
            "id",
            "resident",
            "agent",
            "product",
            "dose",
            "times",
            "as_needed",
            "prescribed_by",
            "valid_from",
            "valid_to",
            "note",
            "is_current",
            "administrations",
        ]
        read_only_fields = ["resident"]

    def get_administrations(self, obj):
        """
        Nur die juengsten. Der Nachweis waechst taeglich; die Seite braucht
        den Ueberblick und nicht das Archiv.
        """
        letzte = obj.administrations.all()[:30]
        return MedicationAdministrationSerializer(letzte, many=True).data


class IncidentSerializer(EigeneGruppeMixin, serializers.ModelSerializer):
    """Ein besonderes Vorkommnis nach § 47 SGB VIII."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    needs_report = serializers.BooleanField(read_only=True)
    resident_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Incident
        fields = [
            "id",
            "group",
            "group_name",
            "resident",
            "resident_name",
            "kind",
            "kind_display",
            "occurred_at",
            "description",
            "immediate_action",
            "participants",
            "reported_to",
            "reported_at",
            "status",
            "status_display",
            "needs_report",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_resident(self, resident):
        """
        Dieselbe Luecke wie bei der Gruppe, eine Ebene tiefer: `resident` ist
        schreibbar, und die Nummer kommt aus dem Rumpf der Anfrage.
        """
        if resident is None:
            return resident
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not Resident.objects.for_user(user).filter(
            id=resident.id
        ).exists():
            raise serializers.ValidationError(
                "Diese Person steht dir nicht offen."
            )
        return resident

    def get_resident_name(self, obj):
        return obj.resident.get_full_name() if obj.resident else ""

    def get_recorded_by_name(self, obj):
        if obj.recorded_by is None:
            return ""
        return obj.recorded_by.get_full_name() or obj.recorded_by.username


class ChecklistItemSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = ChecklistItem
        fields = [
            "id",
            "resident",
            "kind",
            "kind_display",
            "title",
            "done_on",
            "done_by",
            "note",
            "position",
        ]
        read_only_fields = ["resident"]


class PocketMoneyEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    signed_amount = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True
    )

    class Meta:
        model = PocketMoneyEntry
        fields = [
            "id",
            "resident",
            "date",
            "kind",
            "kind_display",
            "amount",
            "signed_amount",
            "note",
            "recorded_by",
        ]
        read_only_fields = ["resident", "recorded_by"]


class ResidentContactSerializer(serializers.ModelSerializer):
    """Kontaktdaten der Erziehungsberechtigten und Bezugspersonen."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    reachability = serializers.CharField(read_only=True)

    class Meta:
        model = ResidentContact
        fields = [
            "id",
            "resident",
            "kind",
            "kind_display",
            "name",
            "relationship",
            "organisation",
            "phone",
            "mobile",
            "email",
            "address",
            "has_custody",
            "is_emergency",
            "note",
            "position",
            "reachability",
        ]
        # resident kommt aus der URL, nicht aus dem Rumpf - sonst koennte ein
        # Kontakt an eine fremde Bewohnerakte gehaengt werden.
        read_only_fields = ["id", "resident", "kind_display", "reachability"]


class ResidentPictureUploadSerializer(serializers.ModelSerializer):
    """Serializer for uploading resident picture."""

    picture = serializers.ImageField(required=True, allow_null=False)

    class Meta:
        model = Resident
        fields = ["id", "picture"]
        read_only_fields = ["id"]

    def get_picture(self, obj):
        """Return full URL for resident picture if available."""
        try:
            if obj.picture:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.picture.url)
                return obj.picture.url
        except (AttributeError, TypeError):
            pass
        return None


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "protocol", "name", "position", "value", "kind", "data"]


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Das eigene Profil - lesen und den Namen aendern.

    Die E-Mail-Adresse steht hier bewusst nur lesend.

    Sie ist in dieser Anwendung kein Kontaktfeld, sondern ein Zugang: mit
    ihr laesst sich anmelden (UsernameOrEmailBackend) und ueber sie laeuft
    das Zuruecksetzen des Passworts. Wer sie selbst aendern kann, kann sein
    Konto auf eine Adresse umhaengen, die er woanders kontrolliert - und
    hinterher fuehrt der Weg zurueck ueber "Passwort vergessen" dorthin.
    Bei einem Tippfehler faellt dasselbe ohne boese Absicht an: die Person
    sperrt sich aus und merkt es erst, wenn sie das Passwort braucht.

    Beides gehoert an eine Stelle, an der jemand hinsieht. Aendern kann die
    Adresse deshalb die Verwaltung (UserAdminDetailView), und die Pruefung
    auf Doppelvergabe steht dort.
    """

    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "date_joined",
            "is_staff",
            "is_superuser",
        ]

    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [group.name for group in Group.objects.filter(group_members=obj)]


class UserGroupPermissionSerializer(serializers.ModelSerializer):
    """Serializer for group with user permissions."""

    permissions = serializers.SerializerMethodField()
    resident_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "address",
            "postalcode",
            "city",
            "permissions",
            "resident_count",
        ]

    def get_permissions(self, obj):
        """
        Was dieses Konto in dieser Gruppe darf.

        Frueher stand hier `can_edit = is_member or is_staff` - die Stufe
        "Aushilfe / Azubi" kam schlicht nicht vor. Das Frontend zeigte
        Bearbeiten-Knoepfe, die serverseitig in ein 403 liefen. Jetzt
        antwortet diese Stelle mit derselben Regel, die auch durchgesetzt
        wird: access_level plus Mitgliedschaft.
        """
        request = self.context.get("request")
        if not request:
            return {}

        user = request.user
        is_member = obj.group_members.filter(id=user.id).exists()
        stufe = access_level(user)
        darf_verwalten = stufe == ADMIN or bool(getattr(user, "is_superuser", False))
        darf_schreiben = darf_verwalten or (stufe == SPECIALIST and is_member)

        return {
            "is_member": is_member,
            "is_staff": darf_verwalten,
            "access_level": stufe,
            "can_view": is_member or darf_verwalten,
            "can_edit": darf_schreiben,
            # Loeschen kaskadiert auf Bewohner UND Protokolle. Das bleibt
            # der Verwaltung vorbehalten.
            "can_delete": darf_verwalten,
        }

    def get_resident_count(self, obj):
        """Get number of residents in this group."""
        return obj.resident_set.count()


class UserDetailedProfileSerializer(serializers.ModelSerializer):
    """Serializer for detailed authenticated user profile with group permissions."""

    groups_with_permissions = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups_with_permissions",
            "employee",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "date_joined",
            "is_staff",
            "is_superuser",
        ]

    def get_groups_with_permissions(self, obj):
        """Get all accessible groups with permissions."""
        groups = Group.objects.for_user(obj)
        serializer = UserGroupPermissionSerializer(
            groups, many=True, context={"request": self.context.get("request")}
        )
        return serializer.data

    def get_employee(self, obj):
        """
        Der eigene Personaldatensatz, sofern das Konto mit einem verknuepft
        ist - sonst null.

        Nur das Noetige: die Kennung, damit die Profilseite das eigene Foto
        an /employee/{id}/picture/ schicken kann, und die Adresse des
        Bildes, damit sie es anzeigen kann. Alles Weitere - Vertrag,
        Personalnummer, Zeitkonto - steht unter Personal und gehoert nicht
        in eine Antwort, die jede Seite dieser Anwendung mitliest.
        """
        employee = employee_of(obj)
        if employee is None:
            return None

        request = self.context.get("request")
        bild = None
        if employee.picture:
            bild = (
                request.build_absolute_uri(employee.picture.url)
                if request
                else employee.picture.url
            )

        return {
            "id": employee.id,
            "full_name": employee.get_full_name(),
            "picture": bild,
        }


class ProtocolPresenceSerializer(serializers.ModelSerializer):
    """Serializer for ProtocolPresence model."""

    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolPresence
        fields = ["id", "protocol", "user", "user_name", "was_present"]

    def get_user_name(self, obj):
        """
        Anzeigename der Person.

        Vorher stand hier stur "{Vorname} {Nachname}". Beim Konto aus dem
        Einrichtungsassistenten sind beide leer, das Ergebnis war ein
        einzelnes Leerzeichen - und im Protokoll und im PDF stand
        "Benutzer #1". Der Benutzername ist kein schoener Name, aber ein
        echter.
        """
        name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return name or obj.user.get_username()


class GroupPDFTemplateSerializer(serializers.ModelSerializer):
    """Serializer for updating Group PDF template."""

    class Meta:
        model = Group
        fields = ["id", "name", "pdf_template"]
        read_only_fields = ["id", "name"]


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed user information with permissions."""

    groups = serializers.SerializerMethodField()
    access_level = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "is_active",
            "date_joined",
            "groups",
            "access_level",
        ]
        read_only_fields = [
            "id",
            "is_staff",
            "is_superuser",
            "date_joined",
        ]

    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [
            {"id": group.id, "name": group.name}
            for group in Group.objects.filter(group_members=obj)
        ]

    def get_access_level(self, obj):
        """
        Die Zugriffsstufe des Kontos.

        Hier stand frueher die feingranulare Rechteliste (UserPermission).
        Sie wurde von keinem einzigen Endpunkt ausgewertet - wer in der
        Oberflaeche jemanden auf "nur lesen" stellte, aenderte damit nichts.
        Was wirklich gilt, steht in django_grp_backend/access.py.
        """
        return access_level(obj)


class UserStaffSerializer(serializers.ModelSerializer):
    """Serializer for staff users listing."""

    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
        ]

    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [group.name for group in Group.objects.filter(group_members=obj)]


class ProtocolTemplateItemSerializer(serializers.ModelSerializer):
    """Baustein einer Protokollvorlage."""

    class Meta:
        model = ProtocolTemplateItem
        fields = [
            "id",
            "name",
            "position",
            "kind",
            "hint",
            "value",
            "columns",
            "rows",
        ]


class ProtocolTemplateSerializer(serializers.ModelSerializer):
    """
    Protokollvorlage samt Bausteinen.

    Die Bausteine werden verschachtelt geschrieben - anders als bei
    ProtocolSerializer.items ist create()/update() hier ausdruecklich
    implementiert, sonst wuerde DRF beim Speichern abbrechen.
    """

    items = ProtocolTemplateItemSerializer(many=True, required=False)

    class Meta:
        model = ProtocolTemplate
        fields = [
            "id",
            "name",
            "description",
            "group",
            "is_active",
            "position",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        template = ProtocolTemplate.objects.create(**validated_data)
        self._write_items(template, items)
        return template

    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items is not None:
            instance.items.all().delete()
            self._write_items(instance, items)
        return instance

    @staticmethod
    def _write_items(template, items):
        for position, item in enumerate(items, start=1):
            item.setdefault("position", position)
            ProtocolTemplateItem.objects.create(template=template, **item)


class ProtocolAttendanceSerializer(serializers.ModelSerializer):
    """Teilnahme eines Bewohners am Gruppenangebot."""

    resident_name = serializers.SerializerMethodField()
    resident_picture = serializers.SerializerMethodField()

    class Meta:
        model = ProtocolAttendance
        fields = [
            "id",
            "protocol",
            "resident",
            "resident_name",
            "resident_picture",
            "was_present",
            "note",
        ]
        read_only_fields = ["id", "protocol"]

    def validate_resident(self, resident):
        """
        Nur Bewohner der Gruppe, um die es geht.

        `resident` kommt als Nummer aus dem Rumpf; ohne diese Pruefung liesse
        sich eine fremde Bewohnerin als Teilnehmerin eintragen - und ihr Name
        stuende danach in einem Protokoll, das sie nichts angeht.
        """
        return _resident_der_protokollgruppe(self, resident)

    def get_resident_name(self, obj):
        return obj.resident.get_full_name()

    def get_resident_picture(self, obj):
        try:
            if obj.resident.picture:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.resident.picture.url)
                return obj.resident.picture.url
        except (AttributeError, TypeError, ValueError):
            pass
        return None


class ProtocolObservationSerializer(serializers.ModelSerializer):
    """Verlaufseintrag - zur Gruppe oder zu einer einzelnen Person."""

    resident_name = serializers.SerializerMethodField()
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )

    class Meta:
        model = ProtocolObservation
        fields = [
            "id",
            "protocol",
            "resident",
            "resident_name",
            "category",
            "category_display",
            "text",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "protocol", "created_at", "updated_at"]

    def validate_resident(self, resident):
        """Wie bei der Teilnahme: kein Verlaufseintrag zu fremden Bewohnern."""
        if resident is None:
            return resident
        return _resident_der_protokollgruppe(self, resident)

    def get_resident_name(self, obj):
        return obj.resident.get_full_name() if obj.resident else None


def _resident_der_protokollgruppe(serializer, resident):
    """
    Prueft, dass ein Bewohner zur Gruppe des Protokolls gehoert.

    Das Protokoll steht in der URL, nicht im Rumpf - das ViewSet legt es als
    `protocol` im Context ab (siehe ProtocolScopedViewSet.get_serializer_context).
    Fehlt es, bleibt als Rueckfallebene die Sichtbarkeit fuer das Konto.
    """
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    protocol = serializer.context.get("protocol")

    if protocol is not None:
        if resident.group_id != protocol.group_id:
            raise serializers.ValidationError(
                "Diese Person gehoert nicht zur Gruppe dieses Protokolls."
            )
        return resident

    if user is not None and getattr(user, "is_authenticated", False):
        if not Resident.objects.for_user(user).filter(id=resident.id).exists():
            raise serializers.ValidationError("Diese Person steht dir nicht offen.")
    return resident
