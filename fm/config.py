from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".fm" / "config.yaml"


@dataclass(slots=True)
class FMConfig:
    benches_dir: Path
    docker_network: str
    certresolver: str
    db_root_password: str
    admin_password: str | None
    erpnext_image: str
    mariadb_image: str
    redis_image: str
    write_log_file: bool
    log_file: Path


def _default_data() -> dict[str, Any]:
    return {
        "paths": {"benches_dir": "benches"},
        "docker": {"network": "web"},
        "erpnext": {
            "images": {
                "erpnext": "frappe/erpnext:v16",
                "mariadb": "mariadb:10.6",
                "redis": "redis:7-alpine",
            },
            "certresolver": "le",
        },
        "defaults": {"db_root_password": None, "admin_password": None},
        "logging": {"write_file": False, "file": "~/.fm/fm.log"},
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _ensure_config_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_default_data(), sort_keys=False), encoding="utf-8")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> FMConfig:
    _ensure_config_file(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _deep_merge(_default_data(), raw)

    benches_dir = Path(str(data["paths"]["benches_dir"])).expanduser()
    log_file = Path(str(data["logging"]["file"])).expanduser()
    return FMConfig(
        benches_dir=benches_dir,
        docker_network=str(data["docker"]["network"]),
        certresolver=str(data["erpnext"]["certresolver"]),
        db_root_password=str(data["defaults"]["db_root_password"] or ""),
        admin_password=(str(data["defaults"]["admin_password"]) if data["defaults"]["admin_password"] else None),
        erpnext_image=str(data["erpnext"]["images"]["erpnext"]),
        mariadb_image=str(data["erpnext"]["images"]["mariadb"]),
        redis_image=str(data["erpnext"]["images"]["redis"]),
        write_log_file=bool(data["logging"]["write_file"]),
        log_file=log_file,
    )
