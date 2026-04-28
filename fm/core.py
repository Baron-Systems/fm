from __future__ import annotations

import json
import logging
import shlex
import socket
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

from .config import FMConfig, load_config
from . import docker
from . import proxy
from .state import get_all_benches as state_get_all_benches
from .state import get_bench as state_get_bench
from .state import remove_bench as state_remove_bench
from .state import upsert_bench as state_upsert_bench
from .utils import generate_secure_password, validate_domain

TEMPLATES_DIR = Path(__file__).parent / "templates"
COMPOSE_FILE_NAME = "docker-compose.yml"
SHARED_WEB_NETWORK = "web"


class BenchError(RuntimeError):
    """Raised when a bench operation fails."""


LOGGER = logging.getLogger("fm")


def _escape_compose_env(value: str) -> str:
    """
    Escape `$` for docker compose interpolation rules.
    Compose treats `$VAR` as environment interpolation unless escaped as `$$`.
    """
    return value.replace("$", "$$")


def get_bench_path(name: str, config: FMConfig | None = None) -> Path:
    state_bench = state_get_bench(name)
    if state_bench and state_bench.get("path"):
        return Path(str(state_bench["path"]))
    cfg = config or load_config()
    return cfg.benches_dir / name


def bench_exists(name: str, config: FMConfig | None = None) -> bool:
    bench = state_get_bench(name)
    if not bench:
        return False
    path = Path(str(bench.get("path", get_bench_path(name, config=config))))
    return path.exists()


def get_all_benches(config: FMConfig | None = None) -> list[str]:
    benches = state_get_all_benches()
    return sorted(benches.keys())


def ensure_bench_missing(name: str, config: FMConfig | None = None) -> None:
    if bench_exists(name, config=config):
        raise BenchError(f"Bench '{name}' already exists.")


def ensure_bench_exists(name: str, config: FMConfig | None = None) -> Path:
    bench = state_get_bench(name)
    if not bench:
        raise BenchError(f"Bench '{name}' does not exist in state.")
    path = get_bench_path(name, config=config)
    if not path.exists():
        raise BenchError(f"Bench '{name}' path does not exist: {path}")
    return path


def _render_compose(
    name: str,
    domain: str,
    site_name: str,
    db_root_password: str,
    certresolver: str,
    erpnext_image: str,
    mariadb_image: str,
    redis_image: str,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("docker-compose.yml.j2")
    return template.render(
        NAME=name,
        DOMAIN=domain,
        SITE_NAME=site_name,
        DB_ROOT_PASSWORD=db_root_password,
        CERTRESOLVER=certresolver,
        ERPNEXT_IMAGE=erpnext_image,
        MARIADB_IMAGE=mariadb_image,
        REDIS_IMAGE=redis_image,
    )


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_service_networks(networks: object, shared_network: str) -> list[str] | dict[str, dict]:
    if isinstance(networks, dict):
        normalized = dict(networks)
        normalized.setdefault("default", {})
        normalized.setdefault(shared_network, {})
        return normalized

    normalized_list: list[str] = []
    if isinstance(networks, list):
        normalized_list.extend(str(item) for item in networks if isinstance(item, (str, int, float)))
    elif isinstance(networks, str):
        normalized_list.append(networks)

    normalized_list.extend(["default", shared_network])
    return _dedupe_preserve_order(normalized_list)


def _ensure_shared_web_network(compose_content: str, enabled: bool = True) -> str:
    compose_data = yaml.safe_load(compose_content) or {}
    if not isinstance(compose_data, dict):
        raise BenchError("Generated docker-compose content is invalid.")

    services = compose_data.get("services") or {}
    if not isinstance(services, dict):
        raise BenchError("Generated docker-compose services definition is invalid.")

    if enabled:
        for service in services.values():
            if isinstance(service, dict):
                service["networks"] = _normalize_service_networks(service.get("networks"), SHARED_WEB_NETWORK)

        networks = compose_data.get("networks") or {}
        if not isinstance(networks, dict):
            networks = {}
        networks["default"] = {}
        networks[SHARED_WEB_NETWORK] = {"external": True}
        compose_data["networks"] = networks

    rendered = yaml.safe_dump(compose_data, sort_keys=False)
    return rendered.replace("default: {}\n", "default:\n")


def _validate_create_inputs(name: str, domain: str, config: FMConfig) -> None:
    ensure_bench_missing(name, config=config)
    if not validate_domain(domain):
        raise BenchError(f"Invalid domain format: {domain}")
    if not docker.docker_available():
        raise BenchError("Docker is not installed or Docker Compose plugin is unavailable.")
    if config.attach_shared_web_network:
        created = docker.ensure_docker_network(SHARED_WEB_NETWORK)
        if created:
            LOGGER.info("Docker network '%s' was missing and has been created.", SHARED_WEB_NETWORK)


def _save_credentials(bench_dir: Path, domain: str, admin_password: str, db_root_password: str) -> Path:
    creds = {
        "site": domain,
        "admin_password": admin_password,
        "db_root_password": db_root_password,
    }
    creds_path = bench_dir / ".credentials.json"
    creds_path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    creds_path.chmod(0o600)
    return creds_path


def _load_bench_credentials(bench_dir: Path) -> dict[str, str] | None:
    creds_path = bench_dir / ".credentials.json"
    if not creds_path.is_file():
        return None
    try:
        data = json.loads(creds_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "site": str(data.get("site") or ""),
        "admin_password": str(data.get("admin_password") or ""),
        "db_root_password": str(data.get("db_root_password") or ""),
    }


def wait_for_service(host: str, port: int, timeout: int = 120) -> bool:
    return docker.wait_for_service(host=host, port=port, timeout=timeout)


def _wait_for_dependencies(bench_dir: Path, timeout: int = 120) -> None:
    docker.wait_for_service_in_backend(bench_dir, "db", 3306, timeout=timeout)
    docker.wait_for_service_in_backend(bench_dir, "backend", 8000, timeout=timeout)
    docker.wait_for_service_in_backend(bench_dir, "redis", 6379, timeout=timeout)


def create_bench(name: str, domain: str, config: FMConfig | None = None) -> tuple[Path, str, Path]:
    cfg = config or load_config()
    _validate_create_inputs(name=name, domain=domain, config=cfg)

    db_root_password = cfg.db_root_password or generate_secure_password()
    admin_password = cfg.admin_password or generate_secure_password()

    bench_dir = get_bench_path(name, config=cfg)
    cfg.benches_dir.mkdir(parents=True, exist_ok=True)
    bench_dir.mkdir(parents=True, exist_ok=False)
    state_upsert_bench(
        name,
        {
            "domain": domain,
            "path": str(bench_dir),
            "status": "creating",
        },
    )

    compose_content = _render_compose(
        name=name,
        domain=domain,
        site_name=domain,
        db_root_password=_escape_compose_env(db_root_password),
        certresolver=cfg.certresolver,
        erpnext_image=cfg.erpnext_image,
        mariadb_image=cfg.mariadb_image,
        redis_image=cfg.redis_image,
    )
    compose_content = _ensure_shared_web_network(
        compose_content,
        enabled=cfg.attach_shared_web_network,
    )
    compose_path = bench_dir / COMPOSE_FILE_NAME
    compose_path.write_text(compose_content, encoding="utf-8")

    try:
        docker.compose_up(bench_dir)
        _wait_for_dependencies(bench_dir, timeout=120)
        # Ensure site creation uses the MariaDB service container, not localhost.
        docker.exec_in_backend(bench_dir, "bench set-config -g db_host db")
        docker.exec_in_backend(bench_dir, "bench set-config -g db_port 3306")
        # Ensure Frappe uses Redis service in the compose network.
        docker.exec_in_backend(bench_dir, "bench set-config -g redis_cache redis://redis:6379")
        docker.exec_in_backend(bench_dir, "bench set-config -g redis_queue redis://redis:6379")
        docker.exec_in_backend(bench_dir, "bench set-config -g redis_socketio redis://redis:6379")
        docker.exec_in_backend(
            bench_dir,
            " ".join(
                [
                    "bench",
                    "new-site",
                    shlex.quote(domain),
                    f"--admin-password={shlex.quote(admin_password)}",
                    f"--db-root-password={shlex.quote(db_root_password)}",
                ]
            ),
        )
        docker.exec_in_backend(
            bench_dir,
            " ".join(["bench", "--site", shlex.quote(domain), "install-app", "erpnext"]),
        )
        creds_path = _save_credentials(bench_dir, domain, admin_password, db_root_password)
        state_upsert_bench(
            name,
            {
                "domain": domain,
                "path": str(bench_dir),
                "status": "running",
            },
        )
        LOGGER.info("Bench created: %s", name)
    except Exception as exc:
        LOGGER.error("Create failed for %s. Rolling back resources.", name)
        try:
            docker.compose_down(bench_dir, remove_volumes=True)
        except Exception as down_exc:  # noqa: BLE001
            LOGGER.warning("Rollback docker down failed: %s", down_exc)
        shutil.rmtree(bench_dir, ignore_errors=True)
        state_remove_bench(name)
        raise BenchError(f"Bench creation failed and rollback completed: {exc}") from exc

    # Optional post-processing: Proxy configuration (non-blocking)
    proxy_conf_path: Path | None = None
    try:
        proxy_conf_path = proxy.add_bench_to_proxy(name, domain, cfg)
    except Exception as proxy_exc:  # noqa: BLE001
        LOGGER.warning("Proxy configuration failed (non-blocking): %s", proxy_exc)

    return bench_dir, admin_password, creds_path


def start_bench(name: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    docker.compose_start(bench_dir)
    state_upsert_bench(name, {"status": "running"})


def stop_bench(name: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    docker.compose_stop(bench_dir)
    state_upsert_bench(name, {"status": "stopped"})


def restart_bench(name: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    docker.compose_restart(bench_dir)
    state_upsert_bench(name, {"status": "running"})


def delete_bench(name: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    docker.compose_down(bench_dir, remove_volumes=True)
    cfg = config or load_config()
    try:
        proxy.remove_bench_from_proxy(name, cfg)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to remove proxy config for %s: %s", name, exc)
    shutil.rmtree(bench_dir)
    state_remove_bench(name)


def _bench_domain_from_compose(bench_dir: Path) -> str:
    compose_path = bench_dir / COMPOSE_FILE_NAME
    if not compose_path.exists():
        return "-"
    for line in compose_path.read_text(encoding="utf-8").splitlines():
        if "traefik.http.routers." in line and ".rule=Host(" in line:
            start = line.find("Host(`")
            if start != -1:
                end = line.find("`)", start)
                if end != -1:
                    return line[start + len("Host(`") : end]
    return "-"


def list_benches(config: FMConfig | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for bench_name in get_all_benches(config=config):
        bench = state_get_bench(bench_name) or {}
        bench_path = Path(str(bench.get("path", get_bench_path(bench_name, config=config))))
        status = str(bench.get("status", "unknown"))
        try:
            services = docker.compose_ps_json(bench_path)
            if not services:
                status = "stopped"
            elif all("running" in (item.get("State") or "").lower() for item in services):
                status = "running"
            else:
                status = "degraded"
        except Exception:
            status = "error"
        rows.append(
            {
                "name": bench_name,
                "status": status,
                "domain": str(bench.get("domain", _bench_domain_from_compose(bench_path))),
            }
        )
    return rows


def bench_logs(name: str, service: str | None = None, lines: int = 100, follow: bool = True, config: FMConfig | None = None) -> str | None:
    bench_dir = ensure_bench_exists(name, config=config)
    if follow:
        docker.compose_logs_follow(bench_dir, service=service)
        return None
    return docker.compose_logs(bench_dir, service=service, lines=lines)


def bench_health(name: str, config: FMConfig | None = None) -> str:
    bench_dir = ensure_bench_exists(name, config=config)
    return docker.compose_ps(bench_dir)


def bench_status(name: str, config: FMConfig | None = None) -> dict:
    bench_dir = ensure_bench_exists(name, config=config)
    services = docker.compose_ps_json(bench_dir)
    running = sum(1 for item in services if "running" in (item.get("State") or "").lower())
    total = len(services)
    return {
        "name": name,
        "domain": _bench_domain_from_compose(bench_dir),
        "running": str(running),
        "total": str(total),
        "raw_ps": docker.compose_ps(bench_dir),
    }


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _collect_service_health(bench_dir: Path, backend_running: bool) -> dict[str, str]:
    health = {
        "backend:8000": "not reachable",
        "db:3306": "not reachable",
        "redis:6379": "not reachable",
    }
    if not backend_running:
        return health

    script = """python - <<'PY'
import json
import socket

checks = {"backend:8000": ("backend", 8000), "db:3306": ("db", 3306), "redis:6379": ("redis", 6379)}
result = {}
for key, (host, port) in checks.items():
    try:
        socket.create_connection((host, port), timeout=2).close()
        result[key] = "healthy"
    except OSError:
        result[key] = "not reachable"

print(json.dumps(result))
PY"""
    try:
        raw = docker.exec_in_backend_output(bench_dir, script).strip()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key in health:
                    if key in parsed:
                        health[key] = str(parsed[key])
    except Exception:
        pass
    return health


def _try_list_apps(bench_dir: Path, domain: str, backend_running: bool) -> list[str]:
    if not backend_running or not domain or domain == "-":
        return []
    try:
        output = docker.exec_in_backend_output(bench_dir, f"bench --site {domain} list-apps")
    except Exception:
        return []
    apps = [line.strip() for line in output.splitlines() if line.strip()]
    return apps


def _volume_usage(project_name: str) -> dict[str, str]:
    usage: dict[str, str] = {}
    for volume in ["db-data", "sites", "logs"]:
        docker_volume = f"{project_name}_{volume}"
        mountpoint = docker.docker_volume_mountpoint(docker_volume)
        if mountpoint is None or not mountpoint.exists():
            usage[volume] = "n/a"
            continue
        usage[volume] = _format_bytes(_dir_size_bytes(mountpoint))
    return usage


def get_bench_info(name: str, config: FMConfig | None = None) -> dict:
    bench_dir = ensure_bench_exists(name, config=config)
    domain = _bench_domain_from_compose(bench_dir)

    info: dict = {
        "name": name,
        "path": str(bench_dir),
        "domain": domain,
        "status": "stopped",
        "docker_available": docker.docker_available(),
        "dns": {"resolved": False, "address": "-", "reachable": False},
        "containers": [],
        "services_health": {
            "backend:8000": "not reachable",
            "db:3306": "not reachable",
            "redis:6379": "not reachable",
        },
        "apps": [],
        "disk_usage": {
            "bench": _format_bytes(_dir_size_bytes(bench_dir)),
            "volumes": {},
        },
        "raw_ps": "",
    }
    info["credentials"] = _load_bench_credentials(bench_dir)

    if domain and domain != "-":
        try:
            resolved_ip = socket.gethostbyname(domain)
            info["dns"] = {"resolved": True, "address": resolved_ip, "reachable": False}
            try:
                with socket.create_connection((domain, 443), timeout=2):
                    info["dns"]["reachable"] = True
            except OSError:
                info["dns"]["reachable"] = False
        except OSError:
            pass

    if not info["docker_available"]:
        return info

    try:
        containers = docker.compose_ps_json(bench_dir)
        info["containers"] = containers
        info["raw_ps"] = docker.compose_ps(bench_dir)
        if not containers:
            info["status"] = "stopped"
            return info
        if all("running" in (item.get("State") or "").lower() for item in containers):
            info["status"] = "running"
        else:
            info["status"] = "degraded"

        backend_running = any(
            (item.get("Service") == "backend" and "running" in (item.get("State") or "").lower())
            for item in containers
        )
        info["services_health"] = _collect_service_health(bench_dir, backend_running=backend_running)
        info["apps"] = _try_list_apps(bench_dir, domain=domain, backend_running=backend_running)
        info["disk_usage"]["volumes"] = _volume_usage(project_name=bench_dir.name)
        return info
    except Exception:
        info["status"] = "error"
        return info


def open_bench_shell(name: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    try:
        docker.exec_backend_interactive(bench_dir, ["bash"])
    except docker.DockerCommandError:
        docker.exec_backend_interactive(bench_dir, ["sh"])


def open_site_console(name: str, site: str, config: FMConfig | None = None) -> None:
    bench_dir = ensure_bench_exists(name, config=config)
    docker.exec_backend_interactive(bench_dir, ["bash", "-lc", f"bench --site {site} console"])
