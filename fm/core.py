from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import docker

BENCHES_DIR = Path("benches")
TEMPLATES_DIR = Path(__file__).parent / "templates"
COMPOSE_FILE_NAME = "docker-compose.yml"


class BenchError(RuntimeError):
    """Raised when a bench operation fails."""


def _bench_path(name: str) -> Path:
    return BENCHES_DIR / name


def bench_exists(name: str) -> bool:
    return _bench_path(name).exists()


def ensure_bench_missing(name: str) -> None:
    if bench_exists(name):
        raise BenchError(f"Bench '{name}' already exists.")


def ensure_bench_exists(name: str) -> Path:
    path = _bench_path(name)
    if not path.exists():
        raise BenchError(f"Bench '{name}' does not exist.")
    return path


def _render_compose(name: str, domain: str, site_name: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("docker-compose.yml.j2")
    return template.render(NAME=name, DOMAIN=domain, SITE_NAME=site_name)


def create_bench(name: str, domain: str) -> Path:
    ensure_bench_missing(name)
    bench_dir = _bench_path(name)
    bench_dir.mkdir(parents=True, exist_ok=False)

    compose_content = _render_compose(name=name, domain=domain, site_name=domain)
    compose_path = bench_dir / COMPOSE_FILE_NAME
    compose_path.write_text(compose_content, encoding="utf-8")

    docker.compose_up(bench_dir)
    docker.wait_for_services()
    docker.exec_in_backend(
        bench_dir,
        f"bench new-site {domain} --admin-password=admin --db-root-password=admin",
    )
    docker.exec_in_backend(bench_dir, f"bench --site {domain} install-app erpnext")
    return bench_dir


def start_bench(name: str) -> None:
    bench_dir = ensure_bench_exists(name)
    docker.compose_start(bench_dir)


def stop_bench(name: str) -> None:
    bench_dir = ensure_bench_exists(name)
    docker.compose_stop(bench_dir)


def restart_bench(name: str) -> None:
    bench_dir = ensure_bench_exists(name)
    docker.compose_restart(bench_dir)


def delete_bench(name: str) -> None:
    bench_dir = ensure_bench_exists(name)
    docker.compose_down(bench_dir)
    shutil.rmtree(bench_dir)


def list_benches() -> list[str]:
    if not BENCHES_DIR.exists():
        return []
    return sorted(path.name for path in BENCHES_DIR.iterdir() if path.is_dir())


def bench_logs(name: str, service: str | None = None, lines: int = 100) -> str:
    bench_dir = ensure_bench_exists(name)
    return docker.compose_logs(bench_dir, service=service, lines=lines)


def bench_health(name: str) -> str:
    bench_dir = ensure_bench_exists(name)
    return docker.compose_ps(bench_dir)


def open_bench_shell(name: str) -> None:
    bench_dir = ensure_bench_exists(name)
    try:
        docker.exec_backend_interactive(bench_dir, ["bash"])
    except docker.DockerCommandError:
        docker.exec_backend_interactive(bench_dir, ["sh"])


def open_site_console(name: str, site: str) -> None:
    bench_dir = ensure_bench_exists(name)
    docker.exec_backend_interactive(bench_dir, ["bash", "-lc", f"bench --site {site} console"])
