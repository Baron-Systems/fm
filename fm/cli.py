from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import core

app = typer.Typer(help="Mini Frappe Manager for ERPNext Docker benches.")
console = Console()


def _handle_error(exc: Exception) -> None:
    console.print(f"[bold red]Error:[/bold red] {exc}")
    raise typer.Exit(code=1)


@app.command("create")
def create(name: str, domain: str) -> None:
    """Create a new bench and bootstrap ERPNext site."""
    try:
        console.print(f"[cyan]Creating bench[/cyan] [bold]{name}[/bold] for [bold]{domain}[/bold]")
        bench_dir = core.create_bench(name=name, domain=domain)
        console.print(f"[green]Bench created successfully:[/green] {bench_dir}")
    except Exception as exc:
        _handle_error(exc)


@app.command("start")
def start(name: str) -> None:
    """Start a bench."""
    try:
        core.start_bench(name)
        console.print(f"[green]Started bench:[/green] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("stop")
def stop(name: str) -> None:
    """Stop a bench."""
    try:
        core.stop_bench(name)
        console.print(f"[yellow]Stopped bench:[/yellow] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("restart")
def restart(name: str) -> None:
    """Restart a bench."""
    try:
        core.restart_bench(name)
        console.print(f"[green]Restarted bench:[/green] {name}")
    except Exception as exc:
        _handle_error(exc)


@app.command("delete")
def delete(name: str, force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")) -> None:
    """Delete a bench and its files."""
    try:
        if not force:
            confirmed = typer.confirm(f"Delete bench '{name}' and all data?")
            if not confirmed:
                console.print("[yellow]Delete cancelled.[/yellow]")
                raise typer.Exit(code=0)
        core.delete_bench(name)
        console.print(f"[green]Deleted bench:[/green] {name}")
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("list")
def list_cmd() -> None:
    """List available benches."""
    benches = core.list_benches()
    if not benches:
        console.print("[yellow]No benches found.[/yellow]")
        return

    table = Table(title="ERPNext Benches")
    table.add_column("Name", style="cyan", no_wrap=True)
    for bench in benches:
        table.add_row(bench)
    console.print(table)


@app.command("logs")
def logs(
    name: str,
    service: str | None = typer.Option(None, "--service", "-s", help="Service name"),
    lines: int = typer.Option(100, "--lines", "-n", min=1, help="Number of log lines"),
) -> None:
    """Show docker compose logs for a bench."""
    try:
        output = core.bench_logs(name=name, service=service, lines=lines)
        console.print(output if output.strip() else "[yellow]No logs available.[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@app.command("health")
def health(name: str) -> None:
    """Show docker compose status for a bench."""
    try:
        output = core.bench_health(name=name)
        console.print(output if output.strip() else "[yellow]No status output.[/yellow]")
    except Exception as exc:
        _handle_error(exc)


@app.command("shell")
def shell(
    name: str,
    site: str | None = typer.Option(None, "--site", help="Open bench console for a specific site"),
) -> None:
    """Open interactive shell in backend container or site console."""
    try:
        if site:
            console.print(f"[cyan]Opening bench console for site[/cyan] [bold]{site}[/bold]")
            core.open_site_console(name=name, site=site)
        else:
            console.print(f"[cyan]Opening backend shell for bench[/cyan] [bold]{name}[/bold]")
            core.open_bench_shell(name=name)
    except Exception as exc:
        _handle_error(exc)


if __name__ == "__main__":
    app()
