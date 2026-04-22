"""
bundle_ext.py

Run this script before PyInstaller to pre-download the DuckDB Excel extension
and stage it in src/extensions/ for bundling.

Usage:
    python src/bundle_ext.py
"""

import duckdb
import shutil
import os
import pathlib
import sys


DEST_DIR = pathlib.Path(__file__).parent / "extensions"


def bundle_excel_extension():
    print("Connecting to DuckDB to install Excel extension...")
    con = duckdb.connect()

    try:
        con.execute("INSTALL excel")
        print("Excel extension installed.")
    except Exception as e:
        print(f"INSTALL excel failed (may already be installed): {e}")

    try:
        row = con.execute(
            "SELECT install_path FROM duckdb_extensions() WHERE extension_name = 'excel'"
        ).fetchone()
    except Exception as e:
        print(f"ERROR: Could not query extension install path: {e}")
        sys.exit(1)
    finally:
        con.close()

    if not row or not row[0]:
        print("ERROR: Excel extension install_path is empty. Was it installed correctly?")
        sys.exit(1)

    src_path = pathlib.Path(row[0])
    if not src_path.exists():
        print(f"ERROR: Extension file not found at: {src_path}")
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = DEST_DIR / "excel.duckdb_extension"
    shutil.copy2(src_path, dest_path)
    print(f"Bundled extension: {src_path} -> {dest_path}")


if __name__ == "__main__":
    bundle_excel_extension()
