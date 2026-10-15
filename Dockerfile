# Network Uptime Monitor - container image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# `ping`/ICMP support is provided by the host kernel; iputils is handy for
# manual debugging inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ICMP needs the NET_RAW capability at runtime:
#   docker run --cap-add=NET_RAW ...
CMD ["python", "monitor.py"]
