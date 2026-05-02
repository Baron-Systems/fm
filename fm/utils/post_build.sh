#!/bin/bash
# Post-build script to copy assets to correct locations for nginx

SITE_NAME="$1"
BENCH_PATH="/home/frappe/frappe-bench"
PUBLIC_BUILD_PATH="$BENCH_PATH/sites/$SITE_NAME/public/build"

echo "=== Copying assets for site: $SITE_NAME ==="

# Create build directories
mkdir -p "$PUBLIC_BUILD_PATH/css"
mkdir -p "$PUBLIC_BUILD_PATH/js"

# Copy CSS files
find "$BENCH_PATH/apps" -name "*.css" -path "*/public/dist/css/*" -exec cp {} "$PUBLIC_BUILD_PATH/css/" \;

# Copy JS files
find "$BENCH_PATH/apps" -name "*.js" -path "*/public/dist/js/*" -exec cp {} "$PUBLIC_BUILD_PATH/js/" \;

echo "✅ Assets copied to $PUBLIC_BUILD_PATH"
echo "CSS files: $(ls -la "$PUBLIC_BUILD_PATH/css/" | wc -l)"
echo "JS files: $(ls -la "$PUBLIC_BUILD_PATH/js/" | wc -l)"
