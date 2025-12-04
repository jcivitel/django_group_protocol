# Group Protocol - Django REST API Backend

A lightweight Django REST Framework backend for managing group protocols, residents, and activities. Designed for use with Flutter or any modern API client.

**Status:** [![Maintenance](https://img.shields.io/maintenance/yes/2025)](https://github.com/jcivitel/)

## Features

- **Session-based Authentication** - Secure cookie-based sessions for API clients
- **Group Management** - Create and manage groups with residents
- **Resident Tracking** - Track resident information with move-in/out dates
- **Protocol Management** - Document activities and protocols with items
- **Image Handling** - Rotate and manage resident images
- **Mention Autocomplete** - Get resident suggestions for @mentions in protocols
- **RESTful API** - Complete REST API with proper HTTP status codes

## Quick Start

### Prerequisites

- Python 3.9+
- SQLite (default) or MySQL
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/jcivitel/django_group_protocol.git
cd django_group_protocol

# Install dependencies
pip install -r requirements.txt

# Setup database
python manage.py migrate

# Run development server
python manage.py runserver 0.0.0.0:8000
```

### First-Time Setup via Web Interface

After starting the server, the system will guide you through setup:

1. Open `http://localhost:8000/api/setup/` in your browser
2. Check setup status: `http://localhost:8000/api/setup/status/` (JSON)
3. If not initialized, a setup form will appear
4. Fill in admin credentials and submit to initialize the system
5. System will automatically run migrations and create superuser
6. You'll be redirected to the system info page: `http://localhost:8000/api/info/`

Alternatively, for automated setup:

```bash
# Create admin user manually
python manage.py createsuperuser
```

### Environment Variables

Create a `.env` file in the project root:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
LANGUAGE_CODE=de-de
TIME_ZONE=Europe/Berlin

# Database (SQLite by default)
MAIN_DATABASE_ENGINE=django.db.backends.sqlite3
MAIN_DATABASE_NAME=db.sqlite3

# For MySQL:
# MAIN_DATABASE_ENGINE=django.db.backends.mysql
# MAIN_DATABASE_NAME=group_protocol
# MAIN_DATABASE_USER=root
# MAIN_DATABASE_PASSWD=password
# MAIN_DATABASE_HOST=localhost
# MAIN_DATABASE_PORT=3306

# CORS and security
CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:3000
```

## API Documentation

Complete API documentation is available in [API.md](API.md).

### Quick API Overview

All endpoints require authentication (session cookie) except `/api/v1/auth/login/`, `/api/setup/`, and `/api/info/`.

#### System Setup & Status

```bash
# Check system initialization status
curl http://localhost:8000/api/setup/status/

# Initialize system (create superuser and run migrations)
curl -X POST http://localhost:8000/api/setup/init/ \
  -H "Content-Type: application/json" \
  -d '{
    "username":"admin",
    "email":"admin@example.com",
    "password":"SecurePassword123!",
    "password_confirm":"SecurePassword123!"
  }'

# View system info page
curl http://localhost:8000/api/info/
```

#### Authentication
```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"john_doe","password":"password123"}'

# Logout
curl -X POST http://localhost:8000/api/v1/auth/logout/
```

#### Groups
```bash
# List groups
curl http://localhost:8000/api/v1/group/

# Create group
curl -X POST http://localhost:8000/api/v1/group/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Haus A","address":"Hauptstraße 42","postalcode":"10115","city":"Berlin"}'
```

#### Residents
```bash
# List residents
curl http://localhost:8000/api/v1/resident/

# Create resident
curl -X POST http://localhost:8000/api/v1/resident/ \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Max","last_name":"Mueller","group":1,"moved_in_since":"2024-01-15"}'
```

#### Protocols
```bash
# List protocols
curl http://localhost:8000/api/v1/protocol/

# Create protocol
curl -X POST http://localhost:8000/api/v1/protocol/ \
  -H "Content-Type: application/json" \
  -d '{"group":1,"protocol_date":"2024-12-01"}'
```

## Project Structure

```
django_group_protocol/
├── django_group_protocol/    # Main project settings
│   ├── settings.py           # Django configuration
│   ├── urls.py               # URL routing
│   ├── wsgi.py               # WSGI application
│   └── asgi.py               # ASGI application
├── django_grp_api/           # REST API views and serializers
│   ├── views.py              # API endpoints
│   ├── serializers.py        # DRF serializers
│   └── urls.py               # API URL routing
├── django_grp_backend/       # Core application logic
│   ├── models.py             # Data models
│   ├── admin.py              # Django admin configuration
│   ├── tests.py              # Tests
│   └── migrations/           # Database migrations
├── manage.py                 # Django management script
├── requirements.txt          # Python dependencies
└── API.md                    # Complete API documentation
```

## Database Models

### Group
- `id` - Primary key
- `name` - Group name
- `address` - Street address
- `postalcode` - Postal code
- `city` - City name
- `color` - Color code (hex)
- `group_members` - M2M relation to users

### Resident
- `id` - Primary key
- `first_name` - First name
- `last_name` - Last name
- `moved_in_since` - Move-in date
- `moved_out_since` - Move-out date (nullable)
- `group` - FK to Group
- `picture` - Optional image field

### Protocol
- `id` - Primary key
- `protocol_date` - Date of the protocol
- `group` - FK to Group
- `status` - Status: "draft" or "exported"
- `exported` - Boolean flag
- `date_added` - Creation timestamp

### ProtocolItem
- `id` - Primary key
- `protocol` - FK to Protocol
- `name` - Item name/title
- `value` - Item value/description
- `position` - Sort order

### ProtocolPresence
- `protocol` - FK to Protocol
- `user` - FK to User
- `was_present` - Boolean flag

## Testing

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test django_grp_backend.tests

# Run specific test class
python manage.py test django_grp_backend.tests.GroupTestCase

# Run with verbose output
python manage.py test --verbosity=2
```

## Code Style

This project uses **Black** for code formatting and follows PEP 8 standards.

```bash
# Check code formatting
black django_grp_* --check

# Format code
black django_grp_*

# Run Django checks
python manage.py check
```

## Docker Deployment

Complete Docker setup with MySQL, Redis, and uWSGI is available.

### Quick Docker Start

```bash
# Copy environment file
cp .env.example .env

# Build and start services
docker-compose up -d

# Check logs
docker-compose logs -f django_group_protocol
```

**First-Time Setup via Web Interface:**
1. Open `http://localhost:8000/api/setup/` in your browser
2. Fill in admin credentials in the setup form
3. Click "Initialize System"
4. The system will create the superuser and apply all migrations automatically
5. You'll be redirected to `http://localhost:8000/api/info/`

**Or initialize via API:**
```bash
curl -X POST http://localhost:8000/api/setup/init/ \
  -H "Content-Type: application/json" \
  -d '{
    "username":"admin",
    "email":"admin@example.com",
    "password":"SecurePassword123!",
    "password_confirm":"SecurePassword123!"
  }'
```

### Production Deployment

For production deployment using Docker:

1. Follow the setup in [DOCKER_SETUP.md](DOCKER_SETUP.md)
2. Configure proper environment variables
3. Use Nginx as reverse proxy
4. Enable HTTPS/SSL
5. Set up database backups
6. Monitor container health

### Manual Deployment with uWSGI + Nginx

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --no-input

# Run with uWSGI
uwsgi --ini uwsgi.ini
```

### Environment Configuration

For production, set these environment variables:

```env
DEBUG=False
SECRET_KEY=your-very-secret-key-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
MAIN_DATABASE_ENGINE=django.db.backends.mysql
MAIN_DATABASE_NAME=group_protocol
MAIN_DATABASE_USER=app_user
MAIN_DATABASE_PASSWD=strong-password
MAIN_DATABASE_HOST=db.yourdomain.com
MAIN_DATABASE_PORT=3306
CORS_ALLOWED_ORIGINS=https://yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

## Session Management

- Default session timeout: **1 hour of inactivity**
- Sessions are stored in Django's session framework
- For production, consider using Redis for session storage

Configure in `settings.py`:

```python
SESSION_ENGINE = "django.contrib.sessions.backends.db"  # Default
# or
SESSION_ENGINE = "django.contrib.sessions.backends.cache"  # Redis
```

## Contributing

Contributions are welcome! Please ensure:

1. Code is formatted with Black
2. All tests pass
3. Type hints are used for all functions
4. Docstrings are provided for models and views

## License

[BSD 3-Clause License](LICENSE)

## Support

For issues, questions, or contributions, visit:
[GitHub Repository](https://github.com/jcivitel/django_group_protocol)

## Changelog

### v2.1 (Upcoming)
- **NEW:** Web-based system setup & initialization
- Setup status endpoint for checking system state
- Setup wizard with superuser creation and automatic migrations
- System info page with statistics and documentation links
- Simplified onboarding for first-time deployment (Docker & manual)

### v2.0 (Backend-Only)
- Removed frontend and exporter functionality
- Simplified to API-only backend
- Updated dependencies
- Improved API documentation

### v1.0
- Initial release
- Session-based authentication
- Core CRUD operations
- Protocol management with PDF export
