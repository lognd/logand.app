#!/bin/sh
# One-time setup for a fresh Ubuntu/Debian VPS -- installs everything
# docs/deployment.md's manual first-deploy walkthrough needs (Docker +
# Compose plugin, Node for the one-time manual frontend build, git,
# firewall rules) and provisions a non-root service account
# (SERVICE_USER) to run the stack, so root SSH access is only ever
# needed for host-level setup, not day-to-day operation. Idempotent --
# safe to re-run; every step either checks "is this already done?"
# first or is a no-op if repeated.
#
# Usage: run as root (fresh VPS default) or a user with sudo access.
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
#   - disable root SSH login (do this yourself once you've confirmed
#     `ssh <service-user>@<host>` works -- see the printed reminder
#     at the end of this script)
set -eu

SERVICE_USER="${SERVICE_USER:-logand}"

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

# -- Service account: the stack runs as SERVICE_USER, never as root or
#    the admin login used for setup -- keeps day-to-day operation
#    (docker compose, git pulls, .env access) off the root account. --
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    log "Creating service account '${SERVICE_USER}'"
    $SUDO useradd --create-home --shell /bin/bash "${SERVICE_USER}"
else
    log "Service account '${SERVICE_USER}' already exists, skipping"
fi

if ! id -nG "${SERVICE_USER}" | grep -qw docker; then
    log "Adding '${SERVICE_USER}' to the docker group"
    $SUDO usermod -aG docker "${SERVICE_USER}"
fi

# Give SERVICE_USER the same SSH access as whoever is running this
# script (root on a fresh VPS) -- copies authorized_keys rather than
# assuming a specific key, so it works with whatever key you added at
# server-creation time.
SERVICE_HOME=$(getent passwd "${SERVICE_USER}" | cut -d: -f6)
ADMIN_AUTHORIZED_KEYS="$HOME/.ssh/authorized_keys"
SERVICE_SSH_DIR="${SERVICE_HOME}/.ssh"
if [ -f "${ADMIN_AUTHORIZED_KEYS}" ] && [ ! -f "${SERVICE_SSH_DIR}/authorized_keys" ]; then
    log "Granting '${SERVICE_USER}' SSH access (copying authorized_keys)"
    $SUDO mkdir -p "${SERVICE_SSH_DIR}"
    $SUDO cp "${ADMIN_AUTHORIZED_KEYS}" "${SERVICE_SSH_DIR}/authorized_keys"
    $SUDO chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SERVICE_SSH_DIR}"
    $SUDO chmod 700 "${SERVICE_SSH_DIR}"
    $SUDO chmod 600 "${SERVICE_SSH_DIR}/authorized_keys"
fi

# -- Node.js (LTS) -- only needed for docs/deployment.md's manual
#    first-deploy frontend build (`npm run build`); ongoing deploys via
#    .github/workflows/deploy.yml build the frontend in CI instead, not
#    on the VPS, so this is a one-time convenience, not a permanent
#    dependency of the running stack. --
if ! command -v node >/dev/null 2>&1; then
    log "Installing Node.js LTS"
    if [ -n "${SUDO}" ]; then
        curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E sh - >/dev/null
    else
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sh - >/dev/null
    fi
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
echo "Next steps (see docs/deployment.md) -- run these as '${SERVICE_USER}', not root:"
echo "  0. ssh ${SERVICE_USER}@<this-host>   # confirm key-based login works before continuing"
echo "  1. git clone <this-repo-url> logand.app && cd logand.app"
echo "  2. cp backend/.env.example backend/.env, fill in real values"
echo "     (see docs/secrets.md's Go-live checklist)"
echo "  3. cd frontend && npm ci && npm run build && cd .."
echo "  4. docker compose up -d postgres redis"
echo "  5. docker compose --profile migrate run --rm migrate"
echo "  6. docker compose up -d backend caddy backup"
echo ""
echo "Once step 0 is confirmed working, lock root SSH login down yourself"
echo "(this script won't do it for you -- don't risk locking yourself out"
echo "automatically): edit /etc/ssh/sshd_config, set 'PermitRootLogin no',"
echo "then 'systemctl restart sshd'."
