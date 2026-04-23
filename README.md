# fm - Mini Frappe Manager

`fm` is a production-ready Python CLI for managing multi-bench ERPNext deployments with Docker Compose and Traefik.

## Features

- Create isolated ERPNext benches under `benches/<name>/`
- Generate bench-specific `docker-compose.yml` from Jinja2 template
- Start, stop, restart, delete, and list benches
- Bootstrap ERPNext site automatically (`bench new-site` + `install-app erpnext`)
- Traefik labels for HTTPS routing with Let's Encrypt resolver
- Optional logs and health commands

## Installation

### Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
fm --help
```

### pipx (GitHub)

```bash
pipx install git+https://github.com/<user>/<repo>
```

## Usage

```bash
fm create <name> <domain>
fm start <name>
fm stop <name>
fm restart <name>
fm delete <name>
fm list
```

Optional commands:

```bash
fm logs <name> --service backend --lines 200
fm health <name>
```

## Example

```bash
fm create acme acme.example.com
fm list
fm health acme
fm logs acme --service frontend
fm stop acme
fm start acme
fm delete acme --force
```

## Operational Notes

- Ensure Docker and Docker Compose plugin are installed (`docker compose version`)
- Ensure Traefik is already running on your host network with `websecure` entrypoint and `le` certresolver
- Default bootstrap credentials are `admin/admin` (change immediately in production)
- Bench creation waits for a fixed startup delay before running `bench` commands

## Repository bootstrap

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<user>/<repo>
git push -u origin main
```

Then install with:

```bash
pipx install git+https://github.com/<user>/<repo>
```
