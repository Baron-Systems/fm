from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional


class DockerCommandError(RuntimeError):
    """Raised when a Docker command fails."""


def run_docker_compose(
    bench_dir: Path,
    args: list[str],
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a docker compose command in a bench directory."""
    command = ["docker", "compose", *args]
    result = subprocess.run(
        command,
        cwd=bench_dir,
        text=True,
        capture_output=capture_output,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or "Unknown Docker error"
        raise DockerCommandError(f"Failed command: {' '.join(command)}\n{details}")
    return result


def compose_up(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["up", "-d"])


def compose_down(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["down"])


def compose_start(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["start"])


def compose_stop(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["stop"])


def compose_restart(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["restart"])


def compose_ps(bench_dir: Path) -> str:
    result = run_docker_compose(bench_dir, ["ps"], capture_output=True)
    return result.stdout


def compose_logs(bench_dir: Path, service: Optional[str] = None, lines: int = 100) -> str:
    args = ["logs", "--tail", str(lines)]
    if service:
        args.append(service)
    result = run_docker_compose(bench_dir, args, capture_output=True)
    return result.stdout


def wait_for_services(seconds: int = 12) -> None:
    """
    Basic wait strategy for containers to initialize.
    A production-grade system would probe specific health endpoints.
    """
    time.sleep(seconds)


def exec_in_backend(bench_dir: Path, command: str) -> None:
    """
    Execute command in backend container.
    Uses sh -lc to preserve quoting and arguments.
    """
    run_docker_compose(bench_dir, ["exec", "-T", "backend", "sh", "-lc", command])


def exec_backend_interactive(bench_dir: Path, args: list[str]) -> None:
    """
    Execute an interactive command in backend container with TTY attached.
    """
    run_docker_compose(bench_dir, ["exec", "backend", *args], capture_output=False)
