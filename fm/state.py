from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".fm" / "state.json"


def _default_state() -> dict[str, Any]:
    return {"benches": {}}


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        save_state(_default_state(), path=path)
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = _default_state()
    if not isinstance(raw, dict) or "benches" not in raw or not isinstance(raw["benches"], dict):
        raw = _default_state()
    return raw


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_bench(name: str, path: Path = STATE_PATH) -> dict[str, Any] | None:
    return load_state(path=path)["benches"].get(name)


def get_all_benches(path: Path = STATE_PATH) -> dict[str, dict[str, Any]]:
    benches = load_state(path=path)["benches"]
    return {str(name): data for name, data in benches.items()}


def upsert_bench(name: str, data: dict[str, Any], path: Path = STATE_PATH) -> None:
    state = load_state(path=path)
    existing = state["benches"].get(name, {})
    merged = {**existing, **data}
    if "created_at" not in merged:
        merged["created_at"] = datetime.now(timezone.utc).isoformat()
    state["benches"][name] = merged
    save_state(state, path=path)


def remove_bench(name: str, path: Path = STATE_PATH) -> None:
    state = load_state(path=path)
    state["benches"].pop(name, None)
    save_state(state, path=path)
