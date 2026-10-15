"""Tests for the JSON state store (restart persistence)."""

from __future__ import annotations

import json

from src.state import HostState, StateStore


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "state.json"

    store = StateStore(path)
    store.set(
        "web",
        HostState(
            is_alive=False,
            since="2026-01-01T00:00:00",
            last_alert_at="2026-01-01T00:00:01",
        ),
    )
    store.save()

    reloaded = StateStore(path)
    record = reloaded.get("web")
    assert record is not None
    assert record.is_alive is False
    assert record.since == "2026-01-01T00:00:00"
    assert record.last_alert_at == "2026-01-01T00:00:01"


def test_missing_file_starts_empty(tmp_path):
    store = StateStore(tmp_path / "does-not-exist.json")
    assert store.get("web") is None


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not valid json", encoding="utf-8")

    store = StateStore(path)  # must not raise
    assert store.get("web") is None


def test_saved_file_is_valid_json(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.set("db", HostState(is_alive=True, since="t"))
    store.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["db"]["is_alive"] is True
    assert data["db"]["since"] == "t"


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    store = StateStore(path)
    store.set("web", HostState())
    store.save()
    assert path.exists()
