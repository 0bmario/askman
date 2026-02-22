#!/bin/bash
set -e

# Askman installer script
# Use: curl -sSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash

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
LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_TAG" ]; then
    echo "Error: Could not fetch latest release. Check your internet connection or GitHub API limits."
    exit 1
fi

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/${ASSET_NAME}"

echo "Downloading askman $LATEST_TAG for $PLATFORM ($ARCH_SUFFIX)..."
TEMP_DIR=$(mktemp -d)

if curl -sL "$DOWNLOAD_URL" -o "${TEMP_DIR}/${ASSET_NAME}"; then
  echo "Download complete."
else
  echo "Failed to download from $DOWNLOAD_URL"
  exit 1
fi

echo "Extracting..."
tar -xzf "${TEMP_DIR}/${ASSET_NAME}" -C "$TEMP_DIR"

INSTALL_DIR="/usr/local/bin"
echo "Installing askman to $INSTALL_DIR (requires sudo)..."
sudo mv "${TEMP_DIR}/askman" "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/askman"

echo ""
echo "Askman installed successfully!"
echo "Run 'askman <query>' to get started."

rm -rf "$TEMP_DIR"
