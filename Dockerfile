FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Temporal CLI: runs the Temporal dev server inside the container (state on the persistent disk)
ARG TEMPORAL_VERSION=1.9.1
RUN curl -sSfL "https://temporal.download/cli/archive/v${TEMPORAL_VERSION}?platform=linux&arch=amd64" \
    | tar -xz -C /usr/local/bin temporal && temporal --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY later ./later
COPY static ./static
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
