# Master Work Log: Architecture, Optimizations, and Guidelines

This document serves as the master record for the `CSV Analyzer SQL` application. It details the core implementation, the performance optimizations made, the pitfalls encountered, and the strict guidelines required to maintain stability moving forward.

---

## 1. Implementation Summary
`CSV Analyzer SQL` is a robust PyQt6 application designed to ingest and analyze massive CSV datasets using SQL. 
To ensure maintainability and a clean project root, the application uses a modular architecture with all core code located in the `src/` directory:
- **`src/database.py`**: Handles all DuckDB interactions, schema fetching, robust CSV/XLSX ingestion, and query execution.
- **`src/workers.py`**: Contains background thread logic (`QRunnable`) to prevent UI blocking. Includes workers for CSV load, XLSX sheet scanning, and XLSX data loading.
- **`src/models.py`**: Contains the virtualized data model (`CSVTableModel`) for the Qt Table View.
- **`src/editor.py`**: Encapsulates the custom `SQLEditor` component with advanced autocomplete functionality.
- **`src/utils.py`**: Contains utility functions: `resource_path()` for cross-platform PyInstaller asset resolution, and `get_app_data_dir()` for resolving the writable session temp directory (`csv_analyzer_temp/`) next to the executable.
- **`src/main.py`**: The application entry point, `MainWindow` UI composition, and `SheetSelectorDialog`.
- **`src/bundle_ext.py`**: Standalone build utility that pre-downloads the DuckDB Excel extension binary and stages it to `src/extensions/` before PyInstaller runs.

---

## 2. Pitfalls & Solutions (The "Gotchas")

During development, several critical bottlenecks and crashes were encountered. Here is how they were solved:

### Pitfall 1: RAM Exhaustion on Massive Files
- **The Problem:** Loading gigabyte-sized CSV files into pandas or native Python memory caused the OS to kill the process.
- **The Solution:** Dropped pandas in favor of **DuckDB**. Connected to a disk-backed temporary database (`tempfile.mktemp(suffix=".duckdb")`), allowing the OS to page memory efficiently.

### Pitfall 2: UI Freezes During Long Operations
- **The Problem:** Executing complex queries or loading large CSVs synchronously blocked the main thread, causing the Qt window to show "Not Responding".
- **The Solution:** Offloaded blocking operations to a `QThreadPool` using custom `QRunnable` classes (`FetchWorker`, `LoadWorker`).

### Pitfall 3: Segmentation Faults from Threading
- **The Problem:** Python would silently crash (segfault) when background workers attempted to update the table data or UI components directly.
- **The Solution:** Enforced strict Qt threading rules. Background workers never touch the UI. Instead, they emit a thread-safe `pyqtSignal` via a dedicated `QObject` (`FetchSignals`), which Qt automatically queues and executes safely on the main thread.

### Pitfall 4: UI Freezes During Table Rendering
- **The Problem:** Loading 1,000,000 rows into a standard `QTableWidget` or calling `table.resizeColumnsToContents()` instantly froze the application.
- **The Solution:** Disabled automatic column resizing. Implemented a custom `QAbstractTableModel` that only loads the rows currently visible on screen.

### Pitfall 5: Scrolling Stutter & Thread Flooding
- **The Problem:** Rapidly dragging the scrollbar generated hundreds of sequential database queries, overloading DuckDB and causing UI stutter.
- **The Solution:** 
  1. **Debouncing:** Implemented a 150ms `QTimer` delay before fetching data.
  2. **Queue Limits:** Restricted pending chunks to a maximum of 3, popping older requests to discard intermediate scroll locations.
  3. **Stale Invalidation:** Implemented checks in the UI thread to discard late-arriving background responses if the user had already sorted or scrolled away.

### Pitfall 6: SQL Syntax Errors with Dynamic Data
- **The Problem:** Users loading files like `My Data-Set.csv` caused SQL crashes because spaces/hyphens are invalid SQL identifiers.
- **The Solution:** 
  - **Table Names:** Sanitized table names upon load (replacing non-alphanumeric characters with `_`).
  - **Column Names:** The SQL Autocomplete system now automatically detects non-alphanumeric column names and wraps them in double quotes (`"Total Price"`) to ensure syntax safety.

### Pitfall 7: Messy CSV Ingestion Failures
- **The Problem:** DuckDB's strict schema inference would fail on CSVs with inconsistent data types or malformed rows, causing load failures.
- **The Solution:** Implemented a strict two-pass fallback mechanism.
  - **Pass 1 (Fast Path):** Attempts `read_csv_auto('{file}')` using the default 20k row sample size. For 99% of massive, well-formed files, this loads instantaneously. We then explicitly check if DuckDB's strict sniffer failed (which happens when structurally malformed rows like `9` columns in an `8` column file exist, causing DuckDB to silently fall back to parsing the file as a single 1-column string). If the resulting table has 1 column and contains delimiter characters in its header, we intentionally throw an exception to trigger the recovery pass.
  - **Pass 2 (Recovery):** If Pass 1 threw a `Conversion Error` (type anomaly) or our custom sniffer-failure exception, we drop the aborted table and fall back to loading the entire file into a staging table. We use `read_csv_auto(..., all_varchar=true, ignore_errors=true)`. `ignore_errors=true` allows the sniffer to bypass the physically malformed rows and successfully detect the correct delimiter (e.g., `|`). `all_varchar=true` guarantees zero data loss from type anomalies. Physically malformed rows (e.g. 9 columns instead of 8) are dropped by DuckDB, which is correct as they cannot fit the schema. We then probe every column across the entire dataset with `TRY_CAST` to recover its natural type (`BIGINT`, `DOUBLE`, etc.), leaving mixed-type columns safely as `VARCHAR`.

### Pitfall 8: Cross-Platform Resource Pathing in PyInstaller
- **The Problem:** When packaged as a single executable, relative paths to images, icons, and QSS stylesheets break. Additionally, Windows paths with backslashes (`\`) break QSS `url()` statements.
- **The Solution:** Implemented a `resource_path()` utility that maps to `sys._MEIPASS` when frozen. Ensured paths used in QSS string replacements are explicitly converted to forward slashes (`/`), and bundled assets like `scripts.json` safely fallback/copy to the user's execution directory.

### Pitfall 9: DuckDB Catalog Errors on Overwrites
- **The Problem:** Executing `DROP TABLE IF EXISTS` throws a Catalog Error if the object is actually a View (and vice-versa). This crashed the app when saving views or reloading CSVs.
- **The Solution:** Implemented a `_drop_object` wrapper that sequentially catches exceptions for both `DROP VIEW IF EXISTS` and `DROP TABLE IF EXISTS` to safely overwrite references.

### Pitfall 10: XLSX Loading Performance and Offline Extension Bundling
- **The Problem:** Adding XLSX support required choosing a loading strategy. The obvious path (`openpyxl` or `pandas.read_excel()`) processes rows through the Python GIL, reproducing the same performance problems as the original CSV loading approach (30-60+ seconds for large files, UI appears frozen).
- **The Solution:** Used DuckDB's native `read_xlsx` C++ reader via the `excel` extension, which reads and parses XLSX files entirely in native code, bypassing Python and streaming directly into DuckDB's columnar memory format. This is the same performance tier as `read_csv_auto`.
- **The Bundling Problem:** DuckDB extensions are normally downloaded at runtime from `extensions.duckdb.org`. In a PyInstaller bundle the app must work offline, so this download cannot happen at user launch time. Additionally, simply copying the `.duckdb_extension` binary into a macOS PyInstaller build causes a fatal `codesign` error, because PyInstaller detects the Mach-O header but cannot correctly re-sign the DuckDB plugin format.
- **The Bundling Solution:** Introduced `src/bundle_ext.py`, a build-time utility script. It calls `INSTALL excel` once during the build process, locates the downloaded binary, and compresses it into `src/extensions/excel_ext.zip` (preserving its native version/platform directory structure). Because it is a zip archive, PyInstaller ignores it during the codesign phase. At runtime, `database.py` extracts this zip into a session-scoped temp directory and sets `extension_directory` to point to it before calling `LOAD excel`. Each CI runner (Windows/macOS/Linux) produces the correct platform-specific zip automatically.
- **Sheet Name Enumeration:** `openpyxl` is still used, but only to read sheet names via `load_workbook(read_only=True).sheetnames`, which parses only the ZIP manifest, not row data. This is instantaneous regardless of file size. No row-level data ever passes through openpyxl.

### Pitfall 11: Temp File Accumulation on Windows
- **The Problem:** Each session creates a disk-backed `.duckdb` database file and an extension extraction directory via `tempfile.mktemp()` / `tempfile.mkdtemp()`. On normal exit `close()` is called from `closeEvent` and both are removed. However, if the process is force-killed (Windows Task Manager, crash, SIGKILL) `closeEvent` never fires and the files are stranded in the OS temp directory indefinitely. On Windows, where users are more likely to discover the temp folder, multi-gigabyte orphaned `.duckdb` files accumulate visibly across sessions. DuckDB also writes a `.wal` (write-ahead log) side file alongside the database that was not being deleted even on clean exits.
- **The Solution:**
  - **Predictable location:** Replaced `tempfile` with a dedicated `csv_analyzer_temp/` directory placed next to the executable (frozen) or at the project root (dev), managed by `get_app_data_dir()` in `utils.py`. Files are now easy to locate and manually clean up if needed.
  - **Session-scoped naming:** The `.duckdb` file and extension dir use a short UUID prefix (`csv_analyzer_<8hex>.duckdb`) so multiple concurrent instances never collide.
  - **Startup cleanup:** `CSVDatabase.cleanup_stale_sessions()` is called once at app launch. It scans `csv_analyzer_temp/` and deletes any `csv_analyzer_*.duckdb` (and `.wal`) files not currently locked by another running instance. On Windows, a locked file raises `OSError`, which is silently skipped — so only orphaned files from dead sessions are removed.
  - **WAL cleanup:** `close()` now explicitly removes the `.wal` and `.wal.tmp` side files after closing the DuckDB connection.
  - **`atexit` safety net:** `atexit.register(db.close)` is called in `MainWindow.__init__` as a secondary guarantee. `atexit` fires on clean Python interpreter shutdown (including `Ctrl+C`) even if `closeEvent` is bypassed, providing one extra layer of defense short of a hard process kill.

---

## 3. UI/UX and Quality of Life Enhancements

The application prioritizes user experience and rapid iteration through several key features:
- **Advanced SQL Toolbar**: Removed basic SQL snippet buttons in favor of robust utilities:
  - **Format**: Leverages `sqlparse` to prettify complex, nested queries instantly.
  - **Query History**: Automatically tracks successful queries during a session in a dropdown, allowing rapid iteration without losing work.
  - **Save as View**: Immediately creates a virtual table (`CREATE OR REPLACE VIEW`) from the current query and loads it into the schema tree for downstream analysis.
  - **Execute Shortcut**: Standardized `Ctrl+Enter` and `F5` shortcuts to execute queries without UI interaction.
- **Smart Autocomplete**: The `SQLEditor` continuously provides context-aware autocomplete suggestions (columns, tables, SQL keywords) dynamically as the user types. It uses an exact-prefix replacement algorithm to maintain correct casing and preserve quoted identifiers seamlessly.
- **Dynamic Layouts**: The `Schema Tree` enforces a clean `60/40` width ratio between the "Column Name" and "Type" headers. It also supports `ExtendedSelection` allowing users to select and copy multiple columns at once.
- **Contextual Actions**: Right-clicking columns in the Schema Tree allows for one-click copying of exact column names directly to the clipboard.
- **Consistent Styling**: Customized QSS prevents default dotted-outlines on Windows tables/trees and ensures inactive selection colors remain visible and professional.

---

## 4. Performance Optimizations

Beyond crash prevention, the following systemic optimizations exist:
- **OLAP Engine:** DuckDB's columnar layout evaluates analytical queries (like `GROUP BY` and `SUM`) exponentially faster than row-based databases like SQLite.
- **Deep Paging (O(1) Seek):** Because DuckDB compiles the CSV into an internal binary format upon load, scrolling to the absolute bottom of a 50M row dataset (`OFFSET 49999500`) does **not** result in a sequential scan. It seeks instantly.
- **Native Data Export:** The `Export Results` feature leverages DuckDB's `COPY (...) TO '...'` command, streaming results directly to disk as standard comma-delimited CSVs at C++ speed without ever pulling the data into Python RAM.
- **Dynamic Header Resizing:** Standard Qt `resizeColumnsToContents()` freezes the UI by scanning every row in a table. Instead, the table evaluates the exact `QFontMetrics` width of the header text and injects padding, rendering columns instantly regardless of dataset size.

---

## 5. Distribution and CI/CD

To ensure seamless distribution across operating systems, the project utilizes:
- **PyInstaller:** Configured via `build.bat` and `build.sh` to package the application as a standalone, single-file executable `--onefile` with no console `--noconsole`.
- **Resource Bundling:** All styling assets (`style.qss`), scripts (`scripts.json`), icons (`icon.ico`, `icon.png`), UI control assets (`grip_horizontal.png`), and the DuckDB Excel extension binary (`src/extensions/`) are natively injected via `--add-data`.
- **Extension Pre-Bundling:** `src/bundle_ext.py` must be run before PyInstaller in every build environment. It downloads the platform-correct DuckDB `excel` extension binary once and stages it for bundling. This ensures XLSX loading works fully offline in the distributed executable.
- **GitHub Actions:** A fully automated `build-exe.yml` workflow triggers on tags, compiling Windows, macOS, and Linux executables concurrently and attaching them to GitHub Releases. Each runner executes `bundle_ext.py` as a dedicated step before PyInstaller.

---

## 6. Development Guidelines

To prevent regressions, adhere to the following rules when modifying this codebase:

> [!WARNING]
> **1. The Threading Safety Rule**
> If an operation takes longer than 50ms (like any database query or file IO), it **MUST** go in `workers.py` as a `QRunnable`. You must use a `pyqtSignal` to communicate the result back to the UI. Never pass UI object references to the background thread.

> [!IMPORTANT]
> **2. The Data Model Rule**
> Never load a full dataset into memory. Always route data through the `CSVTableModel` lazy-loading architecture using `LIMIT` and `OFFSET`. 

> [!CAUTION]
> **3. The File Handling Rule**
> Always assume CSV files and column headers contain malicious or invalid characters (spaces, hyphens, Unicode). Always sanitize and quote names when constructing SQL queries dynamically.

> [!NOTE]
> **4. Resource Cleanup**
> Session temp files (`.duckdb`, `.wal`, extracted extension dir) are stored in `csv_analyzer_temp/` next to the executable. `CSVDatabase.close()` removes them and is called from both `closeEvent` and an `atexit` handler. `cleanup_stale_sessions()` is called at startup to remove orphans from crashed prior sessions. If you add new temp files, delete them in `close()` and handle them in `cleanup_stale_sessions()`.

> [!WARNING]
> **5. Adding New File Format Support**
> Never use Python-level row-iteration libraries (openpyxl row reads, pandas, csv.reader) to ingest data into DuckDB. Always find a native DuckDB reader (`read_csv_auto`, `read_xlsx`, `read_parquet`, etc.) or a DuckDB extension that provides one. Python-level row iteration blocks the GIL, produces the same UI freeze and memory problems as the original CSV approach, and is orders of magnitude slower than the native C++ readers. If a DuckDB extension is required, add it to `bundle_ext.py` and `--add-data` in all build scripts.
