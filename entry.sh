#!/usr/bin/env sh
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py migrate
/opt/grpproto/venv/bin/uwsgi --ini /opt/grpproto/uwsgi.ini