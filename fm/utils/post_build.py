#!/usr/bin/env python3
"""
Post-build script to copy assets to correct locations for nginx
"""
import os
import shutil
from pathlib import Path

def copy_assets_to_public(bench_path: Path, site_name: str):
    """Copy built assets from apps/*/public/dist to sites/*/public/build"""
    
    bench_path = Path(bench_path)
    site_path = bench_path / "sites" / site_name
    public_build_path = site_path / "public" / "build"
    
    # Create build directories
    (public_build_path / "css").mkdir(parents=True, exist_ok=True)
    (public_build_path / "js").mkdir(parents=True, exist_ok=True)
    
    # Find and copy CSS files
    apps_path = bench_path / "apps"
    for app_dir in apps_path.iterdir():
        if not app_dir.is_dir():
            continue
            
        dist_css = app_dir / "public" / "dist" / "css"
        dist_js = app_dir / "public" / "dist" / "js"
        
        if dist_css.exists():
            for css_file in dist_css.glob("*.css"):
                shutil.copy2(css_file, public_build_path / "css")
                
        if dist_js.exists():
            for js_file in dist_js.glob("*.js"):
                shutil.copy2(js_file, public_build_path / "js")
    
    print(f"✅ Assets copied to {public_build_path}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python post_build.py <site_name>")
        sys.exit(1)
    
    site_name = sys.argv[1]
    bench_path = Path.cwd()
    
    copy_assets_to_public(bench_path, site_name)
