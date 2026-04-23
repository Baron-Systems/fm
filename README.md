# fm - Frappe Manager CLI

`fm` is a production-oriented CLI to provision and manage multi-bench ERPNext stacks with Docker Compose and Traefik.

## Highlights

- Strong validation before create (domain, Docker binaries, Docker network)
- Fault-tolerant `create` with rollback (`docker compose down -v` + directory cleanup)
- Health checks with retry (DB `3306`, backend `8000`) instead of fixed sleep
- Secure generated credentials (no hardcoded `admin/admin`)
- Config-driven defaults via `~/.fm/config.yaml`
- Rich UX + structured logging
- Bench status and list views including status/domain metadata

## Install

### Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
fm --help
```

### pipx from GitHub

```bash
pipx install git+https://github.com/<user>/<repo>
```

## Commands

```bash
fm create <name> <domain>
fm start [name]
fm stop [name]
fm restart [name]
fm delete [name]
fm list
fm status <name>
fm info [name]
fm health <name>
fm logs [name] [--service backend] [--follow/--no-follow]
fm shell <name> [--site mysite.example.com]
```

## Example

```bash
fm create acme acme.example.com
fm list
fm status acme
fm logs acme --service frontend
fm stop acme
fm start acme
fm delete acme
```

`fm delete` asks:

`Are you sure? This will delete all data (y/N)`

Only exact `y` proceeds.

Interactive mode:

- If `name` is omitted for `info`, `start`, `stop`, `restart`, `delete`, or `logs`,
  `fm` opens an interactive bench selector (arrow keys + Enter).

## Configuration

`fm` auto-creates `~/.fm/config.yaml` on first run.

Example:

```yaml
paths:
  benches_dir: benches
docker:
  network: web
erpnext:
  certresolver: le
  images:
    erpnext: frappe/erpnext:v16
    mariadb: mariadb:10.6
    redis: redis:7-alpine
defaults:
  db_root_password: null
  admin_password: null
logging:
  write_file: false
  file: ~/.fm/fm.log
```

Notes:

- If password defaults are `null`, secure random values are generated at create time.
- Credentials are saved in `benches/<name>/.credentials.json` with restricted permissions.

## Requirements

- Docker + Docker Compose plugin installed
- Existing Docker network `web` (or configure another in `~/.fm/config.yaml`)
- Traefik configured with `websecure` entrypoint and matching `certresolver`

## Repo bootstrap

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<user>/<repo>
git push -u origin main
```

```bash
pipx install git+https://github.com/<user>/<repo>
```
