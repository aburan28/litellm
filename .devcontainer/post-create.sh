#!/usr/bin/env bash
set -e

UV_VERSION="0.10.9"
UV_INSTALLER_SHA256="7fc46e39cb97290b57169c0c813a17970585ac519139f19006453c99b5f2f45f"

echo "[post-create] Installing uv"
UV_INSTALLER_PATH="$(mktemp "${TMPDIR:-/tmp}/litellm-uv-install.XXXXXX")"
cleanup_uv_installer() { rm -f "$UV_INSTALLER_PATH"; }
trap cleanup_uv_installer 0
trap 'exit 1' HUP INT TERM
curl -LsSf -o "$UV_INSTALLER_PATH" "https://astral.sh/uv/${UV_VERSION}/install.sh"
if command -v sha256sum >/dev/null 2>&1; then
  UV_INSTALLER_ACTUAL_SHA256="$(sha256sum "$UV_INSTALLER_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  UV_INSTALLER_ACTUAL_SHA256="$(shasum -a 256 "$UV_INSTALLER_PATH" | awk '{print $1}')"
else
  echo "[post-create] A SHA-256 utility (sha256sum or shasum) is required to install uv" >&2
  exit 1
fi
if [ "$UV_INSTALLER_ACTUAL_SHA256" != "$UV_INSTALLER_SHA256" ]; then
  echo "[post-create] uv installer checksum verification failed" >&2
  exit 1
fi
env UV_NO_MODIFY_PATH=1 sh "$UV_INSTALLER_PATH"
cleanup_uv_installer
UV_INSTALLER_PATH=""
trap - 0 HUP INT TERM
export PATH="$HOME/.local/bin:$PATH"

echo "[post-create] Installing Python dependencies (uv)"
uv sync --frozen --group proxy-dev --extra proxy

echo "[post-create] Generating Prisma client"
uv run --no-sync prisma generate

echo "[post-create] Installing npm dependencies"
cd ui/litellm-dashboard && npm ci

echo "[post-create] Done"
