#!/bin/bash
set -euo pipefail

# Askman installer script
# Use: curl -fsSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash

REPO="0bmario/askman"

# Determine OS
OS="$(uname -s)"
case "$OS" in
    Linux*)     PLATFORM="linux" ;;
    Darwin*)    PLATFORM="macos" ;;
    *)          echo "Unsupported OS: $OS"; exit 1 ;;
esac

# Determine Architecture
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ARCH_SUFFIX="x86_64" ;;
    arm64)   ARCH_SUFFIX="aarch64" ;;
    aarch64) ARCH_SUFFIX="aarch64" ;;
    *)       echo "Unsupported Architecture: $ARCH"; exit 1 ;;
esac

ASSET_NAME="askman-${PLATFORM}-${ARCH_SUFFIX}.tar.gz"

echo "Detecting latest release for askman..."
if command -v jq >/dev/null 2>&1; then
    LATEST_TAG=$(curl -fs "https://api.github.com/repos/${REPO}/releases/latest" | jq -r '.tag_name')
else
    echo "Warning: jq not found. Falling back to grep/sed parsing which is brittle."
    LATEST_TAG=$(curl -fs "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
fi

if [ -z "$LATEST_TAG" ] || [ "$LATEST_TAG" = "null" ]; then
    echo "Error: Could not fetch latest release. Check your internet connection or GitHub API limits."
    exit 1
fi

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/${ASSET_NAME}"

echo "Downloading askman $LATEST_TAG for $PLATFORM ($ARCH_SUFFIX)..."
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/askman-installer.XXXXXX") || { echo "Error: Failed to create temporary directory."; exit 1; }
trap 'if [ -n "${TEMP_DIR:-}" ] && [ -d "$TEMP_DIR" ]; then rm -rf "$TEMP_DIR"; fi' EXIT INT TERM

if curl -sSfL "$DOWNLOAD_URL" -o "${TEMP_DIR}/${ASSET_NAME}"; then
  echo "Download complete."
else
  echo "Failed to download from $DOWNLOAD_URL"
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
    echo ""
    echo "WARNING: $INSTALL_DIR is not in your PATH."
    echo "Add it by running:"
    echo ""
    if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
        echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    else
        echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
    fi
    echo ""
fi

echo ""
echo "Askman $LATEST_TAG installed successfully to $INSTALL_DIR/askman"
echo "Run 'askman <query>' to get started."
