# AGENTS.md - Django Group Protocol Backend

## Project Setup

**Stack**: Django 5.2.8 + DRF 3.16.1 + MySQL + Celery | **Python**: 3.9+ | **DB**: SQLite/MySQL

```bash
# Database & Setup
python manage.py migrate                    # Run all pending migrations
python manage.py createsuperuser            # Create admin user

# Linting & Validation
black django_grp_* --check                  # Check code formatting
python manage.py check                      # Check Django configuration

# Testing
python manage.py test                       # Run all tests
python manage.py test django_grp_backend.tests     # Run app tests
python manage.py test django_grp_backend.tests.TestClassName    # Single test class
python manage.py test django_grp_backend.tests.TestClassName.test_method_name  # Single test

# Development Server
python manage.py runserver 0.0.0.0:8000    # Start dev server
```

## Code Style Guidelines

**Imports Order**: Standard lib → Django → DRF → Project apps (alphabetically within groups)

**Type Hints**: Required for all function signatures. Example:
```python
def validate_resident(user: User, resident_id: int) -> Resident:
    """Validate user access to resident."""
```

**Naming**: `snake_case` functions/vars, `PascalCase` classes, `_private` prefix for internal.

**Models/Querysets**: Use custom QuerySets for filtering (e.g., `Resident.objects.for_user(user).active()`). Add docstrings to custom QuerySet methods.

**ViewSets/Views**: All endpoints require `IsAuthenticated` by default (settings.py:141–143). Use model `for_user()` QuerySet methods. Inherit from `ModelViewSet` or `ViewSet` in `views.py`.

**Serializers** (serializers.py): Include docstrings. Use `SerializerMethodField` sparingly. Validate in `validate()` or field validators.

**Error Handling**: Catch all exceptions; return appropriate HTTP responses (400, 403, 404, 500). Log errors to stdout for debugging.

**Decorators**: Use `@login_required` (views), `@group_required(group_name)` (custom), `@wraps` (custom decorators).

**Database**: SQLite default (dev), MySQL production. Use transactions for multi-step operations.

**Celery**: Long-running tasks only; keep synchronous for sub-second operations.

## Important Rules for Agents

- **No unsolicited MD files**: Never create README, CHANGELOG, etc. unless explicitly requested
- **No git commands**: Avoid `git clone`, `commit`, `push`, `pull`, etc.
- **Language**: German UI text; code comments in English or German as appropriate
- **Licenses**: BSD 3-Clause applies to both projects
