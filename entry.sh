#!/usr/bin/env sh

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --no-input

# Run database migrations
echo "Running database migrations..."
python manage.py migrate

# Start uWSGI server
echo "Starting uWSGI server..."
/opt/grpproto/venv/bin/uwsgi --ini /opt/grpproto/uwsgi.ini
