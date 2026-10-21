FROM python:3.12-slim

# snmpwalk for GPON polling, ssh for the OLT CLI; mysql-client is only needed by
# the DHCP->NetBox MAC sync and is left out to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends snmp openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY web/ web/
COPY config/ config/
COPY knowledge_base/ knowledge_base/
COPY services/ services/
COPY demo/ demo/

RUN useradd --create-home --uid 1000 monitor \
    && mkdir -p /data \
    && chown monitor:monitor /data
USER monitor

# Users, sessions, settings, audit log and caches live here; mount a volume on it.
ENV MONITOR_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

EXPOSE 4455

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4455/api/health', timeout=4)"

CMD ["python", "-m", "src.main"]
