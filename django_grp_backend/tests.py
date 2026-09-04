from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django_grp_backend.models import Group, Resident, Protocol, ProtocolItem, ProtocolPresence
from datetime import date


class PermissionTestCase(APITestCase):
    """
    Zugriff ohne Anmeldung wird abgewiesen.

    Erwartet wird 401, nicht 403. Der Unterschied ist keine Kosmetik:

    - **401 Unauthorized** heisst "keine Anmeldedaten dabei" - der Aufrufer
      soll sich anmelden.
    - **403 Forbidden** heisst "angemeldet, aber nicht erlaubt" - erneutes
      Anmelden hilft nicht.

    DRF liefert hier 401, weil in den Einstellungen BasicAuthentication
    konfiguriert ist und damit ein WWW-Authenticate-Kopf existiert. Das
    Frontend haengt daran: ApiError.isUnauthorized prueft auf 401 und
    schickt zur Anmeldung, isForbidden auf 403 und zeigt eine Meldung.
    Wuerde hier 403 kommen, liefe eine abgelaufene Sitzung in eine
    Fehlermeldung statt in die Anmeldemaske.

    Diese Tests standen lange auf 403 und waren entsprechend rot - die
    Erwartung war falsch, nicht die Schnittstelle.
    """
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create test users
        self.user1 = User.objects.create_user(
            username='user1',
            password='testpass123',
            email='user1@test.com'
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='testpass123',
            email='user2@test.com'
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            password='testpass123',
            email='staff@test.com',
            is_staff=True
        )
        
        # Create test groups
        self.group1 = Group.objects.create(
            name='Group 1',
            address='Test Address 1',
            postalcode='12345',
            city='Test City 1'
        )
        self.group1.group_members.add(self.user1)
        
        self.group2 = Group.objects.create(
            name='Group 2',
            address='Test Address 2',
            postalcode='54321',
            city='Test City 2'
        )
        self.group2.group_members.add(self.user2)
        
        # Create test residents
        self.resident1 = Resident.objects.create(
            first_name='John',
            last_name='Doe',
            moved_in_since=date(2020, 1, 1),
            group=self.group1
        )
        
        # Create test protocols
        self.protocol1 = Protocol.objects.create(
            protocol_date=date(2024, 1, 1),
            group=self.group1,
            status='draft'
        )
        
        self.protocol2 = Protocol.objects.create(
            protocol_date=date(2024, 1, 2),
            group=self.group2,
            status='draft'
        )
        
        # Create protocol items
        self.item1 = ProtocolItem.objects.create(
            protocol=self.protocol1,
            name='Item 1',
            position=1,
            value='Test Value'
        )
    
    # ============ LOGIN TESTS ============
    
    def test_login_without_credentials(self):
        """Test login endpoint without credentials."""
        response = self.client.post('/api/v1/auth/login/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_login_with_valid_credentials(self):
        """Test login endpoint with valid credentials."""
        response = self.client.post('/api/v1/auth/login/', {
            'username': 'user1',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
    
    def test_login_with_invalid_credentials(self):
        """Test login endpoint with invalid credentials."""
        response = self.client.post('/api/v1/auth/login/', {
            'username': 'user1',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    # ============ PROTOCOL VIEWSET TESTS ============
    
    def test_protocol_list_unauthenticated(self):
        """Test protocol list without authentication - should return 401."""
        response = self.client.get('/api/v1/protocol/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_protocol_list_authenticated(self):
        """Test protocol list with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/protocol/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_protocol_list_filters_by_group_membership(self):
        """Test that protocol list only shows protocols for user's groups."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/protocol/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # User1 should only see protocol1 (in group1)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.protocol1.id)
    
    def test_protocol_detail_unauthenticated(self):
        """Test protocol detail without authentication - should return 401."""
        response = self.client.get(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_protocol_detail_authenticated(self):
        """Test protocol detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_protocol_create_unauthenticated(self):
        """Test protocol creation without authentication - should return 401."""
        response = self.client.post('/api/v1/protocol/', {
            'protocol_date': '2024-01-15',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_protocol_create_authenticated(self):
        """Test protocol creation with authentication - should return 201."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post('/api/v1/protocol/', {
            'protocol_date': '2024-01-15',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_protocol_update_unauthenticated(self):
        """Test protocol update without authentication - should return 401."""
        response = self.client.put(f'/api/v1/protocol/{self.protocol1.id}/', {
            'protocol_date': '2024-01-20',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_protocol_update_authenticated(self):
        """Test protocol update with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(f'/api/v1/protocol/{self.protocol1.id}/', {
            'protocol_date': '2024-01-20',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_protocol_delete_unauthenticated(self):
        """Test protocol deletion without authentication - should return 401."""
        response = self.client.delete(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_protocol_delete_authenticated(self):
        """Test protocol deletion with authentication - should return 204."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
    
    # ============ GROUP VIEWSET TESTS ============
    
    def test_group_list_unauthenticated(self):
        """Test group list without authentication - should return 401."""
        response = self.client.get('/api/v1/group/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_group_list_authenticated(self):
        """Test group list with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/group/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_group_detail_unauthenticated(self):
        """Test group detail without authentication - should return 401."""
        response = self.client.get(f'/api/v1/group/{self.group1.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_group_detail_authenticated(self):
        """Test group detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/group/{self.group1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ RESIDENT VIEWSET TESTS ============
    
    def test_resident_list_unauthenticated(self):
        """Test resident list without authentication - should return 401."""
        response = self.client.get('/api/v1/resident/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_resident_list_authenticated(self):
        """Test resident list with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/resident/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_resident_detail_unauthenticated(self):
        """Test resident detail without authentication - should return 401."""
        response = self.client.get(f'/api/v1/resident/{self.resident1.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_resident_detail_authenticated(self):
        """Test resident detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/resident/{self.resident1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ PROTOCOL PRESENCE TESTS ============
    
    def test_presence_update_unauthenticated(self):
        """Test presence update without authentication - should return 401."""
        response = self.client.post('/api/v1/presence/', {
            'protocol': self.protocol1.id,
            'user': self.user1.id,
            'was_present': True
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_presence_update_authenticated(self):
        """Test presence update with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post('/api/v1/presence/', {
            'protocol': self.protocol1.id,
            'user': self.user1.id,
            'was_present': True
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ PROTOCOL ITEM TESTS ============
    
    def test_item_update_unauthenticated(self):
        """Test item update without authentication - should return 401."""
        response = self.client.post('/api/v1/item/', {
            'item_id': self.item1.id,
            'protocol': self.protocol1.id,
            'name': 'Updated Item',
            'value': 'Updated Value',
            'position': 1
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_item_update_authenticated(self):
        """Test item update with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post('/api/v1/item/', {
            'item_id': self.item1.id,
            'protocol': self.protocol1.id,
            'name': 'Updated Item',
            'value': 'Updated Value',
            'position': 1
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_item_delete_unauthenticated(self):
        """Test item deletion without authentication - should return 401."""
        response = self.client.delete('/api/v1/item/', {
            'item_id': self.item1.id
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_item_delete_authenticated(self):
        """Test item deletion with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete('/api/v1/item/', {
            'item_id': self.item1.id
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ MENTION AUTOCOMPLETE TESTS ============
    
    def test_mention_autocomplete_unauthenticated(self):
        """Test mention autocomplete without authentication - should return 401."""
        response = self.client.get(f'/api/v1/mentions/?protocol_id={self.protocol1.id}')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_mention_autocomplete_authenticated(self):
        """Test mention autocomplete with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/mentions/?protocol_id={self.protocol1.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ LOGOUT TESTS ============
    
    def test_logout_unauthenticated(self):
        """Test logout without authentication - should return 401."""
        response = self.client.post('/api/v1/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_logout_authenticated(self):
        """Test logout with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post('/api/v1/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ GROUP PARTIAL UPDATE TESTS ============
    
    def test_group_partial_update_with_null_fields(self):
        """Test group partial update - null fields should not overwrite existing values."""
        self.client.force_authenticate(user=self.user1)
        original_address = self.group1.address
        original_city = self.group1.city
        
        # Update only the name, leaving address and city as null
        response = self.client.put(f'/api/v1/group/{self.group1.id}/', {
            'id': self.group1.id,
            'name': 'Updated Group Name'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group1.refresh_from_db()
        self.assertEqual(self.group1.name, 'Updated Group Name')
        self.assertEqual(self.group1.address, original_address)
        self.assertEqual(self.group1.city, original_city)
    
    def test_group_partial_update_only_id_required(self):
        """Test group partial update - only id should be required."""
        self.client.force_authenticate(user=self.user1)
        original_data = {
            'name': self.group1.name,
            'address': self.group1.address,
            'postalcode': self.group1.postalcode,
            'city': self.group1.city,
            'color': self.group1.color
        }
        
        # Update with only id and one field
        response = self.client.put(f'/api/v1/group/{self.group1.id}/', {
            'id': self.group1.id,
            'color': '#ff0000'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group1.refresh_from_db()
        self.assertEqual(self.group1.color, '#ff0000')
        self.assertEqual(self.group1.name, original_data['name'])
        self.assertEqual(self.group1.address, original_data['address'])
    
    def test_group_partial_update_multiple_fields(self):
        """Test group partial update with multiple fields."""
        self.client.force_authenticate(user=self.user1)
        original_postalcode = self.group1.postalcode
        
        # Update name and city only
        response = self.client.put(f'/api/v1/group/{self.group1.id}/', {
            'id': self.group1.id,
            'name': 'New Group Name',
            'city': 'New City'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.group1.refresh_from_db()
        self.assertEqual(self.group1.name, 'New Group Name')
        self.assertEqual(self.group1.city, 'New City')
        self.assertEqual(self.group1.postalcode, original_postalcode)


class FremdeGruppeTestCase(APITestCase):
    """
    Angemeldet, aber fremde Gruppe: was sieht man nicht?

    Diese Faelle waren nirgends festgehalten - die vorhandenen Tests pruefen
    nur den Zugriff ganz ohne Anmeldung. Das ist die haertere Frage: eine
    Fachkraft IST angemeldet und darf trotzdem die Bewohner des Nachbarhauses
    nicht sehen.

    Die Schnittstelle antwortet mit 404 und nicht mit 403 - und das ist die
    bessere Wahl: ein 403 wuerde bestaetigen, dass es den Datensatz gibt.
    Wer die Ids durchprobiert, soll nicht einmal das erfahren.
    """

    def setUp(self):
        self.client = APIClient()
        self.eigene = User.objects.create_user(
            username="eigene", password="testpass123"
        )
        self.fremde = User.objects.create_user(
            username="fremde", password="testpass123"
        )

        self.gruppe_eigen = Group.objects.create(
            name="Eigene Gruppe", address="A", postalcode="11111", city="Hier"
        )
        self.gruppe_fremd = Group.objects.create(
            name="Fremde Gruppe", address="B", postalcode="22222", city="Woanders"
        )
        self.gruppe_eigen.group_members.add(self.eigene)
        self.gruppe_fremd.group_members.add(self.fremde)

        self.protokoll_fremd = Protocol.objects.create(
            protocol_date=date(2024, 5, 1), group=self.gruppe_fremd, status="draft"
        )
        self.bewohner_fremd = Resident.objects.create(
            first_name="Fremd",
            last_name="Kind",
            moved_in_since=date(2020, 1, 1),
            group=self.gruppe_fremd,
        )

        self.client.force_authenticate(user=self.eigene)

    def test_fremdes_protokoll_nicht_lesbar(self):
        antwort = self.client.get(f"/api/v1/protocol/{self.protokoll_fremd.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)

    def test_fremdes_protokoll_nicht_aenderbar(self):
        antwort = self.client.patch(
            f"/api/v1/protocol/{self.protokoll_fremd.id}/", {"status": "ready"}
        )
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)

    def test_fremde_gruppe_nicht_lesbar(self):
        antwort = self.client.get(f"/api/v1/group/{self.gruppe_fremd.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)

    def test_fremder_bewohner_nicht_lesbar(self):
        antwort = self.client.get(f"/api/v1/resident/{self.bewohner_fremd.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)

    def test_liste_zeigt_nur_eigene_gruppe(self):
        antwort = self.client.get("/api/v1/group/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        namen = [eintrag["name"] for eintrag in antwort.data]
        self.assertEqual(namen, ["Eigene Gruppe"])

    def test_protokollliste_enthaelt_kein_fremdes(self):
        antwort = self.client.get("/api/v1/protocol/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        ids = [eintrag["id"] for eintrag in antwort.data]
        self.assertNotIn(self.protokoll_fremd.id, ids)


class AnmeldungTestCase(APITestCase):
    """
    Angemeldet wird sich mit Benutzername oder E-Mail.

    Der interessante Fall ist der mehrdeutige: Djangos User-Modell erzwingt
    keine eindeutige Adresse. Teilen sich zwei Konten eine, darf keines von
    beiden angemeldet werden - sonst koennte, wer die Adresse einer Kollegin
    kennt, sich mit einem eigenen Konto an deren Stelle setzen.
    """

    def setUp(self):
        self.person = User.objects.create_user(
            username="m.mustermann",
            email="M.Mustermann@Beispiel.de",
            password="EinGutesPasswort1",
        )

    def anmelden(self, kennung, passwort="EinGutesPasswort1"):
        return self.client.post(
            "/api/v1/auth/login/",
            {"username": kennung, "password": passwort},
            format="json",
        )

    def test_anmeldung_mit_benutzername(self):
        antwort = self.anmelden("m.mustermann")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertTrue(antwort.data["data"]["token"])

    def test_anmeldung_mit_email(self):
        antwort = self.anmelden("M.Mustermann@Beispiel.de")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertEqual(antwort.data["data"]["user"]["username"], "m.mustermann")

    def test_email_ohne_ruecksicht_auf_grossschreibung(self):
        antwort = self.anmelden("m.mustermann@beispiel.DE")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_falsches_passwort_wird_abgewiesen(self):
        antwort = self.anmelden("m.mustermann", "falsch")
        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unbekannte_adresse_wird_abgewiesen(self):
        antwort = self.anmelden("gibtesnicht@beispiel.de")
        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mehrdeutige_adresse_laesst_niemanden_herein(self):
        User.objects.create_user(
            username="zweitkonto",
            email="m.mustermann@beispiel.de",
            password="EinAnderesPasswort1",
        )
        self.assertEqual(
            self.anmelden("m.mustermann@beispiel.de").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        # Der Benutzername bleibt davon unberuehrt - er ist eindeutig.
        self.assertEqual(self.anmelden("m.mustermann").status_code, status.HTTP_200_OK)

    def test_benutzername_hat_vorrang_vor_fremder_adresse(self):
        """
        Wer ein Konto anlegt, dessen Adresse dem Benutzernamen einer anderen
        Person gleicht, uebernimmt deren Platz nicht.
        """
        User.objects.create_user(
            username="angreifer",
            email="m.mustermann",
            password="EinAnderesPasswort1",
        )
        antwort = self.anmelden("m.mustermann")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertEqual(antwort.data["data"]["user"]["username"], "m.mustermann")

    def test_deaktiviertes_konto_kommt_nicht_herein(self):
        self.person.is_active = False
        self.person.save()
        self.assertEqual(
            self.anmelden("m.mustermann@beispiel.de").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class TabellenEintragTestCase(APITestCase):
    """
    Tabellen ueberleben das Speichern.

    Der Endpunkt schrieb lange nur Name, Wert und Position. `kind` und `data`
    fielen unter den Tisch - und damit die ganze Tabelle: wer aus dem Menue
    eine Aufgabenliste waehlte und speicherte, bekam einen leeren Freitext
    zurueck. Beim Bearbeiten einer bestehenden Tabelle verschwand die
    Aenderung, und die alte Tabelle kam wieder.

    Diese Tests halten beide Richtungen fest, dazu den Fall, dass ein
    aelterer Client die Felder gar nicht kennt - dann darf er eine
    vorhandene Tabelle nicht mitloeschen.
    """

    def setUp(self):
        self.person = User.objects.create_user(
            username="fachkraft", password="EinGutesPasswort1"
        )
        self.gruppe = Group.objects.create(
            name="Wohngruppe", address="Weg 1", postalcode="42651", city="Solingen"
        )
        self.gruppe.group_members.add(self.person)
        self.protokoll = Protocol.objects.create(
            protocol_date=date(2026, 9, 4), group=self.gruppe, status="draft"
        )
        self.client.force_authenticate(user=self.person)

    TABELLE = {
        "columns": ["Aufgabe", "Verantwortung", "Termin"],
        "rows": [["Elterngespräch", "Miriam", "12.09."], ["", "", ""]],
    }

    def test_neue_tabelle_bleibt_eine_tabelle(self):
        antwort = self.client.post(
            "/api/v1/item/",
            {
                "protocol": self.protokoll.id,
                "name": "Aufgaben",
                "position": 0,
                "value": "",
                "kind": "table",
                "data": self.TABELLE,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        eintrag = ProtocolItem.objects.get(protocol=self.protokoll)
        self.assertEqual(eintrag.kind, "table")
        self.assertEqual(eintrag.data, self.TABELLE)

    def test_geaenderte_tabelle_wird_gespeichert(self):
        eintrag = ProtocolItem.objects.create(
            protocol=self.protokoll,
            name="Aufgaben",
            position=0,
            value="",
            kind="table",
            data=self.TABELLE,
        )
        geaendert = {
            "columns": ["Aufgabe", "Verantwortung", "Termin"],
            "rows": [["Elterngespräch", "Miriam", "19.09."]],
        }

        antwort = self.client.post(
            "/api/v1/item/",
            {
                "id": eintrag.id,
                "protocol": self.protokoll.id,
                "name": "Aufgaben",
                "position": 0,
                "value": "",
                "kind": "table",
                "data": geaendert,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        eintrag.refresh_from_db()
        self.assertEqual(eintrag.data, geaendert)

    def test_umbau_zu_freitext_leert_die_tabelle(self):
        """Wer ausdruecklich data=null schickt, meint das auch."""
        eintrag = ProtocolItem.objects.create(
            protocol=self.protokoll,
            name="Aufgaben",
            position=0,
            value="",
            kind="table",
            data=self.TABELLE,
        )

        self.client.post(
            "/api/v1/item/",
            {
                "id": eintrag.id,
                "protocol": self.protokoll.id,
                "name": "Notiz",
                "position": 0,
                "value": "Doch lieber Fließtext.",
                "kind": "text",
                "data": None,
            },
            format="json",
        )

        eintrag.refresh_from_db()
        self.assertEqual(eintrag.kind, "text")
        self.assertIsNone(eintrag.data)
        self.assertEqual(eintrag.value, "Doch lieber Fließtext.")

    def test_alter_client_loescht_keine_tabelle(self):
        """
        Der Flutter-Client kennt kind und data nicht. Schickt er nur Name und
        Wert, darf die vorhandene Tabelle nicht verschwinden.
        """
        eintrag = ProtocolItem.objects.create(
            protocol=self.protokoll,
            name="Aufgaben",
            position=0,
            value="",
            kind="table",
            data=self.TABELLE,
        )

        self.client.post(
            "/api/v1/item/",
            {
                "id": eintrag.id,
                "protocol": self.protokoll.id,
                "name": "Aufgaben neu benannt",
                "position": 1,
                "value": "",
            },
            format="json",
        )

        eintrag.refresh_from_db()
        self.assertEqual(eintrag.name, "Aufgaben neu benannt")
        self.assertEqual(eintrag.kind, "table")
        self.assertEqual(eintrag.data, self.TABELLE)
