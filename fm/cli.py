from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from . import core
from . import nginx
from .state import get_bench as state_get_bench
from .state import get_all_benches as state_get_all_benches
from .utils import setup_logging
from .utils.interactive import InteractiveSelectionError, select_bench

app = typer.Typer(help="Mini Frappe Manager for ERPNext Docker benches.")
console = Console()
config = load_config()
logger = setup_logging(write_file=config.write_log_file, log_file=config.log_file)


def _handle_error(exc: Exception) -> None:
    logger.error(str(exc))
    console.print(f"[bold red]Error:[/bold red] {exc}")
    raise typer.Exit(code=1)


def _resolve_bench_name(name: str | None) -> str:
    if name:
        return name
    benches = core.get_all_benches(config=config)
    try:
        selected = select_bench(config=config, benches=benches)
        console.print(f"[cyan]Selected bench:[/cyan] [bold]{selected}[/bold]")
        return selected
    except InteractiveSelectionError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1) from exc


@app.command("create")
def create(name: str, domain: str) -> None:
    """Create a new bench and bootstrap ERPNext site."""
    try:
        logger.info("Create requested for bench=%s domain=%s", name, domain)
        with console.status(f"Creating bench {name} for {domain}..."):
            bench_dir, admin_password, creds_path = core.create_bench(name=name, domain=domain, config=config)
        console.print(f"[green]Bench created successfully:[/green] {bench_dir}")
        console.print(
            Panel.fit(
                f"Site: [bold]{domain}[/bold]\n"
                f"Admin password: [bold]{admin_password}[/bold]\n"
                f"Credentials file: [bold]{creds_path}[/bold]",
                title="Generated Credentials",
                border_style="green",
            )
        )
    except Exception as exc:
        _handle_error(exc)


@app.command("hello")
def hello() -> None:
    """Print a welcome message."""
    console.print("Welcome to fm tool, Mr. Mohammed Taradeh.")


@app.command("start")
def start(name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)")) -> None:
    """Start a bench."""
    try:
        name = _resolve_bench_name(name)
        logger.info("Starting bench=%s", name)
        core.start_bench(name, config=config)
        console.print(f"[green]Started bench:[/green] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("stop")
def stop(name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)")) -> None:
    """Stop a bench."""
    try:
        name = _resolve_bench_name(name)
        logger.info("Stopping bench=%s", name)
        core.stop_bench(name, config=config)
        console.print(f"[yellow]Stopped bench:[/yellow] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("restart")
def restart(name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)")) -> None:
    """Restart a bench."""
    try:
        name = _resolve_bench_name(name)
        logger.info("Restarting bench=%s", name)
        core.restart_bench(name, config=config)
        console.print(f"[green]Restarted bench:[/green] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("delete")
def delete(
    name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Delete a bench and its files."""
    try:
        name = _resolve_bench_name(name)
        if not force:
            answer = typer.prompt(f"Are you sure you want to delete {name}? (y/N)", default="N")
            if answer.strip().lower() != "y":
                console.print("[yellow]Delete cancelled.[/yellow]")
                raise typer.Exit(code=0)
        logger.warning("Deleting bench=%s", name)
        core.delete_bench(name, config=config)
        console.print(f"[green]Deleted bench:[/green] {name}")
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("list")
def list_cmd() -> None:
    """List available benches."""
    benches = core.list_benches(config=config)
    if not benches:
        console.print("[yellow]No benches found.[/yellow]")
        return

    table = Table(title="ERPNext Benches")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")
    table.add_column("Domain", style="green")
    for bench in benches:
        table.add_row(bench["name"], bench["status"], bench["domain"])
    console.print(table)


@app.command("logs")
def logs(
    name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)"),
    service: str | None = typer.Option(None, "--service", "-s", help="Service name"),
    lines: int = typer.Option(100, "--lines", "-n", min=1, help="Number of log lines"),
    follow: bool = typer.Option(True, "--follow/--no-follow", help="Follow logs output"),
) -> None:
    """Show docker compose logs for a bench."""
    try:
        name = _resolve_bench_name(name)
        logger.info("Showing logs bench=%s service=%s follow=%s", name, service, follow)
        output = core.bench_logs(name=name, service=service, lines=lines, follow=follow, config=config)
        if output is not None:
            console.print(output if output.strip() else "[yellow]No logs available.[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@app.command("health")
def health(name: str) -> None:
    """Show docker compose status for a bench."""
    try:
        output = core.bench_health(name=name, config=config)
        console.print(output if output.strip() else "[yellow]No status output.[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@app.command("status")
def status(name: str) -> None:
    """Show bench status including health overview and compose output."""
    try:
        info = core.bench_status(name=name, config=config)
        console.print(
            Panel.fit(
                f"Bench: [bold]{info['name']}[/bold]\n"
                f"Domain: [bold]{info['domain']}[/bold]\n"
                f"Running containers: [bold]{info['running']}/{info['total']}[/bold]",
                title="Bench Status",
                border_style="cyan",
            )
        )
        console.print(info["raw_ps"] if info["raw_ps"].strip() else "[yellow]No docker compose output.[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@app.command("info")
def info(name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)")) -> None:
    """Show detailed information for a specific bench."""
    try:
        name = _resolve_bench_name(name)
        details = core.get_bench_info(name=name, config=config)
        console.print(
            Panel.fit(
                f"Bench: [bold]{details['name']}[/bold]\n"
                f"Status: [bold]{details['status']}[/bold]\n"
                f"Path: [bold]{details['path']}[/bold]\n"
                f"Domain: [bold]{details['domain']}[/bold]",
                title="Bench Overview",
                border_style="cyan",
            )
        )

        creds = details.get("credentials")
        if creds:
            console.print(
                Panel.fit(
                    f"Site: [bold]{creds['site']}[/bold]\n"
                    f"Admin password: [bold]{creds['admin_password']}[/bold]\n"
                    f"DB root password: [bold]{creds['db_root_password']}[/bold]",
                    title="Credentials",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel.fit(
                    "[yellow]No .credentials.json found (or file is unreadable).[/yellow]",
                    title="Credentials",
                    border_style="yellow",
                )
            )

        dns = details["dns"]
        console.print(
            Panel.fit(
                f"Resolved: [bold]{dns['resolved']}[/bold]\n"
                f"Address: [bold]{dns['address']}[/bold]\n"
                f"Reachable (443): [bold]{dns['reachable']}[/bold]",
                title="Domain Info",
                border_style="blue",
            )
        )

        containers_table = Table(title="Containers")
        containers_table.add_column("Container", style="cyan")
        containers_table.add_column("Service", style="green")
        containers_table.add_column("State", style="magenta")
        containers_table.add_column("Ports", style="yellow")
        containers = details.get("containers", [])
        if containers:
            for item in containers:
                container_name = str(item.get("Name") or item.get("Container") or "-")
                service_name = str(item.get("Service") or "-")
                state = str(item.get("State") or "-")
                ports = str(item.get("Publishers") or item.get("Ports") or "-")
                containers_table.add_row(container_name, service_name, state, ports)
        else:
            containers_table.add_row("-", "-", "stopped", "-")
        console.print(containers_table)

        health_table = Table(title="Services Health")
        health_table.add_column("Service", style="cyan")
        health_table.add_column("Health", style="green")
        for service, health in details["services_health"].items():
            health_table.add_row(service, health)
        console.print(health_table)

        apps = details.get("apps", [])
        apps_table = Table(title="Installed Apps")
        apps_table.add_column("App", style="cyan")
        if apps:
            for app_name in apps:
                apps_table.add_row(app_name)
        else:
            apps_table.add_row("No app data available")
        console.print(apps_table)

        disk_usage = details["disk_usage"]
        disk_table = Table(title="Disk Usage")
        disk_table.add_column("Target", style="cyan")
        disk_table.add_column("Size", style="green")
        disk_table.add_row("bench", str(disk_usage["bench"]))
        for volume, size in disk_usage.get("volumes", {}).items():
            disk_table.add_row(f"volume:{volume}", str(size))
        console.print(disk_table)

    except Exception as exc:
        _handle_error(exc)


@app.command("shell")
def shell(
    name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)"),
    site: str | None = typer.Option(None, "--site", help="Open bench console for a specific site"),
) -> None:
    """Open interactive shell in backend container or site console."""
    try:
        name = _resolve_bench_name(name)
        if site:
            console.print(f"[cyan]Opening bench console for site[/cyan] [bold]{site}[/bold]")
            core.open_site_console(name=name, site=site, config=config)
        else:
            console.print(f"[cyan]Opening backend shell for bench[/cyan] [bold]{name}[/bold]")
            core.open_bench_shell(name=name, config=config)
    except Exception as exc:
        _handle_error(exc)


@app.command("enable-proxy")
def enable_proxy(
    name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)"),
) -> None:
    """Enable reverse proxy for a bench."""
    try:
        name = _resolve_bench_name(name)
        bench = state_get_bench(name)
        if not bench:
            console.print(f"[red]Bench '{name}' not found.[/red]")
            raise typer.Exit(code=1)

        domain = bench.get("domain", "")
        if not domain:
            console.print(f"[red]Bench '{name}' has no domain configured.[/red]")
            raise typer.Exit(code=1)

        logger.info("Enabling proxy for bench=%s domain=%s", name, domain)
        with console.status(f"Enabling reverse proxy for {name}..."):
            success = nginx.enable_proxy(name, domain, config)

        if success:
            console.print(f"[green]Reverse proxy enabled for bench:[/green] {name}")
            console.print(f"[cyan]Config file:[/cyan] {config.nginx_fm_conf_dir / f'{name}.conf'}")
        else:
            console.print(f"[yellow]Failed to enable reverse proxy for bench:[/yellow] {name}")
            console.print("[yellow]Check logs for details. NGINX may not be available.[/yellow]")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("disable-proxy")
def disable_proxy(
    name: str | None = typer.Argument(None, help="Bench name (optional in interactive mode)"),
) -> None:
    """Disable reverse proxy for a bench."""
    try:
        name = _resolve_bench_name(name)
        logger.info("Disabling proxy for bench=%s", name)
        with console.status(f"Disabling reverse proxy for {name}..."):
            success = nginx.disable_proxy(name, config)

        if success:
            console.print(f"[green]Reverse proxy disabled for bench:[/green] {name}")
        else:
            console.print(f"[yellow]Failed to disable reverse proxy for bench:[/yellow] {name}")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("sync-proxy")
def sync_proxy() -> None:
    """Sync reverse proxy configurations for all benches."""
    try:
        logger.info("Syncing proxy configurations for all benches")
        with console.status("Syncing reverse proxy configurations..."):
            results = nginx.sync_proxy(state_get_all_benches, state_get_bench, config)

        if not results:
            console.print("[yellow]No benches found or NGINX not available.[/yellow]")
            return

        table = Table(title="Proxy Sync Results")
        table.add_column("Bench", style="cyan")
        table.add_column("Status", style="green")

        for bench_name, success in results.items():
            status = "[green]Success[/green]" if success else "[red]Failed[/red]"
            table.add_row(bench_name, status)

        console.print(table)

        successful = sum(1 for s in results.values() if s)
        total = len(results)
        console.print(f"\n[cyan]Synced {successful}/{total} benches successfully.[/cyan]")
    except Exception as exc:
        _handle_error(exc)


if __name__ == "__main__":
    app()
