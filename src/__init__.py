"""Network Uptime Monitor - core package.

Modules
-------
config  : load & validate ``config.yaml`` + ``.env``
pinger  : ICMP ping wrapper (latency / packet-loss stats)
logger  : rotating application log + CSV metrics writer
alerts  : Email / Telegram alert channels with DOWN->UP state tracking
"""

__version__ = "0.1.0"
