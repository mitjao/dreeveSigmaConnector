# Stdlib-only connector: no pip dependencies, so a plain slim image suffices.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    SIGMA_CONNECTOR_WATCH_DIR=/watch \
    SIGMA_CONNECTOR_STATE_DIR=/state \
    SIGMA_CONNECTOR_TOKEN_DIR=/tokens

WORKDIR /app
COPY src/ /app/src/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /watch /state /tokens

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["run"]
