from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from typing import Optional


class DockerCommandError(RuntimeError):
    """Raised when a Docker command fails."""


def run_docker(
    cmd: list[str],
    cwd: Path | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run Docker command with robust error handling."""
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            check=True,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or "Unknown Docker error"
        raise DockerCommandError(f"Failed command: {' '.join(cmd)}\n{details}") from exc


def run_docker_compose(bench_dir: Path, args: list[str], capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return run_docker(["docker", "compose", *args], cwd=bench_dir, capture_output=capture_output)


def compose_up(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["up", "-d"])


def compose_down(bench_dir: Path, remove_volumes: bool = False) -> None:
    args = ["down"]
    if remove_volumes:
        args.append("-v")
    run_docker_compose(bench_dir, args)


def compose_start(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["start"])


def compose_stop(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["stop"])


def compose_restart(bench_dir: Path) -> None:
    run_docker_compose(bench_dir, ["restart"])


def compose_ps(bench_dir: Path) -> str:
    result = run_docker_compose(bench_dir, ["ps"], capture_output=True)
    return result.stdout


def compose_ps_json(bench_dir: Path) -> list[dict]:
    result = run_docker_compose(bench_dir, ["ps", "--format", "json"], capture_output=True)
    raw = result.stdout.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except json.JSONDecodeError:
        # Fallback for line-separated JSON objects.
        rows: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows


def compose_logs(bench_dir: Path, service: Optional[str] = None, lines: int = 100) -> str:
    args = ["logs", "--tail", str(lines)]
    if service:
        args.append(service)
    result = run_docker_compose(bench_dir, args, capture_output=True)
    return result.stdout


def compose_logs_follow(bench_dir: Path, service: Optional[str] = None) -> None:
    args = ["logs", "-f"]
    if service:
        args.append(service)
    run_docker_compose(bench_dir, args, capture_output=False)


def wait_for_service(host: str, port: int, timeout: int = 120) -> None:
    """
    Wait until TCP service is reachable.
    Retries every 2 seconds until timeout.
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError:
            time.sleep(2)
    raise DockerCommandError(f"Service {host}:{port} did not become ready within {timeout}s")


def wait_for_service_in_backend(bench_dir: Path, host: str, port: int, timeout: int = 120) -> None:
    """
    Wait for a service from inside backend container where docker DNS is available.
    """
    script = f"""python - <<'PY'
import socket
import time

host = {host!r}
port = {port}
timeout = {timeout}
deadline = time.time() + timeout

while time.time() < deadline:
    try:
        socket.create_connection((host, port), timeout=2).close()
        raise SystemExit(0)
    except OSError:
        time.sleep(2)

raise SystemExit(f"Service {{host}}:{{port}} did not become ready within {{timeout}}s")
PY"""
    exec_in_backend(bench_dir, script)


def exec_in_backend(bench_dir: Path, command: str) -> None:
    """
    Execute command in backend container.
    Uses sh -lc to preserve quoting and arguments.
    """
    run_docker_compose(bench_dir, ["exec", "-T", "backend", "sh", "-lc", command])


def exec_in_backend_output(bench_dir: Path, command: str) -> str:
    """Execute command in backend container and return stdout."""
    result = run_docker_compose(bench_dir, ["exec", "-T", "backend", "sh", "-lc", command], capture_output=True)
    return result.stdout


def exec_backend_interactive(bench_dir: Path, args: list[str]) -> None:
    """
    Execute an interactive command in backend container with TTY attached.
    """
    run_docker_compose(bench_dir, ["exec", "backend", *args], capture_output=False)


def docker_available() -> bool:
    try:
        run_docker(["docker", "--version"])
        run_docker(["docker", "compose", "version"])
        return True
    except DockerCommandError:
        return False


def docker_network_exists(network_name: str) -> bool:
    try:
        result = run_docker(
            ["docker", "network", "ls", "--filter", f"name=^{network_name}$", "--format", "{{.Name}}"]
        )
        return network_name in result.stdout.splitlines()
    except DockerCommandError:
        return False


def docker_volume_mountpoint(volume_name: str) -> Path | None:
    try:
        result = run_docker(
            ["docker", "volume", "inspect", volume_name, "--format", "{{ .Mountpoint }}"],
            capture_output=True,
        )
    except DockerCommandError:
        return None
    mountpoint = result.stdout.strip()
    if not mountpoint:
        return None
    return Path(mountpoint)
