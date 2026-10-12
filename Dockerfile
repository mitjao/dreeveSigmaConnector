# Only pip dependency is cronsim (pure Python), so a plain slim image suffices.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    SIGMA_CONNECTOR_WATCH_DIR=/watch \
    SIGMA_CONNECTOR_STATE_DIR=/state \
    SIGMA_CONNECTOR_TOKEN_DIR=/tokens

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src/ /app/src/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
# tzdata so TZ (e.g. Europe/Berlin) applies to SIGMA_CONNECTOR_SCHEDULE
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /watch /state /tokens

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["run"]
