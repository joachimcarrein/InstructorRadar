# Build context: this folder (instructor_radar/).
FROM python:3.13-slim

LABEL org.opencontainers.image.title="Instructor Radar" \
      org.opencontainers.image.description="Driving instructor lesson schedule for Home Assistant" \
      org.opencontainers.image.source="https://github.com/joachimcarrein/InstructorRadar" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt
COPY app/ app/

EXPOSE 8099 8100
ENTRYPOINT ["python", "-m", "app"]
