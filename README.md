# 🌐 Automated Network Uptime Monitor with Alert System

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-blue)
![Status](https://img.shields.io/badge/Status-MVP%20Working-brightgreen)

A lightweight, self-hosted uptime monitor written in Python. It pings a list of
hosts on a schedule, records **latency** and **packet loss** to disk, and fires
**Email / Telegram alerts** the moment a host goes **DOWN** — plus a recovery
alert when it comes back **UP**.

Designed to run quietly in the background on a Linux box (NOC / home-lab /
VPS) via **cron** or a **systemd** service.

---

## 📖 Overview

Poor man's UptimeRobot, but fully yours. No SaaS, no dashboard lock-in — just a
script you own, a config file, and alerts that reach you where you already are
(Telegram / Email).

**Why it matters:** a NOC + dev combo — the exact "monitoring mindset" that
network operations roles look for, demonstrated in a small, real, deployable tool.

---

## ✨ Features

- 🔁 **Multi-host monitoring** — ping any number of hosts concurrently, each with
  its own interval.
- 📉 **Latency & packet-loss tracking** — records min/avg/max RTT and loss % per round.
- 🗂️ **File logging** — rotating application log + a CSV time-series for later analysis.
- 🚨 **Smart alerting** — Email (SMTP) and Telegram, with **DOWN → UP** state
  tracking so you get *one* alert per incident, not a message every second.
- ⏱️ **Flexible scheduling** — run with `cron` / `systemd timer`, or in-app via `schedule`.
- ⚙️ **Config-driven** — hosts, intervals, thresholds and channels live in `config.yaml`.
- 🔐 **Secrets kept out of git** — all credentials are loaded from `.env`.
- 🧪 **Testable** — clean module layout with `pytest`.

---

## 🧰 Tech Stack

| Layer            | Technology                          |
| ---------------- | ----------------------------------- |
| Language         | Python 3.10+                        |
| ICMP / ping      | [`icmplib`](https://pypi.org/project/icmplib/) |
| HTTP (Telegram)  | `requests`                          |
| Config / secrets | `PyYAML`, `python-dotenv`           |
| Scheduling       | Cron / systemd (or `schedule`)      |
| Alerts           | SMTP (`smtplib`) + Telegram Bot API |
| Output           | `logging`, CSV, `rich`              |
| Tests            | `pytest`                            |
| Platform         | Linux                               |

---

## 🗂️ Project Structure

```
network-uptime-monitor/
├── monitor.py              # entry point: load config -> ping -> log -> alert
├── config.yaml             # hosts, intervals, thresholds, alert toggles
├── .env.example            # template for secrets  (copy to .env)
├── requirements.txt        # pinned Python dependencies
├── src/
│   ├── __init__.py
│   ├── config.py           # load & validate config.yaml + .env
│   ├── pinger.py           # ICMP ping, latency & packet-loss stats
│   ├── logger.py           # rotating log + CSV metrics writer
│   └── alerts.py           # Email (SMTP) & Telegram senders + state tracking
├── tests/                  # pytest unit tests
├── logs/                   # generated logs & metrics (git-ignored)
├── .gitignore
├── LICENSE
└── README.md
```

## 🧩 How It Works (file by file)

| File | Responsibility |
| --- | --- |
| **`monitor.py`** | Entry point / orchestrator. Parses CLI args, loads the config, then in a loop: ping each host → write metrics → raise alerts if state changed. `--once` runs a single cycle (cron-friendly); the default is continuous (systemd). |
| **`src/config.py`** | Reads `config.yaml` + `.env`, merges per-host values over `defaults`, and returns validated dataclasses (`Host`, `LoggingConfig`, `AlertConfig`). |
| **`src/pinger.py`** | Thin wrapper over `icmplib`. Runs the ICMP ping and normalises the result into a `PingResult` (`is_alive`, packet-loss %, min/avg/max RTT, jitter). Falls back to unprivileged mode automatically. |
| **`src/logger.py`** | `setup_logger()` builds a rotating file + console logger; `MetricsWriter` appends one CSV row per ping for the time-series. |
| **`src/alerts.py`** | Telegram & Email channels plus the `AlertManager`, which remembers each host's last state so you get **one** DOWN alert and **one** RECOVERY alert per incident — not a message every second. |
| **`config.yaml`** | What to monitor and how (hosts, intervals, thresholds, channels). |
| **`.env`** | Secrets only (Telegram token, SMTP credentials). Never committed. |

### Flow of a single check

```
monitor.py
└─ config.load_config()               # config.yaml + .env
└─ for each host (respecting its interval):
     ├─ pinger.ping_host()            # icmplib        -> PingResult
     ├─ logger.MetricsWriter.write()  #                -> logs/metrics.csv
     └─ alerts.AlertManager.evaluate()# state change?  -> Telegram / Email
```

### Alert behaviour

- A host must fail **`retries` consecutive rounds** before it is considered DOWN
  (prevents a single lost packet from paging you).
- One **DOWN** alert per outage; one **RECOVERED** alert when it returns
  (disable recovery alerts per host with `alert_recovery: false`).
- A host that is **already down** when the monitor starts still triggers a DOWN
  alert (unknown hosts are assumed UP on first sight).

---

## ✅ Prerequisites

- Linux (tested on Linux Mint / Ubuntu / Debian)
- Python **3.10+**
- `ping` utility (`iputils-ping`)
- `cron` (for scheduled runs)
- Root / `CAP_NET_RAW` for raw ICMP sockets (see note below)

---

## 🚀 Installation

```bash
# 1. Clone
git clone https://github.com/hariomop12/network-uptime-monitor.git
cd network-uptime-monitor

# 2. System packages (Debian / Ubuntu / Mint)
sudo apt update
sudo apt install -y python3 python3-pip python3-venv iputils-ping cron

# 3. Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Python dependencies
pip install -r requirements.txt
```

### 🔑 ICMP permissions (important)

`icmplib` uses raw sockets, which normally need root. Instead of running the
whole script with `sudo`, grant the capability once to the interpreter:

```bash
# Option A: run with sudo
sudo ./.venv/bin/python monitor.py

# Option B (cleaner): grant CAP_NET_RAW to the venv interpreter
sudo setcap cap_net_raw+ep .venv/bin/python3
```

---

## ⚙️ Configuration

### `config.yaml`

Controls **what** is monitored and **how**:

- `defaults` — global interval, timeout, retries, recovery alerts
- `logging` — log directory, rotation size, CSV file name, log level
- `alerts` — enable/disable Email and Telegram channels
- `hosts` — the list of hosts (name + address), each optionally overriding defaults

```yaml
hosts:
  - name: Google DNS
    address: 8.8.8.8
    interval: 30
  - name: Local Gateway
    address: 192.168.1.1
```

### `.env` (secrets)

Never stored in `config.yaml`. Copy the template and fill it in:

```bash
cp .env.example .env
```

| Variable             | Purpose                                  |
| -------------------- | ---------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID`   | Your chat/group id (from `getUpdates`)   |
| `SMTP_HOST` / `SMTP_PORT` | SMTP server for email alerts        |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP login (Gmail → App Password) |
| `ALERT_EMAIL_TO`     | Recipient address for alerts             |

---

## 🔔 Alert Setup

### Telegram

1. Open Telegram → chat with **@BotFather** → `/newbot` → copy the **token**.
2. Put it in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Send your bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`
   into `TELEGRAM_CHAT_ID`.
4. Set `alerts.telegram.enabled: true` in `config.yaml`.

### Email (SMTP)

1. For Gmail: enable 2-Step Verification → **App passwords** → generate one.
2. Fill `SMTP_*` and `ALERT_EMAIL_TO` in `.env`.
3. Set `alerts.email.enabled: true` and `to_addrs` in `config.yaml`.

---

## ▶️ Usage

Raw ICMP needs privileges, so prefix with `sudo` (or use the `setcap` route above):

```bash
source .venv/bin/activate

# Continuous mode — keeps running (good for systemd / manual testing)
sudo ./.venv/bin/python monitor.py

# Single cycle then exit (good for cron)
sudo ./.venv/bin/python monitor.py --once

# Custom config path
sudo ./.venv/bin/python monitor.py --once --config /path/to/config.yaml
```

Outputs land in `logs/`:

- `logs/monitor.log` — human-readable rotating log
- `logs/metrics.csv` — per-round latency / packet-loss time-series

---

## 🔄 Running as a Background Service

### Option A — cron (every minute)

Use `--once` so each cron tick runs exactly one cycle. To avoid needing root in
cron, grant the capability once (see [ICMP permissions](#-icmp-permissions-important)):

```bash
crontab -e
```

```cron
* * * * * cd /home/hariom/project/network-uptime-monitor && ./.venv/bin/python monitor.py --once >> logs/cron.log 2>&1
```

### Option B — systemd service

```ini
# /etc/systemd/system/uptime-monitor.service
[Unit]
Description=Network Uptime Monitor
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/hariom/project/network-uptime-monitor
ExecStart=/home/hariom/project/network-uptime-monitor/.venv/bin/python monitor.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uptime-monitor
```

---

## 🗺️ Roadmap

- [x] Project scaffolding — structure, `config.yaml`, `.env.example`, docs
- [x] Ping engine (`src/pinger.py`) — latency & packet-loss stats
- [x] Logging (`src/logger.py`) — rotating log + CSV metrics
- [x] Alerting (`src/alerts.py`) — Email + Telegram with DOWN/UP state tracking
- [x] Entry point (`monitor.py`) — orchestration + CLI args
- [ ] Unit tests (`pytest`)
- [x] Deployment docs (cron + systemd examples shipped)
- [ ] *Optional* — simple web dashboard / HTML report

---

## 🤝 Contributing

This is a personal portfolio / learning project, but suggestions are welcome —
open an issue or a pull request.

---

## 📄 License

Released under the [MIT License](LICENSE).
