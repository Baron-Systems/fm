"""Cloudflare Tunnel Manager for FM Tool"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any

import yaml
from rich.console import Console

from . import docker

console = Console()
CLOUDFLARE_DIR = Path.home() / ".fm" / "cloudflare"


def setup_tunnel(token: str, email: str) -> None:
    """Setup Cloudflare Tunnel configuration and files."""
    
    # Ensure cloudflare directory exists
    CLOUDFLARE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create docker-compose.yml
    compose_content = f"""version: '3.8'

services:
  cloudflare-tunnel:
    image: cloudflare/cloudflared:latest
    container_name: cloudflare-tunnel
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN={token}
    networks:
      - web
    depends_on:
      - traefik

  traefik:
    image: traefik:v3.0
    container_name: traefik
    restart: unless-stopped
    command:
      - --api.insecure=true
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.websecure.address=:443
      - --entrypoints.web.address=:80
      - --certificatesresolvers.letsencrypt.acme.httpchallenge=true
      - --certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web
      - --certificatesresolvers.letsencrypt.acme.email={email}
      - --certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json
      - --log.level=INFO
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"  # Traefik dashboard
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    networks:
      - web
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.traefik.rule=Host(`traefik.mby-solution.vip`)"
      - "traefik.http.routers.traefik.entrypoints=websecure"
      - "traefik.http.routers.traefik.tls.certresolver=letsencrypt"
      - "traefik.http.services.traefik.loadbalancer.server.port=8080"

networks:
  web:
    external: true

volumes:
  letsencrypt:
"""
    
    # Write docker-compose.yml
    compose_file = CLOUDFLARE_DIR / "docker-compose.yml"
    compose_file.write_text(compose_content, encoding="utf-8")
    
    # Create .env file
    env_content = f"""TUNNEL_TOKEN={token}
ACME_EMAIL={email}
"""
    env_file = CLOUDFLARE_DIR / ".env"
    env_file.write_text(env_content, encoding="utf-8")
    
    console.print(f"✅ Configuration saved to {CLOUDFLARE_DIR}")


def start_services() -> None:
    """Start Cloudflare Tunnel and Traefik services."""
    
    if not CLOUDFLARE_DIR.exists():
        raise FileNotFoundError("Cloudflare configuration not found. Run 'fm cloudflare token' first.")
    
    # Ensure web network exists
    docker.ensure_docker_network("web")
    
    # Start services
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=CLOUDFLARE_DIR,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start services: {result.stderr}")
    
    console.print("✅ Services started successfully")


def stop_services() -> None:
    """Stop Cloudflare Tunnel and Traefik services."""
    
    if not CLOUDFLARE_DIR.exists():
        console.print("ℹ️  No Cloudflare configuration found")
        return
    
    # Stop services
    result = subprocess.run(
        ["docker", "compose", "down"],
        cwd=CLOUDFLARE_DIR,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Failed to stop services: {result.stderr}")
    
    console.print("✅ Services stopped successfully")


def get_status() -> Dict[str, Any]:
    """Get status of Cloudflare Tunnel services."""
    
    status = {}
    
    # Check cloudflare-tunnel
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=cloudflare-tunnel", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            name, state = result.stdout.strip().split("\t")
            status["cloudflare-tunnel"] = {
                "running": "Up" in state,
                "url": "N/A"
            }
        else:
            status["cloudflare-tunnel"] = {
                "running": False,
                "url": "N/A"
            }
    except Exception:
        status["cloudflare-tunnel"] = {"running": False, "url": "N/A"}
    
    # Check traefik
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=traefik", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            name, state = result.stdout.strip().split("\t")
            status["traefik"] = {
                "running": "Up" in state,
                "url": "http://traefik.mby-solution.vip:8080"
            }
        else:
            status["traefik"] = {
                "running": False,
                "url": "http://traefik.mby-solution.vip:8080"
            }
    except Exception:
        status["traefik"] = {"running": False, "url": "http://traefik.mby-solution.vip:8080"}
    
    return status
