# IT Support Ticket System - Podman Containerfile
# Build with:  podman build -t it-support-tickets:v1.0 .

# Fully qualified base image: avoids Podman's interactive "short-name" prompt.
FROM docker.io/library/python:3.11-slim

LABEL org.opencontainers.image.title="IT Support Ticket System" \
      org.opencontainers.image.description="Flask + SQLite IT help-desk ticket tracker" \
      org.opencontainers.image.version="1.0"

# Unbuffered output makes `podman logs` show log lines immediately.
# DATABASE_PATH is where the app stores its SQLite file (the /data volume).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/tickets.db

WORKDIR /app

# Copy only requirements.txt first so this layer is cached and the
# dependencies are reinstalled only when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code last (it changes most often).
COPY app.py .
COPY templates/ templates/

# Create the data directory, then declare it as a volume for persistent storage.
RUN mkdir -p /data
VOLUME /data

EXPOSE 5000

# app.py listens on 0.0.0.0:5000 so the published port is reachable from the host.
CMD ["python", "app.py"]
