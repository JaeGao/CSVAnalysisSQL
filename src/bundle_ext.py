"""
bundle_ext.py

Run this script before PyInstaller to pre-download the DuckDB Excel extension
and stage it in src/extensions/ as a zip archive for bundling.

Bundling as a zip rather than a raw binary prevents PyInstaller's macOS
codesign pipeline from attempting to re-sign the Mach-O extension file,
which fails because the file is a plugin format, not a standard executable.

At runtime, database.py extracts the zip to a session temp directory and
points DuckDB's extension_directory at it before loading.

Usage:
    python src/bundle_ext.py
"""

import duckdb
import zipfile
import pathlib
import sys


DEST_DIR = pathlib.Path(__file__).parent / "extensions"
DEST_ZIP = DEST_DIR / "excel_ext.zip"


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

    install_path = pathlib.Path(row[0])
    if not install_path.exists():
        print(f"ERROR: Extension file not found at: {install_path}")
        sys.exit(1)

    # The install path is: <ext_base>/<version>/<platform>/excel.duckdb_extension
    # We preserve the version/platform subdirectory inside the zip so that
    # at runtime we can set extension_directory=<extracted_base> and DuckDB
    # will find the correct path automatically.
    ext_base = install_path.parents[2]
    rel_path = install_path.relative_to(ext_base)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DEST_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(install_path, rel_path)

    print(f"Bundled extension (zip): {install_path} -> {DEST_ZIP}")
    print(f"  Internal path in zip: {rel_path}")


if __name__ == "__main__":
    bundle_excel_extension()
