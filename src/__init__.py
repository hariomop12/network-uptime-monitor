"""Network Uptime Monitor - core package.

Modules
-------
config  : load & validate ``config.yaml`` + ``.env``
checks  : host checks - ICMP ping, TCP port and HTTP(S)
logger  : rotating application log + CSV metrics writer
state   : JSON state store (survives restarts)
alerts  : Email / Telegram alert channels with DOWN->UP state tracking
"""

__version__ = "0.1.0"
