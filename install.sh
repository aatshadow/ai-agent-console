#!/usr/bin/env bash
# ai-agent-console — bootstrap installer for fresh Ubuntu/Debian VPS.
set -euo pipefail

# ── output helpers ──────────────────────────────────────────────────────────
C_GREEN=$'\033[0;32m'; C_CYAN=$'\033[0;36m'; C_YELLOW=$'\033[0;33m'
C_RED=$'\033[0;31m';   C_RESET=$'\033[0m'
QUIET=0
say()  { [[ "$QUIET" == "1" ]] || echo "${C_GREEN}[✓]${C_RESET} $*"; }
step() { [[ "$QUIET" == "1" ]] || echo "${C_CYAN}[→]${C_RESET} $*"; }
warn() { echo "${C_YELLOW}[!]${C_RESET} $*" >&2; }
die()  { echo "${C_RED}[✗]${C_RESET} $*" >&2; exit 1; }

# ── flags ───────────────────────────────────────────────────────────────────
NO_TAILSCALE=0; NO_WIZARD=0
for arg in "$@"; do
  case "$arg" in
    --no-tailscale) NO_TAILSCALE=1 ;;
    --no-wizard)    NO_WIZARD=1 ;;
    --quiet)        QUIET=1 ;;
    -h|--help)
      cat <<EOF
usage: install.sh [--no-tailscale] [--no-wizard] [--quiet]
EOF
      exit 0 ;;
    *) die "unknown flag: $arg" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ── 1. OS detection ─────────────────────────────────────────────────────────
step "detecting OS"
[[ -r /etc/os-release ]] || die "cannot read /etc/os-release — unsupported system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) say "OS: $PRETTY_NAME" ;;
  *) die "only Ubuntu/Debian supported (detected: ${ID:-unknown})" ;;
esac

SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

# ── 2. system deps ──────────────────────────────────────────────────────────
step "installing system packages (git, tmux, python3, sqlite3, curl, jq)"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
  git tmux python3 python3-pip python3-venv sqlite3 curl jq >/dev/null
say "system deps installed"

# ── 3. tailscale (optional) ─────────────────────────────────────────────────
if [[ "$NO_TAILSCALE" == "0" ]]; then
  if command -v tailscale >/dev/null 2>&1; then
    say "tailscale already installed"
  else
    read -rp "¿Instalar Tailscale para conectar con otras VPS? [y/N] " ans
    if [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]; then
      step "installing tailscale"
      curl -fsSL https://tailscale.com/install.sh | sh
      step "ejecutando tailscale up (puede pedirte autenticación web)"
      $SUDO tailscale up || warn "tailscale up no terminó; corre 'sudo tailscale up' manualmente"
      say "tailscale listo"
    else
      warn "saltando tailscale"
    fi
  fi
fi

# ── 4. project scaffolding ──────────────────────────────────────────────────
step "creando estructura agent/"
ROLES=(researcher designer watcher analyst extractor changewatcher taskmaster)
for r in "${ROLES[@]}"; do mkdir -p "agent/memory/$r"; done
mkdir -p agent/journal agent/data agent/logs agent/agents

# copy role templates (if already present)
TPL_ROLES="$REPO_ROOT/.claude/skills/agent-console/templates/roles"
if [[ -d "$TPL_ROLES" ]]; then
  shopt -s nullglob
  copied=0
  for f in "$TPL_ROLES"/*.md; do
    dest="agent/agents/$(basename "$f")"
    [[ -e "$dest" ]] || { cp "$f" "$dest"; copied=$((copied+1)); }
  done
  shopt -u nullglob
  say "role templates copiados: $copied"
else
  warn "no hay templates/roles/ aún (el subagente-libs los crea)"
fi
say "estructura agent/ lista"

# ── 5. python venv ──────────────────────────────────────────────────────────
if [[ ! -d venv ]]; then
  step "creando venv en ./venv"
  python3 -m venv venv
fi
step "instalando python deps"
# Only non-obvious: uvicorn[standard] pulls httptools+uvloop for bridge perf.
./venv/bin/pip install --quiet --upgrade pip >/dev/null
./venv/bin/pip install --quiet \
  fastapi "uvicorn[standard]" anthropic python-dotenv \
  requests pyyaml pandas >/dev/null
say "venv listo"

# ── 6. init DB ──────────────────────────────────────────────────────────────
step "inicializando SQLite"
# lib.db path contains a hyphen so we must import via importlib + sys.path.
./venv/bin/python - <<PY || warn "init_db() falló; lib/db.py puede no existir aún"
import sys, importlib.util, pathlib
root = pathlib.Path("$REPO_ROOT").resolve()
lib_path = root / ".claude" / "skills" / "agent-console" / "lib" / "db.py"
if not lib_path.exists():
    sys.stderr.write(f"skip: {lib_path} missing\n"); sys.exit(0)
spec = importlib.util.spec_from_file_location("aac_db", lib_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
mod.init_db()
print("db ready")
PY

# ── 7. wizard ───────────────────────────────────────────────────────────────
if [[ "$NO_WIZARD" == "0" ]]; then
  step "lanzando wizard de onboarding"
  ./venv/bin/python wizard.py
else
  say "instalación completa — corre 'python3 wizard.py' cuando quieras configurar"
fi
