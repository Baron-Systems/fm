#!/bin/bash
# Post-build script to copy assets to correct locations for nginx

SITE_NAME="$1"
BENCH_PATH="/home/frappe/frappe-bench"
PUBLIC_BUILD_PATH="$BENCH_PATH/sites/$SITE_NAME/public/build"

echo "=== Copying assets for site: $SITE_NAME ==="

# Create build directories
mkdir -p "$PUBLIC_BUILD_PATH/css"
mkdir -p "$PUBLIC_BUILD_PATH/js"

# Copy CSS files from all possible locations
echo "🔍 Searching for CSS files..."
find "$BENCH_PATH/apps" -name "*.css" -path "*/dist/css/*" -exec cp {} "$PUBLIC_BUILD_PATH/css/" \; 2>/dev/null
find "$BENCH_PATH" -maxdepth 2 -name "*.css" -path "*/dist/css/*" -exec cp {} "$PUBLIC_BUILD_PATH/css/" \; 2>/dev/null

# Copy JS files from all possible locations  
echo "🔍 Searching for JS files..."
find "$BENCH_PATH/apps" -name "*.js" -path "*/dist/js/*" -exec cp {} "$PUBLIC_BUILD_PATH/js/" \; 2>/dev/null
find "$BENCH_PATH" -maxdepth 2 -name "*.js" -path "*/dist/js/*" -exec cp {} "$PUBLIC_BUILD_PATH/js/" \; 2>/dev/null

# Also check for erpnext and frappe directories specifically
if [ -d "$BENCH_PATH/erpnext/dist/css" ]; then
    echo "📁 Found erpnext/dist/css"
    cp "$BENCH_PATH/erpnext/dist/css"/*.css "$PUBLIC_BUILD_PATH/css/" 2>/dev/null
fi

if [ -d "$BENCH_PATH/erpnext/dist/js" ]; then
    echo "📁 Found erpnext/dist/js"
    cp "$BENCH_PATH/erpnext/dist/js"/*.js "$PUBLIC_BUILD_PATH/js/" 2>/dev/null
fi

if [ -d "$BENCH_PATH/frappe/dist/css" ]; then
    echo "📁 Found frappe/dist/css"
    cp "$BENCH_PATH/frappe/dist/css"/*.css "$PUBLIC_BUILD_PATH/css/" 2>/dev/null
fi

if [ -d "$BENCH_PATH/frappe/dist/js" ]; then
    echo "📁 Found frappe/dist/js"
    cp "$BENCH_PATH/frappe/dist/js"/*.js "$PUBLIC_BUILD_PATH/js/" 2>/dev/null
fi

echo "✅ Assets copied to $PUBLIC_BUILD_PATH"
echo "CSS files: $(ls -la "$PUBLIC_BUILD_PATH/css/" | wc -l)"
echo "JS files: $(ls -la "$PUBLIC_BUILD_PATH/js/" | wc -l)"
