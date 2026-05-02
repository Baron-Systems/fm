#!/bin/bash
# Setup Cloudflare Tunnel and Traefik

set -e

echo "🌐 Setting up Cloudflare Tunnel and Traefik..."

# Check if TUNNEL_TOKEN is set
if [ -z "$TUNNEL_TOKEN" ]; then
    echo "❌ Error: TUNNEL_TOKEN environment variable is required"
    echo "Please set it: export TUNNEL_TOKEN=your_token_here"
    exit 1
fi

# Check if ACME_EMAIL is set
if [ -z "$ACME_EMAIL" ]; then
    echo "❌ Error: ACME_EMAIL environment variable is required"
    echo "Please set it: export ACME_EMAIL=your@email.com"
    exit 1
fi

# Create cloudflare directory
mkdir -p cloudflare
cd cloudflare

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  cloudflare-tunnel:
    image: cloudflare/cloudflared:latest
    container_name: cloudflare-tunnel
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=${TUNNEL_TOKEN}
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
      - --certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}
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
EOF

# Create .env file
cat > .env << EOF
TUNNEL_TOKEN=${TUNNEL_TOKEN}
ACME_EMAIL=${ACME_EMAIL}
EOF

echo "✅ Cloudflare Tunnel setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Start the services: cd cloudflare && docker-compose up -d"
echo "2. Check Traefik dashboard: http://traefik.mby-solution.vip:8080"
echo "3. Create your benches: fm create site1 site1.mby-solution.vip"
echo ""
echo "🌐 Your sites will be accessible through Cloudflare Tunnel!"
