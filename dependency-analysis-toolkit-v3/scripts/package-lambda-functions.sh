#!/bin/bash

# Simple Lambda packaging script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_ROOT/lambda-packages"
DIST_DIR="$PROJECT_ROOT/dist"

# Clean and create dist directory (preserve layer zip if it exists)
mkdir -p "$DIST_DIR"

# Remove only Lambda function zips, not the layer zip
if [ -f "$DIST_DIR/shared-dependencies-layer.zip" ]; then
    # Preserve the layer zip
    mv "$DIST_DIR/shared-dependencies-layer.zip" "$DIST_DIR/shared-dependencies-layer.zip.backup"
fi

rm -f "$DIST_DIR"/*.zip

if [ -f "$DIST_DIR/shared-dependencies-layer.zip.backup" ]; then
    mv "$DIST_DIR/shared-dependencies-layer.zip.backup" "$DIST_DIR/shared-dependencies-layer.zip"
fi

# Package each function
for func in dependency-analysis minimal-dependency-finder missing-component-analysis bedrock-agent-custom-resource; do
    echo "Packaging $func..."
    
    if [ ! -f "$LAMBDA_DIR/$func/lambda_function.py" ]; then
        echo "Error: $LAMBDA_DIR/$func/lambda_function.py not found"
        continue
    fi
    
    cd "$LAMBDA_DIR/$func"
    zip -r "$DIST_DIR/$func.zip" . -q
    echo "Created $func.zip ($(du -h "$DIST_DIR/$func.zip" | cut -f1))"
done

echo "All packages created in $DIST_DIR"