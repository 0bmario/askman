#!/bin/bash
set -euo pipefail

REPO="0bmario/askman"
VERSION="${ASKMAN_VERSION:-}"

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
      VERSION="$2"
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

if [ -n "$VERSION" ] && [[ "$VERSION" != v* ]]; then
  VERSION="v${VERSION}"
fi

case "$(uname -s):$(uname -m)" in
  Linux*:x86_64) ASSET_NAME="askman-linux-x86_64.tar.gz" ;;
  Darwin*:x86_64) ASSET_NAME="askman-macos-x86_64.tar.gz" ;;
  Darwin*:arm64|Darwin*:aarch64) ASSET_NAME="askman-macos-aarch64.tar.gz" ;;
  *) echo "Unsupported platform: $(uname -s) $(uname -m)"; exit 1 ;;
esac

TAG="${VERSION:-$(
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | sed -nE 's/^[[:space:]]*"tag_name":[[:space:]]*"([^"]+)".*/\1/p' \
    | head -n1
)}"

if [ -z "$TAG" ] || [ "$TAG" = "null" ]; then
  echo "Error: Could not fetch release tag."
  exit 1
fi

echo "Installing askman ${TAG}..."
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/askman-installer.XXXXXX") || { echo "Error: Failed to create temporary directory."; exit 1; }
trap 'if [ -n "${TEMP_DIR:-}" ] && [ -d "$TEMP_DIR" ]; then rm -rf "$TEMP_DIR"; fi' EXIT INT TERM

BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
curl -fsSL "${BASE_URL}/${ASSET_NAME}" -o "${TEMP_DIR}/${ASSET_NAME}"
curl -fsSL "${BASE_URL}/${ASSET_NAME}.sha256" -o "${TEMP_DIR}/${ASSET_NAME}.sha256"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$TEMP_DIR" && sha256sum -c "${ASSET_NAME}.sha256")
elif command -v shasum >/dev/null 2>&1; then
  (cd "$TEMP_DIR" && shasum -a 256 -c "${ASSET_NAME}.sha256")
else
  echo "Error: checksum verification requires sha256sum or shasum in PATH."
  exit 1
fi

tar -xzf "${TEMP_DIR}/${ASSET_NAME}" -C "$TEMP_DIR"

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "$INSTALL_DIR"
mv "${TEMP_DIR}/askman" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/askman"

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
echo "Installed askman ${TAG} to $INSTALL_DIR/askman"
echo "Run 'askman <query>' to get started."
