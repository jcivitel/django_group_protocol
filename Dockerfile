FROM python:3.12-alpine AS builder

RUN apk add --no-cache libgcc mariadb-connector-c pkgconf mariadb-dev \
    postgresql-dev linux-headers

WORKDIR /opt/grpproto/
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY . /opt/grpproto/

FROM builder AS install
WORKDIR /opt/grpproto
ENV VIRTUAL_ENV=/opt/grpproto/venv

RUN python -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --no-cache-dir -r /opt/grpproto/requirements.txt

FROM install

EXPOSE 8000
CMD ["sh", "entry.sh"]
