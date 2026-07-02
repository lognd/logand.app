#!/bin/sh
# One-time setup for a fresh Ubuntu/Debian VPS -- installs everything
# docs/deployment.md's manual first-deploy walkthrough needs (Docker +
# Compose plugin, Node for the one-time manual frontend build, git,
# firewall rules). Idempotent -- safe to re-run; every step either
# checks "is this already done?" first or is a no-op if repeated.
#
# Usage: run as a user with sudo access.
#   curl -fsSL https://raw.githubusercontent.com/<you>/logand.app/main/ops/setup-vps.sh | sh
# or, having already cloned the repo:
#   sh ops/setup-vps.sh
#
# What this does NOT do (deliberately -- see docs/deployment.md for
# these as explicit, reviewed steps rather than something a curl|sh
# script silently decides for you):
#   - clone the repo
#   - write backend/.env (see docs/secrets.md's go-live checklist)
#   - configure DNS
#   - run docker compose up
set -eu

log() { printf '\n==> %s\n' "$1"; }

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This script only supports Ubuntu/Debian (apt-get not found)." >&2
    echo "See docs/deployment.md for the manual equivalent on other distros." >&2
    exit 1
fi

log "Updating package index"
$SUDO apt-get update -qq

log "Installing base packages (git, curl, ca-certificates, ufw)"
$SUDO apt-get install -y -qq git curl ca-certificates ufw gnupg

# -- Docker Engine + Compose plugin (official apt repository, not the
#    curl|sh convenience script -- pinned/auditable, and idempotent to
#    re-run since it just re-adds the same repo config each time). --
if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker Engine + Compose plugin"
    $SUDO install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.asc ]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO tee /etc/apt/keyrings/docker.asc >/dev/null
        $SUDO chmod a+r /etc/apt/keyrings/docker.asc
    fi
    ARCH=$(dpkg --print-architecture)
    CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME}")
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
    log "Docker already installed, skipping"
fi

# Let the invoking user run docker without sudo -- takes effect on next
# login/shell, not this one (group membership is read at login time).
if [ -n "${SUDO}" ] && ! id -nG "$(whoami)" | grep -qw docker; then
    log "Adding $(whoami) to the docker group (log out and back in for this to take effect)"
    $SUDO usermod -aG docker "$(whoami)"
fi

# -- Node.js (LTS) -- only needed for docs/deployment.md's manual
#    first-deploy frontend build (`npm run build`); ongoing deploys via
#    .github/workflows/deploy.yml build the frontend in CI instead, not
#    on the VPS, so this is a one-time convenience, not a permanent
#    dependency of the running stack. --
if ! command -v node >/dev/null 2>&1; then
    log "Installing Node.js LTS"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E sh - >/dev/null
    $SUDO apt-get install -y -qq nodejs
else
    log "Node.js already installed ($(node --version)), skipping"
fi

# -- Firewall: only what the site actually needs exposed. --
log "Configuring ufw (allow 22/tcp, 80/tcp, 443/tcp; deny everything else incoming)"
$SUDO ufw allow 22/tcp >/dev/null
$SUDO ufw allow 80/tcp >/dev/null
$SUDO ufw allow 443/tcp >/dev/null
$SUDO ufw --force enable >/dev/null

log "Done."
echo "Installed: $(docker --version), $(docker compose version --short 2>/dev/null || echo 'compose plugin ok'), $(node --version), $(git --version)"
echo ""
echo "Next steps (see docs/deployment.md):"
echo "  1. git clone <this-repo-url> logand.app && cd logand.app"
echo "  2. cp backend/.env.example backend/.env, fill in real values"
echo "     (see docs/secrets.md's Go-live checklist)"
echo "  3. cd frontend && npm ci && npm run build && cd .."
echo "  4. docker compose up -d postgres redis"
echo "  5. docker compose --profile migrate run --rm migrate"
echo "  6. docker compose up -d backend caddy backup"
