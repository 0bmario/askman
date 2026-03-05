#!/bin/bash
set -euo pipefail

REPO="0bmario/askman"
REQUESTED_VERSION="${ASKMAN_VERSION:-}"

usage() {
  cat <<'EOF'
Install askman from GitHub releases.

Usage:
  install.sh [--version vX.Y.Z]
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      [ $# -ge 2 ] || { echo "Error: --version requires a value."; exit 1; }
      REQUESTED_VERSION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [ -n "$REQUESTED_VERSION" ] && [[ "$REQUESTED_VERSION" != v* ]]; then
  REQUESTED_VERSION="v${REQUESTED_VERSION}"
fi

# Determine OS
OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM="linux" ;;
  Darwin*) PLATFORM="macos" ;;
  *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

# Determine Architecture
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  ARCH_SUFFIX="x86_64" ;;
  arm64|aarch64)
    if [ "$PLATFORM" = "linux" ]; then
      echo "Unsupported Architecture: $ARCH on Linux (linux-aarch64 release is not available)"
      exit 1
    fi
    ARCH_SUFFIX="aarch64"
    ;;
  *) echo "Unsupported Architecture: $ARCH"; exit 1 ;;
esac

ASSET_NAME="askman-${PLATFORM}-${ARCH_SUFFIX}.tar.gz"

if [ -n "$REQUESTED_VERSION" ]; then
  TAG="$REQUESTED_VERSION"
else
  echo "Detecting latest release for askman..."
  TAG="$(
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
      | sed -nE 's/^[[:space:]]*"tag_name":[[:space:]]*"([^"]+)".*/\1/p' \
      | head -n1
  )"
fi

if [ -z "$TAG" ] || [ "$TAG" = "null" ]; then
  echo "Error: Could not fetch release tag."
  exit 1
fi

RELEASE_BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
DOWNLOAD_URL="${RELEASE_BASE_URL}/${ASSET_NAME}"
CHECKSUM_URL="${RELEASE_BASE_URL}/${ASSET_NAME}.sha256"

echo "Downloading askman ${TAG} for ${PLATFORM} (${ARCH_SUFFIX})..."
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/askman-installer.XXXXXX") || { echo "Error: Failed to create temporary directory."; exit 1; }
trap 'if [ -n "${TEMP_DIR:-}" ] && [ -d "$TEMP_DIR" ]; then rm -rf "$TEMP_DIR"; fi' EXIT INT TERM

if curl -sSfL "$DOWNLOAD_URL" -o "${TEMP_DIR}/${ASSET_NAME}" && \
   curl -sSfL "$CHECKSUM_URL" -o "${TEMP_DIR}/${ASSET_NAME}.sha256"; then
  :
else
  echo "Failed to download release assets from $RELEASE_BASE_URL"
  exit 1
fi

echo "Verifying checksum..."
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$TEMP_DIR" && sha256sum -c "${ASSET_NAME}.sha256")
elif command -v shasum >/dev/null 2>&1; then
  (cd "$TEMP_DIR" && shasum -a 256 -c "${ASSET_NAME}.sha256")
else
  echo "Error: checksum verification requires sha256sum or shasum in PATH."
  exit 1
fi

echo "Extracting..."
tar -xzf "${TEMP_DIR}/${ASSET_NAME}" -C "$TEMP_DIR"

# Install to ~/.local/bin (no sudo required)
INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "$INSTALL_DIR"
mv "${TEMP_DIR}/askman" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/askman"

# Check if INSTALL_DIR is in PATH
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
  echo
  echo "WARNING: $INSTALL_DIR is not in your PATH."
  echo "Add it by running:"
  echo
  if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  else
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
  fi
  echo
fi

echo
echo "Askman ${TAG} installed successfully to $INSTALL_DIR/askman"
echo "Run 'askman <query>' to get started."
