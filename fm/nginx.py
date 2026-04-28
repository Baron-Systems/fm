from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import FMConfig


TEMPLATES_DIR = Path(__file__).parent / "templates"
NGINX_INCLUDE_LINE = "include /etc/nginx/conf.d/*.conf;"
LOGGER = logging.getLogger("fm")


class NginxConfigError(RuntimeError):
    """Raised when NGINX config generation or reload fails."""


def is_nginx_available(config: FMConfig) -> bool:
    """Check if nginx is available either as host binary or Docker container."""
    # Check if nginx binary is available
    try:
        subprocess.run(
            [config.nginx_bin, "-v"],
            text=True,
            check=True,
            capture_output=True,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        pass

    # Check if nginx is running in Docker
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=nginx", "--format", "{{.Names}}"],
            text=True,
            check=True,
            capture_output=True,
        )
        if result.stdout.strip():
            return True
    except (OSError, subprocess.CalledProcessError):
        pass

    return False


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
    """Ensure nginx main config includes the conf.d directory. Returns True if modified, False otherwise."""
    if not config.nginx_ensure_main_include:
        return False

    main_config_path = config.nginx_main_config
    if not main_config_path.exists():
        LOGGER.warning(
            "NGINX main config not found at %s. Skipping reverse proxy configuration.",
            main_config_path,
        )
        return False

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
    """Configure nginx for a bench. Returns config path if successful, None if skipped or failed."""
    # Skip if nginx integration is disabled
    if not config.nginx_integration_enabled:
        LOGGER.info("NGINX integration disabled, skipping reverse proxy configuration")
        return None

    # Skip if nginx is not enabled
    if not config.nginx_enabled:
        return None

    # Check if nginx is available (host binary or Docker container)
    if not is_nginx_available(config):
        LOGGER.warning("NGINX not available, skipping reverse proxy configuration step")
        return None

    # Ensure main config includes conf.d directory (non-blocking)
    ensure_main_nginx_include(config)
    conf_path = write_bench_nginx_config(bench_name=bench_name, domain=domain, config=config)

    if config.nginx_validate_and_reload:
        try:
            validate_nginx_config(config)
            reload_nginx(config)
        except Exception as exc:
            LOGGER.warning("NGINX validation/reload failed: %s", exc)
            try:
                if conf_path.exists():
                    conf_path.unlink()
            except OSError:
                pass
            # Return None to indicate nginx config failed but don't raise
            return None

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
