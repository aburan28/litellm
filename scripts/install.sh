#!/usr/bin/env bash
# LiteLLM Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/BerriAI/litellm/main/scripts/install.sh | sh
#
# Needs curl and either sha256sum or shasum: uv is bootstrapped if missing, and uv
# provisions a compatible Python itself (reusing a suitable system one, else downloading a managed build).
#
# To install from an unreleased branch, tag, or commit instead of the latest PyPI
# release, set LITELLM_CLI_REF:
#   curl -fsSL https://raw.githubusercontent.com/BerriAI/litellm/<branch>/scripts/install.sh | \
#     LITELLM_CLI_REF=<branch> sh
#
# NOTE: set -e without pipefail for POSIX sh compatibility (dash on Ubuntu/Debian
# ignores the shebang when invoked as `sh` and does not support `pipefail`).
set -eu

# NOTE: before merging, this must stay as "litellm[proxy]" to install from PyPI.
# LITELLM_CLI_REF opts into installing from a branch, tag, or commit instead (for
# example, to QA lite autoroute against an unreleased branch, which needs this proxy
# runtime, not the thin litellm[cli] install).
if [ -n "${LITELLM_CLI_REF:-}" ]; then
  LITELLM_PACKAGE="litellm[proxy] @ git+https://github.com/BerriAI/litellm.git@${LITELLM_CLI_REF}"
else
  LITELLM_PACKAGE="litellm[proxy]"
fi
UV_VERSION="0.10.9"
UV_INSTALLER_SHA256="7fc46e39cb97290b57169c0c813a17970585ac519139f19006453c99b5f2f45f"

# ── colours ────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD='\033[1m'
  GREEN='\033[38;2;78;186;101m'
  GREY='\033[38;2;153;153;153m'
  RESET='\033[0m'
else
  BOLD='' GREEN='' GREY='' RESET=''
fi

info()    { printf "${GREY}  %s${RESET}\n" "$*"; }
success() { printf "${GREEN}  ✔ %s${RESET}\n" "$*"; }
header()  { printf "${BOLD}  %s${RESET}\n" "$*"; }
die()     { printf "\n  Error: %s\n\n" "$*" >&2; exit 1; }

# ── banner ─────────────────────────────────────────────────────────────────
echo ""
cat << 'EOF'
  ██╗     ██╗████████╗███████╗██╗     ██╗     ███╗   ███╗
  ██║     ██║╚══██╔══╝██╔════╝██║     ██║     ████╗ ████║
  ██║     ██║   ██║   █████╗  ██║     ██║     ██╔████╔██║
  ██║     ██║   ██║   ██╔══╝  ██║     ██║     ██║╚██╔╝██║
  ███████╗██║   ██║   ███████╗███████╗███████╗██║ ╚═╝ ██║
  ╚══════╝╚═╝   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝     ╚═╝
EOF
printf "  ${BOLD}LiteLLM Installer${RESET}  ${GREY}— unified gateway for 100+ LLM providers${RESET}\n\n"

# ── OS detection ───────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)  PLATFORM="macOS ($ARCH)" ;;
  Linux)   PLATFORM="Linux ($ARCH)" ;;
  *)       die "Unsupported OS: $OS. LiteLLM supports macOS and Linux." ;;
esac

info "Platform: $PLATFORM"

# ── uv detection / install ────────────────────────────────────────────────
UV_BIN=""
CURRENT_UV_VERSION=""
for candidate in uv "$HOME/.local/bin/uv"; do
  if command -v "$candidate" >/dev/null 2>&1; then
    UV_BIN="$(command -v "$candidate")"
    break
  elif [ -x "$candidate" ]; then
    UV_BIN="$candidate"
    break
  fi
done

if [ -n "$UV_BIN" ]; then
  CURRENT_UV_VERSION="$("$UV_BIN" --version 2>/dev/null | awk '{print $2}' | head -1 || true)"
fi

if [ -z "$UV_BIN" ] || [ "${CURRENT_UV_VERSION:-}" != "$UV_VERSION" ]; then
  header "Installing uv…"
  if [ -n "${CURRENT_UV_VERSION:-}" ]; then
    info "Upgrading uv from ${CURRENT_UV_VERSION} to ${UV_VERSION}"
  fi
  UV_INSTALLER_DIR="$(mktemp -d "${TMPDIR:-/tmp}/litellm-uv-install.XXXXXX")" \
    || die "Could not create a temporary directory for the uv installer"
  UV_INSTALLER_PATH="${UV_INSTALLER_DIR}/uv-installer.sh"
  cleanup_uv_installer() { rm -rf "$UV_INSTALLER_DIR"; }
  trap cleanup_uv_installer 0
  trap 'exit 1' HUP INT TERM
  curl --proto '=https' --tlsv1.2 -LsSf -o "$UV_INSTALLER_PATH" \
    "https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/uv-installer.sh" \
    || die "Could not download the uv installer"
  if command -v sha256sum >/dev/null 2>&1; then
    UV_INSTALLER_ACTUAL_SHA256="$(sha256sum "$UV_INSTALLER_PATH" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    UV_INSTALLER_ACTUAL_SHA256="$(shasum -a 256 "$UV_INSTALLER_PATH" | awk '{print $1}')"
  else
    die "A SHA-256 utility (sha256sum or shasum) is required to install uv"
  fi
  [ "$UV_INSTALLER_ACTUAL_SHA256" = "$UV_INSTALLER_SHA256" ] \
    || die "uv installer checksum verification failed"
  UV_CURL_BIN="$(command -v curl)"
  case "$UV_CURL_BIN" in
    /*) ;;
    *) die "curl must resolve to an absolute path" ;;
  esac
  cat > "${UV_INSTALLER_DIR}/curl" <<'EOF'
#!/bin/sh
set -eu

"$LITELLM_UV_REAL_CURL" --proto '=https' --tlsv1.2 "$@"

UV_ARCHIVE_URL=""
UV_ARCHIVE_PATH=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) UV_ARCHIVE_PATH="$2"; shift 2 ;;
    https://*) UV_ARCHIVE_URL="$1"; shift ;;
    *) shift ;;
  esac
done

UV_ARCHIVE_NAME="${UV_ARCHIVE_URL##*/}"
case "$UV_ARCHIVE_NAME" in
  uv-aarch64-apple-darwin.tar.gz) UV_ARCHIVE_SHA256="a92f61e9ac9b0f29668c15f56152e4a60143fca148ff5bfadb86718472c3f376" ;;
  uv-x86_64-apple-darwin.tar.gz) UV_ARCHIVE_SHA256="9cc2de7d195fa157f98b306a8a1cb151ded93f488939b93363cebc8b9d598c28" ;;
  uv-aarch64-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="cc0c5a8573e7d6d78aecb954e0a62b5c0d18217bb81f1e19363b428c57a9962a" ;;
  uv-aarch64-unknown-linux-musl.tar.gz) UV_ARCHIVE_SHA256="05b0d3087e913ebe11756365a90dd47c05d6728752fdbe129ad4c3ccd769826d" ;;
  uv-arm-unknown-linux-musleabihf.tar.gz) UV_ARCHIVE_SHA256="6220fa3eb5f8212cae4ec3a5053060914aaa829549cf706dde9f9cc344f75f61" ;;
  uv-armv7-unknown-linux-gnueabihf.tar.gz) UV_ARCHIVE_SHA256="0076eac165c2f7129627e2297478e7ffbb9465d9ae6a8961b2f53dcbd807473d" ;;
  uv-armv7-unknown-linux-musleabihf.tar.gz) UV_ARCHIVE_SHA256="f702e821b80e371e14987a886d58ee103c5948b7b096fa49a552624c24d7e073" ;;
  uv-i686-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="90d9168a4e7900463f9fd79a32eb1890081fb1e238d803404f6e17b2dcdcca7b" ;;
  uv-i686-unknown-linux-musl.tar.gz) UV_ARCHIVE_SHA256="1d42b0d0a037b3d658b11ec889154686db3ab269ba2b789bdbc45d36e3549f34" ;;
  uv-powerpc64le-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="e804f4a7d0659e09ef806365f04bdd33c940603fab903e925402748d05dd109a" ;;
  uv-riscv64gc-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="1541596da45855e34202130027a613a2ace7d441e04d747cb4dd9f2590461c9a" ;;
  uv-s390x-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="a589d4a8930c82fa7225daec19c632651b3c84f50f770efe758056b387e5f0dd" ;;
  uv-x86_64-unknown-linux-gnu.tar.gz) UV_ARCHIVE_SHA256="20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594" ;;
  uv-x86_64-unknown-linux-musl.tar.gz) UV_ARCHIVE_SHA256="433e56874739e92c7cfd661ba9e5f287b376ca612c08c8194a41a98a13158aea" ;;
  *) echo "uv archive is not in the repository checksum allowlist: $UV_ARCHIVE_NAME" >&2; exit 1 ;;
esac

if command -v sha256sum >/dev/null 2>&1; then
  UV_ARCHIVE_ACTUAL_SHA256="$(sha256sum "$UV_ARCHIVE_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  UV_ARCHIVE_ACTUAL_SHA256="$(shasum -a 256 "$UV_ARCHIVE_PATH" | awk '{print $1}')"
else
  echo "A SHA-256 utility is required to verify the uv archive" >&2
  exit 1
fi
[ "$UV_ARCHIVE_ACTUAL_SHA256" = "$UV_ARCHIVE_SHA256" ] \
  || { echo "uv archive checksum verification failed" >&2; exit 1; }
EOF
  chmod 0700 "${UV_INSTALLER_DIR}/curl"
  env PATH="${UV_INSTALLER_DIR}:$PATH" LITELLM_UV_REAL_CURL="$UV_CURL_BIN" UV_NO_MODIFY_PATH=1 \
    sh "$UV_INSTALLER_PATH" || die "uv installation failed"
  cleanup_uv_installer
  UV_INSTALLER_DIR=""
  UV_INSTALLER_PATH=""
  trap - 0 HUP INT TERM
  UV_BIN="$HOME/.local/bin/uv"
fi

# ── install ────────────────────────────────────────────────────────────────
echo ""
if [ -n "${LITELLM_CLI_REF:-}" ]; then
  header "Installing litellm[proxy] from ${LITELLM_CLI_REF}…"
else
  header "Installing litellm[proxy]…"
fi
echo ""

# --python mirrors requires-python in pyproject.toml (keep in sync): uv selects the
# interpreter before resolving, so an unconstrained request accepts a too-old system
# Python (stock macOS ships 3.9) and fails resolution instead of downloading a
# managed one. --python-preference system still reuses a compatible system Python.
"$UV_BIN" tool install --python '>=3.10,<3.15' --python-preference system --force "${LITELLM_PACKAGE}" \
  || die "uv tool install failed. Try manually: $UV_BIN tool install --python '>=3.10,<3.15' '${LITELLM_PACKAGE}'"

# ── find the litellm binary installed by uv tool ───────────────────────────
SCRIPTS_DIR="$("$UV_BIN" tool dir --bin)"
LITELLM_BIN="${SCRIPTS_DIR}/litellm"

if [ ! -x "$LITELLM_BIN" ]; then
  die "litellm binary not found after install. Try: $UV_BIN tool install '${LITELLM_PACKAGE}'"
fi

# ── success banner ─────────────────────────────────────────────────────────
echo ""
success "LiteLLM installed"

installed_ver="$("$LITELLM_BIN" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
[ -n "$installed_ver" ] && info "Version: $installed_ver"

# ── PATH hint ──────────────────────────────────────────────────────────────
if ! command -v litellm >/dev/null 2>&1; then
  info "Note: add litellm to your PATH:  export PATH=\"\$PATH:${SCRIPTS_DIR}\""
fi

# ── launch setup wizard ────────────────────────────────────────────────────
echo ""
printf "  ${BOLD}Run the interactive setup wizard?${RESET} ${GREY}(Y/n)${RESET}: "
# /dev/tty may be unavailable in Docker/CI — default to yes if it can't be read
answer=""
if [ -r /dev/tty ]; then
  read -r answer </dev/tty || answer=""
fi

if [ -z "$answer" ] || [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
  echo ""
  # Use /dev/tty for interactive input when available (stdin is a pipe from curl)
  if [ -r /dev/tty ]; then
    exec "$LITELLM_BIN" --setup </dev/tty
  else
    exec "$LITELLM_BIN" --setup
  fi
else
  echo ""
  header "Quick start:"
  echo ""
  info "  litellm --setup          # interactive wizard"
  info "  litellm --model gpt-4o   # single-model quickstart"
  echo ""
  info "Docs: https://docs.litellm.ai"
  echo ""
fi
