"""Persist per-host state between runs.

Without this, restarting the monitor forgets which hosts were already down, so
a restart would re-send DOWN alerts for every down host. State is stored as a
small JSON file and written atomically.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class HostState:
    """Last known state of a single host."""

    is_alive: bool = True
    since: str = ""          # ISO time the current state began
    last_alert_at: str = ""  # ISO time of the last alert sent for this host


class StateStore:
    """A JSON-backed ``host name -> HostState`` map."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._states: dict[str, HostState] = {}
        self.load()

    def load(self) -> None:
        """Read the state file if it exists; ignore a missing/corrupt file."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read state file %s: %s", self.path, exc)
            return

        for name, record in (data or {}).items():
            self._states[name] = HostState(
                is_alive=bool(record.get("is_alive", True)),
                since=str(record.get("since", "")),
                last_alert_at=str(record.get("last_alert_at", "")),
            )

    def get(self, name: str) -> HostState | None:
        return self._states.get(name)

    def set(self, name: str, state: HostState) -> None:
        self._states[name] = state

    def save(self) -> None:
        """Write the whole map to disk atomically (temp file + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: asdict(state) for name, state in self._states.items()}

        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)
