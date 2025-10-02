#!/bin/bash
set -e

echo "🔧 Building pandas layer for Python 3.12..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build/layer"

# Clean any existing build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/python"

# Install pandas for Python 3.12 with clean dependencies
echo "📦 Installing pandas for Python 3.12..."
pip3 install pandas -t "$BUILD_DIR/python" --quiet --no-warn-script-location --break-system-packages

# Create layer zip
echo "📦 Creating layer package..."
cd "$BUILD_DIR"
mkdir -p "$PROJECT_ROOT/dist"
zip -r "$PROJECT_ROOT/dist/shared-dependencies-layer.zip" python/ > /dev/null 2>&1

# Clean up build directory immediately to avoid local clutter
echo "🧹 Cleaning up build directory..."
cd "$PROJECT_ROOT"
rm -rf "$BUILD_DIR"
rm -rf "$PROJECT_ROOT/build"

echo "✅ Pandas layer built and cleaned up"
echo "💡 Layer size: $(du -h dist/shared-dependencies-layer.zip | cut -f1)"
