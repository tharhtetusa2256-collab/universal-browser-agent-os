FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN useradd --create-home --uid 10001 uba

WORKDIR /app
COPY . /app

RUN python -m pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && mkdir -p \
        /app/artifacts \
        /app/results \
        /app/reports/generated \
        /app/service-data \
    && chown -R uba:uba \
        /app/artifacts \
        /app/results \
        /app/reports/generated \
        /app/service-data \
        /ms-playwright

USER uba

EXPOSE 8000
CMD ["uba-api"]
