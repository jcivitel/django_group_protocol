from django.test import TestCase, Client
from django.contrib.auth.models import User
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django_grp_backend.models import Group, Resident, Protocol, ProtocolItem, ProtocolPresence
from datetime import date


class PermissionTestCase(APITestCase):
    """Test cases for 403 Forbidden errors in API endpoints."""
    
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
        """Test protocol list without authentication - should return 403."""
        response = self.client.get('/api/v1/protocol/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
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
        """Test protocol detail without authentication - should return 403."""
        response = self.client.get(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_protocol_detail_authenticated(self):
        """Test protocol detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_protocol_create_unauthenticated(self):
        """Test protocol creation without authentication - should return 403."""
        response = self.client.post('/api/v1/protocol/', {
            'protocol_date': '2024-01-15',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_protocol_create_authenticated(self):
        """Test protocol creation with authentication - should return 201."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post('/api/v1/protocol/', {
            'protocol_date': '2024-01-15',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_protocol_update_unauthenticated(self):
        """Test protocol update without authentication - should return 403."""
        response = self.client.put(f'/api/v1/protocol/{self.protocol1.id}/', {
            'protocol_date': '2024-01-20',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_protocol_update_authenticated(self):
        """Test protocol update with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(f'/api/v1/protocol/{self.protocol1.id}/', {
            'protocol_date': '2024-01-20',
            'group': self.group1.id
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_protocol_delete_unauthenticated(self):
        """Test protocol deletion without authentication - should return 403."""
        response = self.client.delete(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_protocol_delete_authenticated(self):
        """Test protocol deletion with authentication - should return 204."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete(f'/api/v1/protocol/{self.protocol1.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
    
    # ============ GROUP VIEWSET TESTS ============
    
    def test_group_list_unauthenticated(self):
        """Test group list without authentication - should return 403."""
        response = self.client.get('/api/v1/group/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_group_list_authenticated(self):
        """Test group list with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/group/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_group_detail_unauthenticated(self):
        """Test group detail without authentication - should return 403."""
        response = self.client.get(f'/api/v1/group/{self.group1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_group_detail_authenticated(self):
        """Test group detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/group/{self.group1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ RESIDENT VIEWSET TESTS ============
    
    def test_resident_list_unauthenticated(self):
        """Test resident list without authentication - should return 403."""
        response = self.client.get('/api/v1/resident/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_resident_list_authenticated(self):
        """Test resident list with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/v1/resident/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_resident_detail_unauthenticated(self):
        """Test resident detail without authentication - should return 403."""
        response = self.client.get(f'/api/v1/resident/{self.resident1.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_resident_detail_authenticated(self):
        """Test resident detail with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/resident/{self.resident1.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ PROTOCOL PRESENCE TESTS ============
    
    def test_presence_update_unauthenticated(self):
        """Test presence update without authentication - should return 403."""
        response = self.client.post('/api/v1/presence/', {
            'protocol': self.protocol1.id,
            'user': self.user1.id,
            'was_present': True
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
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
        """Test item update without authentication - should return 403."""
        response = self.client.post('/api/v1/item/', {
            'item_id': self.item1.id,
            'protocol': self.protocol1.id,
            'name': 'Updated Item',
            'value': 'Updated Value',
            'position': 1
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
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
        """Test item deletion without authentication - should return 403."""
        response = self.client.delete('/api/v1/item/', {
            'item_id': self.item1.id
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_item_delete_authenticated(self):
        """Test item deletion with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete('/api/v1/item/', {
            'item_id': self.item1.id
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ MENTION AUTOCOMPLETE TESTS ============
    
    def test_mention_autocomplete_unauthenticated(self):
        """Test mention autocomplete without authentication - should return 403."""
        response = self.client.get(f'/api/v1/mentions/?protocol_id={self.protocol1.id}')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_mention_autocomplete_authenticated(self):
        """Test mention autocomplete with authentication - should return 200."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/v1/mentions/?protocol_id={self.protocol1.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    # ============ LOGOUT TESTS ============
    
    def test_logout_unauthenticated(self):
        """Test logout without authentication - should return 403."""
        response = self.client.post('/api/v1/auth/logout/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
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
