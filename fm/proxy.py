from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import FMConfig
from . import docker

TEMPLATES_DIR = Path(__file__).parent / "templates"
LOGGER = logging.getLogger("fm")


class ProxyError(RuntimeError):
    """Raised when proxy operations fail."""


def _safe_run_command(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str] | None:
    """
    Safely run a subprocess command with proper error handling.
    
    Returns CompletedProcess on success, None on failure.
    Never raises exceptions - logs warnings instead.
    """
    try:
        if capture:
            return subprocess.run(cmd, text=True, check=check, capture_output=True)
        else:
            return subprocess.run(cmd, text=True, check=check)
    except (OSError, subprocess.CalledProcessError) as exc:
        LOGGER.warning("Proxy command failed: %s - %s", " ".join(cmd), exc)
        return None


def _render_nginx_server_block(bench_name: str, domain: str) -> str:
    """Render nginx server block configuration for a bench."""
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


def get_proxy_config_path(bench_name: str, config: FMConfig) -> Path:
    """Get the path for proxy configuration in the fm-specific directory."""
    return config.nginx_fm_conf_dir / f"{bench_name}.conf"


def is_nginx_available(config: FMConfig) -> bool:
    """
    Check if nginx is available via Docker container.
    
    This function only checks for Docker-based nginx to avoid host binary dependencies.
    This ensures fm create works in Docker-only environments without host nginx.
    """
    # Check if nginx is running in Docker
    result = _safe_run_command(
        ["docker", "ps", "--filter", "name=nginx", "--format", "{{.Names}}"],
        check=False,
        capture=True,
    )
    if result is not None and result.stdout and result.stdout.strip():
        return True

    # Check if nginx container exists (even if not running)
    result = _safe_run_command(
        ["docker", "ps", "-a", "--filter", "name=nginx", "--format", "{{.Names}}"],
        check=False,
        capture=True,
    )
    if result is not None and result.stdout and result.stdout.strip():
        return True

    return False


def _run_nginx_command(config: FMConfig, args: list[str]) -> bool:
    """
    Run an nginx command and handle errors safely.
    
    Returns True if successful, False otherwise.
    Never raises exceptions - logs warnings instead.
    """
    cmd = [config.nginx_bin, *args]
    result = _safe_run_command(cmd, check=True, capture=True)
    if result is None:
        LOGGER.warning("NGINX command failed: %s", " ".join(cmd))
        return False
    return True


def validate_nginx_config(config: FMConfig) -> bool:
    """
    Validate nginx configuration.
    
    Returns True if successful, False otherwise.
    """
    return _run_nginx_command(config, ["-t"])


def reload_nginx(config: FMConfig) -> bool:
    """
    Reload nginx configuration.
    
    Returns True if successful, False otherwise.
    """
    return _run_nginx_command(config, ["-s", "reload"])


def ensure_main_nginx_include(config: FMConfig) -> bool:
    """Ensure nginx main config includes the fm conf directory. Returns True if modified."""
    if not config.nginx_ensure_main_include:
        return False

    main_config_path = config.nginx_main_config
    if not main_config_path.exists():
        LOGGER.warning(
            "NGINX main config not found at %s. Skipping include update.",
            main_config_path,
        )
        return False

    fm_include_line = f"include {config.nginx_fm_conf_dir}/*.conf;"
    content = main_config_path.read_text(encoding="utf-8")
    if fm_include_line in content:
        return False

    http_block_pattern = re.compile(r"(^\s*http\s*\{\s*$)", re.MULTILINE)
    if http_block_pattern.search(content):
        updated = http_block_pattern.sub(rf"\1\n    {fm_include_line}", content, count=1)
    else:
        updated = content.rstrip() + f"\n{fm_include_line}\n"

    main_config_path.write_text(updated, encoding="utf-8")
    LOGGER.info("Added fm nginx include to main config")
    return True


def init_proxy(config: FMConfig) -> bool:
    """
    Initialize the proxy layer infrastructure.
    
    This sets up the reverse proxy infrastructure by:
    - Creating the fm nginx config directory
    - Ensuring nginx main config includes the fm directory
    - Connecting to the shared docker network if needed
    
    Returns True if successful, False otherwise.
    """
    LOGGER.info("Initializing proxy layer infrastructure")

    # Check if nginx is available
    if not is_nginx_available(config):
        LOGGER.warning("NGINX not available, proxy layer initialization skipped")
        return False

    # Create fm nginx config directory
    config.nginx_fm_conf_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Created proxy config directory: %s", config.nginx_fm_conf_dir)

    # Ensure main nginx config includes fm directory
    ensure_main_nginx_include(config)

    # Validate nginx config
    if config.nginx_validate_and_reload:
        if not validate_nginx_config(config):
            LOGGER.warning("NGINX validation failed")
            return False
        LOGGER.info("NGINX configuration validated successfully")

    LOGGER.info("Proxy layer initialized successfully")
    return True


def add_bench_to_proxy(bench_name: str, domain: str, config: FMConfig) -> bool:
    """
    Add a bench to the proxy layer.
    
    This generates routing configuration for:
    - Frontend service (port 80)
    - Websocket service (port 9000)
    - Domain mapping
    
    Returns True if successful, False otherwise.
    """
    LOGGER.info("Adding bench '%s' to proxy layer for domain %s", bench_name, domain)

    # Check if nginx is available
    if not is_nginx_available(config):
        LOGGER.warning("NGINX not available, cannot add bench to proxy")
        return False

    # Ensure proxy layer is initialized
    config.nginx_fm_conf_dir.mkdir(parents=True, exist_ok=True)
    ensure_main_nginx_include(config)

    # Generate and write bench-specific proxy config
    conf_path = get_proxy_config_path(bench_name, config)
    rendered = _render_nginx_server_block(bench_name=bench_name, domain=domain)
    conf_path.write_text(rendered, encoding="utf-8")
    LOGGER.info("Generated proxy config for bench '%s' at %s", bench_name, conf_path)

    # Validate and reload nginx
    if config.nginx_validate_and_reload:
        if not validate_nginx_config(config):
            LOGGER.warning("NGINX validation failed")
            return False
        if not reload_nginx(config):
            LOGGER.warning("NGINX reload failed")
            return False
        LOGGER.info("NGINX validated and reloaded successfully")

    return True


def remove_bench_from_proxy(bench_name: str, config: FMConfig) -> bool:
    """
    Remove a bench from the proxy layer.
    
    Returns True if successful, False otherwise.
    """
    LOGGER.info("Removing bench '%s' from proxy layer", bench_name)

    conf_path = get_proxy_config_path(bench_name, config)
    if not conf_path.exists():
        LOGGER.info("No proxy config found for bench '%s'", bench_name)
        return True

    try:
        conf_path.unlink()
        LOGGER.info("Removed proxy config for bench '%s'", bench_name)

        if config.nginx_validate_and_reload:
            if not validate_nginx_config(config):
                LOGGER.warning("NGINX validation failed during bench removal")
            elif not reload_nginx(config):
                LOGGER.warning("NGINX reload failed during bench removal")
            else:
                LOGGER.info("NGINX validated and reloaded successfully")
        return True
    except Exception as exc:
        LOGGER.warning("Failed to remove bench '%s' from proxy: %s", bench_name, exc)
        return False


def sync_proxy(
    get_all_benches_func: Callable,
    get_bench_func: Callable,
    config: FMConfig,
) -> dict[str, bool]:
    """
    Synchronize proxy configurations for all benches.
    
    This scans all existing benches and regenerates routing configs.
    
    Returns dict of bench_name -> success status.
    """
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

    # Ensure proxy layer is initialized
    config.nginx_fm_conf_dir.mkdir(parents=True, exist_ok=True)
    ensure_main_nginx_include(config)

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
            conf_path = get_proxy_config_path(bench_name, config)
            rendered = _render_nginx_server_block(bench_name=bench_name, domain=domain)
            conf_path.write_text(rendered, encoding="utf-8")
            LOGGER.info("Generated proxy config for bench '%s'", bench_name)
            results[bench_name] = True
        except Exception as exc:
            LOGGER.warning("Failed to generate proxy config for bench '%s': %s", bench_name, exc)
            results[bench_name] = False

    # Validate and reload nginx
    if config.nginx_validate_and_reload and any(results.values()):
        if not validate_nginx_config(config):
            LOGGER.warning("NGINX validation failed during sync")
        elif not reload_nginx(config):
            LOGGER.warning("NGINX reload failed during sync")
        else:
            LOGGER.info("NGINX validated and reloaded successfully")

    return results


def list_proxy_benches(config: FMConfig) -> list[str]:
    """
    List all benches currently registered in the proxy layer.
    
    Returns list of bench names.
    """
    if not config.nginx_fm_conf_dir.exists():
        return []

    conf_files = list(config.nginx_fm_conf_dir.glob("*.conf"))
    bench_names = [f.stem for f in conf_files if f.is_file()]
    return sorted(bench_names)


def get_proxy_status(config: FMConfig) -> dict:
    """
    Get the status of the proxy layer.
    
    Returns dict with status information.
    """
    return {
        "nginx_available": is_nginx_available(config),
        "config_dir_exists": config.nginx_fm_conf_dir.exists(),
        "config_dir": str(config.nginx_fm_conf_dir),
        "registered_benches": list_proxy_benches(config),
        "main_config_exists": config.nginx_main_config.exists(),
        "main_config": str(config.nginx_main_config),
    }
