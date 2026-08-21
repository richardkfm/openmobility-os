# syntax=docker/dockerfile:1.6

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      binutils \
      libproj-dev \
      gdal-bin \
      libgdal-dev \
      gettext \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

RUN mkdir -p /app/staticfiles /app/mediafiles

ENV PYTHONPATH=/app/backend \
    DJANGO_SETTINGS_MODULE=config.settings.production

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# --timeout: a sync worker is held for the whole of a response, transmission
# included, so a large layer going to a client on a slow link occupies it
# for the duration. At gunicorn's 30 s default those workers were being
# killed mid-send and the browser saw a broken transfer.
# --threads: lets one worker serve several such slow reads at once instead
# of the whole site stalling behind three of them.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "4", "--timeout", "120", \
     "--graceful-timeout", "30", "--access-logfile", "-"]
