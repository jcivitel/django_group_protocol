# Group Protocol API Documentation

## Base URL

```
https://your-server.com/api/
```

## Authentication

### Token Authentication (Recommended for Mobile Apps)

The API uses **token-based authentication**. After successful login, the server returns an authentication token that must be included in the `Authorization` header for all subsequent requests.

#### Token-Based Authentication Flow:
1. **POST** `/api/v1/auth/login/` with username and password
2. Server returns `token` in response data
3. Store token securely on device (e.g., `flutter_secure_storage`)
4. Include token in `Authorization: Token <token>` header for all API requests
5. **POST** `/api/v1/auth/logout/` to invalidate the token

#### Flutter Implementation Example:

```dart
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class ApiClient {
  final String baseUrl = 'https://your-server.com/api';
  final storage = const FlutterSecureStorage();
  late http.Client _client;

  ApiClient() {
    _client = http.Client();
  }

  // Login and store token
  Future<void> login(String username, String password) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/v1/auth/login/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'password': password,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final token = data['data']['token'];
      await storage.write(key: 'auth_token', value: token);
    } else {
      throw Exception('Login failed');
    }
  }

  // Get stored token
  Future<String?> getToken() async {
    return await storage.read(key: 'auth_token');
  }

  // Make API request with token
  Future<Map<String, dynamic>> _getWithAuth(String endpoint) async {
    final token = await getToken();
    final response = await _client.get(
      Uri.parse('$baseUrl$endpoint'),
      headers: {
        'Authorization': 'Token $token',
        'Content-Type': 'application/json',
      },
    );

    if (response.statusCode == 401) {
      throw Exception('Unauthorized - please login again');
    }

    return jsonDecode(response.body);
  }

  // Logout and remove token
  Future<void> logout() async {
    final token = await getToken();
    await _client.post(
      Uri.parse('$baseUrl/v1/auth/logout/'),
      headers: {
        'Authorization': 'Token $token',
        'Content-Type': 'application/json',
      },
    );
    await storage.delete(key: 'auth_token');
  }
}
```

---

## Endpoints Overview

### Authentication Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/auth/login/` | POST | ❌ | Authenticate and get token |
| `/api/v1/auth/logout/` | POST | ✅ | Invalidate token |

### System Setup & Info Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/setup/status/` | GET | ❌ | Check system initialization status |
| `/api/setup/init/` | POST | ❌ | Initialize system (create superuser & run migrations) |
| `/api/setup/` | GET | ❌ | Smart redirect page (shows setup form or info) |
| `/api/info/` | GET | ❌ | Display system information & API documentation |

### User Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/user/profile/` | GET | ✅ | Get user profile + groups |
| `/api/v1/user/profile/` | PUT | ✅ | Update profile (email, name) |
| `/api/v1/user/me/` | GET | ✅ | Get detailed profile + permissions |

### Admin Endpoints (Staff Only)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/admin/users/` | GET | ✅ | List all users |
| `/api/v1/admin/users/` | POST | ✅ | Create new user |
| `/api/v1/admin/users/{id}/` | GET | ✅ | Get user details |
| `/api/v1/admin/users/{id}/` | PUT | ✅ | Update user |
| `/api/v1/admin/users/{id}/` | DELETE | ✅ | Delete user |
| `/api/v1/admin/users/{id}/groups/` | POST | ✅ | Add user to group |
| `/api/v1/admin/users/{id}/groups/{gid}/` | DELETE | ✅ | Remove from group |
| `/api/v1/admin/users/{id}/permissions/` | GET | ✅ | List permissions |
| `/api/v1/admin/users/{id}/permissions/` | POST | ✅ | Grant permission |
| `/api/v1/admin/users/{id}/permissions/{pid}/` | DELETE | ✅ | Revoke permission |

### Group Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/group/` | GET | ✅ | List accessible groups |
| `/api/v1/group/` | POST | ✅ | Create group (staff only) |
| `/api/v1/group/{id}/` | GET | ✅ | Get group details |
| `/api/v1/group/{id}/` | PUT | ✅ | Update group |
| `/api/v1/group/{id}/` | DELETE | ✅ | Delete group (staff only) |
| `/api/v1/group/{id}/pdf_template/` | POST | ✅ | Upload PDF template |

### Resident Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/resident/` | GET | ✅ | List residents |
| `/api/v1/resident/` | POST | ✅ | Create resident |
| `/api/v1/resident/{id}/` | GET | ✅ | Get resident |
| `/api/v1/resident/{id}/` | PUT | ✅ | Update resident |
| `/api/v1/resident/{id}/` | DELETE | ✅ | Delete resident |
| `/api/v1/resident/{id}/picture/` | GET | ✅ | Get resident picture |

### Protocol Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/protocol/` | GET | ✅ | List protocols |
| `/api/v1/protocol/` | POST | ✅ | Create protocol |
| `/api/v1/protocol/{id}/` | GET | ✅ | Get protocol |
| `/api/v1/protocol/{id}/` | PUT | ✅ | Update protocol |
| `/api/v1/protocol/{id}/` | DELETE | ✅ | Delete protocol |
| `/api/v1/protocol/{id}/presence/` | GET | ✅ | Get presence entries |
| `/api/v1/presence/` | POST | ✅ | Update presence |

### Protocol Item & Utility Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/item/` | POST | ✅ | Create/update item |
| `/api/v1/item/` | DELETE | ✅ | Delete item |
| `/api/v1/mentions/` | GET | ✅ | Get residents for @mention |
| `/api/v1/rotate_image/` | POST | ✅ | Rotate resident image |

---

## Detailed Endpoint Documentation

### Authentication

#### POST `/api/v1/auth/login/`

**Purpose:** Authenticate user and get token

**Request:**
```json
{
  "username": "john_doe",
  "password": "password123"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "token": "abc123def456...",
    "user": {
      "id": 1,
      "username": "john_doe",
      "email": "john@example.com",
      "first_name": "John",
      "last_name": "Doe"
    }
  }
}
```

**Error (401 Unauthorized):**
```json
{
  "success": false,
  "error": "Invalid username or password"
}
```

---

#### POST `/api/v1/auth/logout/`

**Purpose:** Invalidate token

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

### System Setup & Initialization

#### GET `/api/setup/status/`

**Purpose:** Check system initialization status (useful for onboarding screens)

**Access Control:** Public (no authentication required)

**Response (200 OK) - Not Initialized:**
```json
{
  "is_initialized": false,
  "superuser_exists": false,
  "migrations_pending": false,
  "pending_migrations": [],
  "status": "not_initialized"
}
```

**Response (200 OK) - Migrations Pending:**
```json
{
  "is_initialized": false,
  "superuser_exists": true,
  "migrations_pending": true,
  "pending_migrations": ["django_grp_backend.0016_userpermission"],
  "status": "needs_migration"
}
```

**Response (200 OK) - Ready:**
```json
{
  "is_initialized": true,
  "superuser_exists": true,
  "migrations_pending": false,
  "pending_migrations": [],
  "status": "ready"
}
```

**Error (500 Internal Server Error):**
```json
{
  "error": "Error message description",
  "status": "error"
}
```

---

#### POST `/api/setup/init/`

**Purpose:** Initialize system by creating superuser and running all pending migrations

**Access Control:** Public (only works if no superuser exists yet)

**Request:**
```json
{
  "username": "admin",
  "email": "admin@example.com",
  "password": "SecurePassword123!",
  "password_confirm": "SecurePassword123!"
}
```

**Validation Rules:**
- `username`: Required, must not exist in system
- `email`: Required, valid email format, must not exist in system
- `password`: Required, minimum 8 characters
- `password_confirm`: Must match `password` exactly

**Response (201 Created) - Success:**
```json
{
  "success": true,
  "message": "System initialized successfully. Superuser created and migrations applied.",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "is_staff": true,
    "is_superuser": true
  }
}
```

**Error (400 Bad Request) - Validation Failed:**
```json
{
  "error": "Password must be at least 8 characters long."
}
```

**Error (403 Forbidden) - Already Initialized:**
```json
{
  "error": "System already initialized. Superuser already exists."
}
```

**Error (500 Internal Server Error) - Migration Failed:**
```json
{
  "error": "Migration failed: [error details]"
}
```

---

#### GET `/api/setup/`

**Purpose:** Smart redirect page that shows setup form or system info based on status

**Access Control:** Public (no authentication required)

**Behavior:**
- If superuser does **not** exist OR migrations are pending → Displays `setup_wizard.html` with form
- If superuser exists AND all migrations applied → Displays `info.html` with system information

**Response (200 OK):**
- HTML page (template-based response, not JSON)

**Frontend Flow:**
1. User loads `/api/setup/` on first visit
2. If system not initialized, shows setup form
3. Form submits to `/api/setup/init/` endpoint
4. On success, frontend redirects to `/api/info/` or `/admin/`

---

#### GET `/api/info/`

**Purpose:** Display system information and API documentation in HTML

**Access Control:** Public (no authentication required)

**Response (200 OK):**
- HTML page with system status, statistics, and quick links
- Contains:
  - System initialization status badges
  - Database statistics (users, groups, residents, protocols)
  - Quick navigation links to API, Admin panel, and documentation
  - Table of main API endpoints with method indicators
  - Admin functions section
  - Links to GitHub repository and API documentation

**Frontend Features:**
- Responsive design (mobile & desktop)
- Green/red status badges
- Direct links to:
  - `/admin/` - Django admin panel
  - `/api/v1/` - API root (if authenticated)
  - Repository documentation

---

### User Profile

#### GET `/api/v1/user/profile/`

**Purpose:** Get authenticated user's profile

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_staff": false,
  "is_superuser": false,
  "date_joined": "2024-01-15T10:30:00Z",
  "groups": ["Wohngruppe A", "Wohngruppe B"]
}
```

---

#### PUT `/api/v1/user/profile/`

**Purpose:** Update user profile

**Request:**
```json
{
  "email": "newemail@example.com",
  "first_name": "Jane",
  "last_name": "Smith"
}
```

**Response (200 OK):** Same as GET

---

#### GET `/api/v1/user/me/`

**Purpose:** Get detailed user profile with group permissions

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_staff": false,
  "is_superuser": false,
  "date_joined": "2024-01-15T10:30:00Z",
  "groups_with_permissions": [
    {
      "id": 1,
      "name": "Wohngruppe A",
      "address": "Hauptstr. 123",
      "postalcode": "12345",
      "city": "Berlin",
      "resident_count": 8,
      "permissions": {
        "is_member": true,
        "is_staff": false,
        "can_view": true,
        "can_edit": true,
        "can_delete": false
      }
    }
  ]
}
```

---

### Admin User Management

#### GET `/api/v1/admin/users/`

**Purpose:** List all users (staff only)

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_staff": false,
    "is_superuser": false,
    "is_active": true,
    "date_joined": "2024-01-15T10:30:00Z",
    "groups": [{"id": 1, "name": "Wohngruppe A"}],
    "permissions": []
  }
]
```

**Error (403 Forbidden):**
```json
{
  "error": "Sie haben keine Berechtigung, um diese Seite zu sehen."
}
```

---

#### POST `/api/v1/admin/users/`

**Purpose:** Create new user (staff only)

**Request:**
```json
{
  "username": "new_user",
  "email": "user@example.com",
  "first_name": "Max",
  "last_name": "Mustermann",
  "password": "secure_pass_123",
  "is_staff": false
}
```

**Response (201 Created):**
```json
{
  "id": 15,
  "username": "new_user",
  "email": "user@example.com",
  "first_name": "Max",
  "last_name": "Mustermann",
  "is_staff": false,
  "is_superuser": false,
  "is_active": true,
  "date_joined": "2024-12-04T15:30:00Z",
  "groups": [],
  "permissions": []
}
```

---

#### GET `/api/v1/admin/users/{id}/`

**Purpose:** Get user details (staff only)

**Response (200 OK):** User object (same as POST response)

---

#### PUT `/api/v1/admin/users/{id}/`

**Purpose:** Update user (staff only)

**Request:**
```json
{
  "email": "newemail@example.com",
  "first_name": "Jane",
  "password": "new_password_123",
  "is_active": true
}
```

**Response (200 OK):** Updated user object

---

#### DELETE `/api/v1/admin/users/{id}/`

**Purpose:** Delete user (staff only)

**Response (204 No Content):** Empty

---

#### POST `/api/v1/admin/users/{id}/groups/`

**Purpose:** Add user to group (staff only)

**Request:**
```json
{
  "group_id": 1
}
```

**Response (200 OK):** Updated user object

---

#### DELETE `/api/v1/admin/users/{id}/groups/{group_id}/`

**Purpose:** Remove user from group (staff only)

**Response (200 OK):** Updated user object

---

#### GET `/api/v1/admin/users/{id}/permissions/`

**Purpose:** List user permissions (staff only)

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "user": 1,
    "group": 1,
    "resource": "resident",
    "resource_display": "Bewohner",
    "permission": "read",
    "permission_display": "Lesezugriff",
    "created_at": "2024-12-01T10:00:00Z"
  }
]
```

---

#### POST `/api/v1/admin/users/{id}/permissions/`

**Purpose:** Grant permission (staff only)

**Request:**
```json
{
  "group_id": 1,
  "resource": "resident",
  "permission": "read"
}
```

**Parameters:**
- `group_id`: Group ID
- `resource`: `resident`, `protocol`, or `group`
- `permission`: `read`, `write`, or `delete`

**Response (201 Created):**
```json
{
  "id": 1,
  "user": 1,
  "group": 1,
  "resource": "resident",
  "resource_display": "Bewohner",
  "permission": "read",
  "permission_display": "Lesezugriff",
  "created_at": "2024-12-04T15:30:00Z"
}
```

---

#### DELETE `/api/v1/admin/users/{id}/permissions/{perm_id}/`

**Purpose:** Revoke permission (staff only)

**Response (204 No Content):** Empty

---

### Groups

#### GET `/api/v1/group/`

**Purpose:** List accessible groups

**Response (200 OK):**
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Wohngruppe A",
      "address": "Hauptstr. 123",
      "postalcode": "12345",
      "city": "Berlin",
      "members": [
        {
          "id": 10,
          "first_name": "Max",
          "last_name": "Mueller",
          "moved_in_since": "2024-01-15",
          "moved_out_since": null,
          "group": 1,
          "picture": "https://..."
        }
      ],
      "pdf_template": null,
      "color": "#ffffff"
    }
  ]
}
```

---

#### POST `/api/v1/group/`

**Purpose:** Create group (staff only)

**Request:**
```json
{
  "name": "Wohngruppe B",
  "address": "Nebenstr. 456",
  "postalcode": "10116",
  "city": "Berlin",
  "color": "#ff0000"
}
```

**Response (201 Created):** Group object

---

#### GET `/api/v1/group/{id}/`

**Purpose:** Get group details

**Response (200 OK):** Group object (same as list)

---

#### PUT `/api/v1/group/{id}/`

**Purpose:** Update group

**Request:**
```json
{
  "name": "Wohngruppe A - Updated",
  "address": "Neuestr. 789"
}
```

**Response (200 OK):** Updated group object

---

#### DELETE `/api/v1/group/{id}/`

**Purpose:** Delete group (staff only)

**Response (204 No Content):** Empty

---

#### POST `/api/v1/group/{id}/pdf_template/`

**Purpose:** Upload PDF template

**Request:** `multipart/form-data`
- `pdf_template`: PDF file

**Response (200 OK):**
```json
{
  "success": true,
  "message": "PDF template updated",
  "group_id": 1,
  "template_url": "https://..."
}
```

---

### Residents

#### GET `/api/v1/resident/`

**Purpose:** List accessible residents

**Response (200 OK):**
```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 10,
      "first_name": "Max",
      "last_name": "Mueller",
      "moved_in_since": "2024-01-15",
      "moved_out_since": null,
      "group": 1,
      "picture": "https://..."
    }
  ]
}
```

---

#### POST `/api/v1/resident/`

**Purpose:** Create resident

**Request:**
```json
{
  "first_name": "Peter",
  "last_name": "Wagner",
  "moved_in_since": "2024-03-01",
  "group": 1
}
```

**Response (201 Created):** Resident object

---

#### GET `/api/v1/resident/{id}/`

**Purpose:** Get resident details

**Response (200 OK):** Resident object

---

#### PUT `/api/v1/resident/{id}/`

**Purpose:** Update resident

**Request:**
```json
{
  "moved_out_since": "2024-12-31"
}
```

**Response (200 OK):** Updated resident object

---

#### DELETE `/api/v1/resident/{id}/`

**Purpose:** Delete resident

**Response (204 No Content):** Empty

---

#### GET `/api/v1/resident/{id}/picture/`

**Purpose:** Get resident picture

**Response (200 OK):**
```json
{
  "id": 10,
  "name": "Max Mueller",
  "picture_url": "https://..."
}
```

---

### Protocols

#### GET `/api/v1/protocol/`

**Purpose:** List accessible protocols

**Response (200 OK):**
```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "protocol_date": "2024-12-01",
      "group": 1,
      "status": "draft",
      "exported": false,
      "items": [
        {
          "id": 1,
          "name": "Aktivität",
          "position": 1,
          "value": "Spaziergang"
        }
      ]
    }
  ]
}
```

---

#### POST `/api/v1/protocol/`

**Purpose:** Create protocol

**Request:**
```json
{
  "protocol_date": "2024-12-15",
  "group": 1
}
```

**Response (201 Created):** Protocol object

---

#### GET `/api/v1/protocol/{id}/`

**Purpose:** Get protocol details

**Response (200 OK):** Protocol object (same as list)

---

#### PUT `/api/v1/protocol/{id}/`

**Purpose:** Update protocol

**Request:**
```json
{
  "protocol_date": "2024-12-16",
  "status": "ready"
}
```

**Response (200 OK):** Updated protocol object

**Error (403 Forbidden - if exported):**
```json
{
  "error": "Exportierte Protokolle können nicht bearbeitet werden."
}
```

---

#### DELETE `/api/v1/protocol/{id}/`

**Purpose:** Delete protocol

**Response (204 No Content):** Empty

---

#### GET `/api/v1/protocol/{id}/presence/`

**Purpose:** Get presence entries for protocol

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "protocol": 1,
    "user": 5,
    "user_name": "Max Mustermann",
    "was_present": true
  },
  {
    "id": 2,
    "protocol": 1,
    "user": 6,
    "user_name": "Anna Schmidt",
    "was_present": false
  }
]
```

---

#### POST `/api/v1/presence/`

**Purpose:** Update presence entry

**Request:**
```json
{
  "protocol": 1,
  "user": 5,
  "was_present": true
}
```

**Response (200 OK):**
```json
{
  "message": "Presence created",
  "created": true
}
```

---

### Protocol Items

#### POST `/api/v1/item/`

**Purpose:** Create or update protocol item

**Request:**
```json
{
  "id": "",
  "protocol": 1,
  "name": "Aktivität",
  "position": 1,
  "value": "Spaziergang im Park"
}
```

**Response (200 OK):**
```json
{
  "message": "Item created"
}
```

**Note:** Set `id` to empty string to create, provide `id` to update

---

#### DELETE `/api/v1/item/`

**Purpose:** Delete protocol item

**Request:**
```json
{
  "item_id": 42
}
```

**Response (200 OK):**
```json
{
  "message": "Item deleted"
}
```

---

### Utilities

#### GET `/api/v1/mentions/?protocol_id={id}`

**Purpose:** Get residents for @mention autocomplete

**Response (200 OK):**
```json
[
  {
    "id": 10,
    "name": "Max Mueller",
    "mention": "Max_Mueller"
  },
  {
    "id": 11,
    "name": "Anna Schmidt",
    "mention": "Anna_Schmidt"
  }
]
```

---

#### POST `/api/v1/rotate_image/`

**Purpose:** Rotate resident image

**Request:**
```json
{
  "direction": "left",
  "image_url": "/media/images/abc123.jpg"
}
```

**Parameters:**
- `direction`: `left` (90°) or `right` (-90°)
- `image_url`: Full media path

**Response (200 OK):**
```json
{
  "success": true,
  "new_image_url": "/media/images/abc123.jpg"
}
```

---

## Error Handling

### Common HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Server Error |

### Standard Error Response

```json
{
  "error": "Error message description"
}
```

---

## Pagination

List endpoints support pagination:

**Query Parameters:**
- `page` (int, default: 1)
- `limit` (int, default: 20)

**Response Format:**
```json
{
  "count": 100,
  "next": "https://api.example.com/api/v1/protocol/?page=2",
  "previous": null,
  "results": [...]
}
```

---

## Access Control

### Permission Levels

**Staff Users** (`is_staff == true`):
- Full access to all endpoints
- Can manage users and permissions

**Group Members:**
- Access to groups they're assigned to
- Access to residents in their groups
- Access to protocols in their groups

**Non-Members:**
- Limited or no access (403 Forbidden)

### Permission Matrix

| Resource | Staff | Group Member | Non-Member |
|----------|-------|--------------|-----------|
| Groups | ✅ All | ✅ Own | ❌ 403 |
| Residents | ✅ All | ✅ Own group | ❌ 403 |
| Protocols | ✅ All | ✅ Own group | ❌ 403 |
| Admin Users | ✅ All | ❌ 403 | ❌ 403 |

---

## Changelog

### v1.6 (2025)
- **NEW:** System Setup & Initialization API
- Setup status endpoint for checking initialization state
- Setup wizard endpoint for creating superuser and running migrations
- Smart redirect page showing setup form or system info
- System info page with statistics and quick links
- Simplified onboarding flow for first-time deployment

### v1.5 (2025)
- **NEW:** Complete Admin API for user management
- User creation, update, deletion endpoints
- Group membership management
- Fine-grained resource permissions (read/write/delete)
- New `UserPermission` model for per-resource access control

### v1.4 (2025)
- Admin dashboard endpoints
- User and permission management

### v1.3 (2025)
- PDF template upload endpoint
- Protocol presence listing
- Enhanced access control

### v1.2 (2025)
- Session → Token Authentication (breaking change)
- User profile with detailed permissions endpoint
- Flutter secure storage recommendations

### v1.1 (2024)
- User profile endpoints (GET/PUT)
- Resident picture endpoint
- Group membership listing

### v1.0 (2024)
- Initial API release
- Session-based authentication
- CRUD operations
- Image manipulation and mentions
