"""
bundle_ext.py

Run this script before PyInstaller to pre-download the DuckDB Excel extension
for all supported platforms and stage them in src/extensions/ as a zip archive.

Bundling for multiple platforms (Windows, Linux, macOS) ensures that the
resulting binary is cross-platform compatible even when built on a single OS.
"""

import duckdb
import zipfile
import pathlib
import sys
import urllib.request
import gzip
import io

DEST_DIR = pathlib.Path(__file__).parent / "extensions"
DEST_ZIP = DEST_DIR / "excel_ext.zip"

# Platforms to bundle
PLATFORMS = ["linux_amd64", "windows_amd64", "osx_amd64", "osx_arm64"]
EXTENSION_NAME = "excel"

def bundle_extensions():
    print("Detecting DuckDB version...")
    con = duckdb.connect()
    try:
        # Get the internal version string (e.g., "v1.1.0")
        v_str = con.execute("SELECT library_version FROM duckdb_extensions() LIMIT 1").fetchone()[0]
        if not v_str.startswith('v'):
            v_str = 'v' + v_str
    except Exception as e:
        print(f"Error detecting version: {e}")
        # Fallback to duckdb.__version__ with 'v' prefix
        v_str = 'v' + duckdb.__version__
    finally:
        con.close()

    print(f"Bundling extensions for version: {v_str}")
    
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    with zipfile.ZipFile(DEST_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for platform in PLATFORMS:
            url = f"https://extensions.duckdb.org/{v_str}/{platform}/{EXTENSION_NAME}.duckdb_extension.gz"
            print(f"  Downloading {platform}...")
            
            try:
                # Use a proper User-Agent to avoid being blocked by some CDNs
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    compressed_data = response.read()
                    
                with gzip.GzipFile(fileobj=io.BytesIO(compressed_data)) as gz:
                    extension_data = gz.read()
                
                # Internal zip path: <version>/<platform>/excel.duckdb_extension
                zip_path = f"{v_str}/{platform}/{EXTENSION_NAME}.duckdb_extension"
                zf.writestr(zip_path, extension_data)
                print(f"    Added to bundle.")
                success_count += 1
            except Exception as e:
                print(f"    FAILED: {e}")

    if success_count == 0:
        print("\nERROR: No extensions were bundled. Check your internet connection.")
        sys.exit(1)
    
    print(f"\nDone! Bundled {success_count} platforms into {DEST_ZIP}")

if __name__ == "__main__":
    bundle_extensions()
