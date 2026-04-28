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
        FRONTEND_UPSTREAM=f"{bench_name}-frontend:8080",
        WEBSOCKET_UPSTREAM=f"{bench_name}-websocket:9000",
    ).strip() + "\n"


def nginx_conf_path(bench_name: str, config: FMConfig) -> Path:
    """Get the path for nginx config in the fm-specific directory."""
    return config.nginx_fm_conf_dir / f"{bench_name}.conf"


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


def enable_proxy(bench_name: str, domain: str, config: FMConfig) -> bool:
    """Enable reverse proxy for a bench. Returns True if successful, False otherwise."""
    # Check if nginx is available
    if not is_nginx_available(config):
        LOGGER.warning("NGINX not available, cannot enable reverse proxy")
        return False

    # Create fm nginx config directory
    config.nginx_fm_conf_dir.mkdir(parents=True, exist_ok=True)

    # Ensure main nginx config includes fm directory
    fm_include_line = f"include {config.nginx_fm_conf_dir}/*.conf;"
    main_config_path = config.nginx_main_config

    if main_config_path.exists():
        content = main_config_path.read_text(encoding="utf-8")
        if fm_include_line not in content:
            http_block_pattern = re.compile(r"(^\s*http\s*\{\s*$)", re.MULTILINE)
            if http_block_pattern.search(content):
                updated = http_block_pattern.sub(rf"\1\n    {fm_include_line}", content, count=1)
            else:
                updated = content.rstrip() + f"\n{fm_include_line}\n"
            main_config_path.write_text(updated, encoding="utf-8")
            LOGGER.info("Added fm nginx include to main config")
    else:
        LOGGER.warning("Main nginx config not found, skipping include update")

    # Write bench-specific nginx config
    conf_path = nginx_conf_path(bench_name, config)
    rendered = _render_nginx_server_block(bench_name=bench_name, domain=domain)
    conf_path.write_text(rendered, encoding="utf-8")
    LOGGER.info("Generated nginx config for bench '%s' at %s", bench_name, conf_path)

    # Validate and reload nginx
    if config.nginx_validate_and_reload:
        try:
            validate_nginx_config(config)
            reload_nginx(config)
            LOGGER.info("NGINX validated and reloaded successfully")
        except Exception as exc:
            LOGGER.warning("NGINX validation/reload failed: %s", exc)
            return False

    return True


def disable_proxy(bench_name: str, config: FMConfig) -> bool:
    """Disable reverse proxy for a bench. Returns True if successful, False otherwise."""
    conf_path = nginx_conf_path(bench_name, config)
    if not conf_path.exists():
        LOGGER.info("No nginx config found for bench '%s'", bench_name)
        return True

    try:
        conf_path.unlink()
        LOGGER.info("Removed nginx config for bench '%s'", bench_name)

        if config.nginx_validate_and_reload:
            validate_nginx_config(config)
            reload_nginx(config)
            LOGGER.info("NGINX validated and reloaded successfully")
        return True
    except Exception as exc:
        LOGGER.warning("Failed to disable proxy for bench '%s': %s", bench_name, exc)
        return False


def sync_proxy(get_all_benches_func, get_bench_func, config: FMConfig) -> dict[str, bool]:
    """Sync proxy configurations for all benches. Returns dict of bench_name -> success."""
    results: dict[str, bool] = {}

    # Check if nginx is available
    if not is_nginx_available(config):
        LOGGER.warning("NGINX not available, skipping proxy sync")
        return results

    # Get all benches
    bench_names = get_all_benches_func(config=config)
    if not bench_names:
        LOGGER.info("No benches found, nothing to sync")
        return results

    LOGGER.info("Syncing proxy configurations for %d benches", len(bench_names))

    # Create fm nginx config directory
    config.nginx_fm_conf_dir.mkdir(parents=True, exist_ok=True)

    # Ensure main nginx config includes fm directory
    fm_include_line = f"include {config.nginx_fm_conf_dir}/*.conf;"
    main_config_path = config.nginx_main_config

    if main_config_path.exists():
        content = main_config_path.read_text(encoding="utf-8")
        if fm_include_line not in content:
            http_block_pattern = re.compile(r"(^\s*http\s*\{\s*$)", re.MULTILINE)
            if http_block_pattern.search(content):
                updated = http_block_pattern.sub(rf"\1\n    {fm_include_line}", content, count=1)
            else:
                updated = content.rstrip() + f"\n{fm_include_line}\n"
            main_config_path.write_text(updated, encoding="utf-8")
            LOGGER.info("Added fm nginx include to main config")
    else:
        LOGGER.warning("Main nginx config not found, skipping include update")

    # Generate configs for each bench
    for bench_name in bench_names:
        bench = get_bench_func(bench_name)
        if not bench:
            LOGGER.warning("Bench '%s' not found in state, skipping", bench_name)
            results[bench_name] = False
            continue

        domain = bench.get("domain", "")
        if not domain:
            LOGGER.warning("Bench '%s' has no domain, skipping", bench_name)
            results[bench_name] = False
            continue

        try:
            conf_path = nginx_conf_path(bench_name, config)
            rendered = _render_nginx_server_block(bench_name=bench_name, domain=domain)
            conf_path.write_text(rendered, encoding="utf-8")
            LOGGER.info("Generated nginx config for bench '%s'", bench_name)
            results[bench_name] = True
        except Exception as exc:
            LOGGER.warning("Failed to generate nginx config for bench '%s': %s", bench_name, exc)
            results[bench_name] = False

    # Validate and reload nginx
    if config.nginx_validate_and_reload and any(results.values()):
        try:
            validate_nginx_config(config)
            reload_nginx(config)
            LOGGER.info("NGINX validated and reloaded successfully")
        except Exception as exc:
            LOGGER.warning("NGINX validation/reload failed: %s", exc)

    return results
