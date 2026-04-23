from __future__ import annotations

from typing import Sequence

import questionary
from rich.console import Console

from ..config import FMConfig, load_config

console = Console()


class InteractiveSelectionError(RuntimeError):
    """Raised when interactive bench selection cannot proceed."""


def _get_bench_names(config: FMConfig | None = None) -> list[str]:
    cfg = config or load_config()
    if not cfg.benches_dir.exists():
        return []
    return sorted(path.name for path in cfg.benches_dir.iterdir() if path.is_dir())


def select_bench(config: FMConfig | None = None, benches: Sequence[str] | None = None) -> str:
    names = list(benches) if benches is not None else _get_bench_names(config=config)
    if not names:
        raise InteractiveSelectionError("No benches found.")

    selected = questionary.select(
        "Select a bench:",
        choices=names,
        qmark="fm",
    ).ask()
    if not selected:
        raise InteractiveSelectionError("Bench selection cancelled.")
    return selected
