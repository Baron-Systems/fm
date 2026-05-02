#!/usr/bin/env python3
"""
Hook to automatically copy assets after bench build
"""
import os
import subprocess
import sys
from pathlib import Path

def main():
    """Run post-build script automatically"""
    bench_path = Path.cwd()
    
    # Get all sites
    sites_dir = bench_path / "sites"
    if not sites_dir.exists():
        return
    
    for site_dir in sites_dir.iterdir():
        if not site_dir.is_dir() or site_dir.name.startswith('.'):
            continue
            
        site_name = site_dir.name
        post_build_script = bench_path / "utils" / "post_build.sh"
        
        if post_build_script.exists():
            print(f"🔄 Running post-build for site: {site_name}")
            try:
                subprocess.run(["bash", str(post_build_script), site_name], 
                             check=True, capture_output=True)
                print(f"✅ Post-build completed for {site_name}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Post-build failed for {site_name}: {e}")

if __name__ == "__main__":
    main()
