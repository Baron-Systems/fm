from __future__ import annotations

import re
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import FMConfig


TEMPLATES_DIR = Path(__file__).parent / "templates"
NGINX_INCLUDE_LINE = "include /etc/nginx/conf.d/*.conf;"


class NginxConfigError(RuntimeError):
    """Raised when NGINX config generation or reload fails."""


def _run_nginx_command(config: FMConfig, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [config.nginx_bin, *args]
    try:
        return subprocess.run(cmd, text=True, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or "Unknown nginx error"
        raise NginxConfigError(f"Failed command: {' '.join(cmd)}\n{details}") from exc
    except OSError as exc:
        raise NginxConfigError(f"Failed to execute {' '.join(cmd)}: {exc}") from exc


def _render_nginx_server_block(bench_name: str, domain: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("nginx-bench.conf.j2")
    return template.render(
        BENCH_NAME=bench_name,
        DOMAIN=domain,
        FRONTEND_UPSTREAM=f"{bench_name}-frontend:80",
        WEBSOCKET_UPSTREAM=f"{bench_name}-websocket:9000",
    ).strip() + "\n"


def nginx_conf_path(bench_name: str, config: FMConfig) -> Path:
    return config.nginx_conf_dir / f"{bench_name}.conf"


def ensure_main_nginx_include(config: FMConfig) -> bool:
    if not config.nginx_ensure_main_include:
        return False

    main_config_path = config.nginx_main_config
    if not main_config_path.exists():
        raise NginxConfigError(f"Main nginx config not found: {main_config_path}")

    content = main_config_path.read_text(encoding="utf-8")
    if NGINX_INCLUDE_LINE in content:
        return False

    http_block_pattern = re.compile(r"(^\s*http\s*\{\s*$)", re.MULTILINE)
    if http_block_pattern.search(content):
        updated = http_block_pattern.sub(rf"\1\n    {NGINX_INCLUDE_LINE}", content, count=1)
    else:
        updated = content.rstrip() + f"\n{NGINX_INCLUDE_LINE}\n"

    main_config_path.write_text(updated, encoding="utf-8")
    return True


def write_bench_nginx_config(bench_name: str, domain: str, config: FMConfig) -> Path:
    conf_path = nginx_conf_path(bench_name, config)
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _render_nginx_server_block(bench_name=bench_name, domain=domain)
    current = conf_path.read_text(encoding="utf-8") if conf_path.exists() else None
    if current != rendered:
        conf_path.write_text(rendered, encoding="utf-8")
    return conf_path


def validate_nginx_config(config: FMConfig) -> None:
    _run_nginx_command(config, ["-t"])


def reload_nginx(config: FMConfig) -> None:
    _run_nginx_command(config, ["-s", "reload"])


def configure_bench_nginx(bench_name: str, domain: str, config: FMConfig) -> Path | None:
    if not config.nginx_enabled:
        return None

    ensure_main_nginx_include(config)
    conf_path = write_bench_nginx_config(bench_name=bench_name, domain=domain, config=config)

    if config.nginx_validate_and_reload:
        try:
            validate_nginx_config(config)
            reload_nginx(config)
        except Exception:
            try:
                if conf_path.exists():
                    conf_path.unlink()
            except OSError:
                pass
            raise

    return conf_path


def remove_bench_nginx_config(bench_name: str, config: FMConfig) -> None:
    if not config.nginx_enabled:
        return

    conf_path = nginx_conf_path(bench_name, config)
    if conf_path.exists():
        conf_path.unlink()

    if config.nginx_validate_and_reload:
        validate_nginx_config(config)
        reload_nginx(config)
