# Master Work Log: Architecture, Optimizations, and Guidelines

This document serves as the master record for the `CSV Analyzer SQL` application. It details the core implementation, the performance optimizations made, the pitfalls encountered, and the strict guidelines required to maintain stability moving forward.

---

## 1. Implementation Summary
`CSV Analyzer SQL` is a robust PyQt6 application designed to ingest and analyze massive CSV datasets using SQL. 
To ensure maintainability and a clean project root, the application uses a modular architecture with all core code located in the `src/` directory:
- **`src/database.py`**: Handles all DuckDB interactions, schema fetching, robust CSV ingestion, and query execution.
- **`src/workers.py`**: Contains background thread logic (`QRunnable`) to prevent UI blocking.
- **`src/models.py`**: Contains the virtualized data model (`CSVTableModel`) for the Qt Table View.
- **`src/editor.py`**: Encapsulates the custom `SQLEditor` component with advanced autocomplete functionality.
- **`src/utils.py`**: Contains utility functions like `resource_path()` for cross-platform PyInstaller asset resolution.
- **`src/main.py`**: The application entry point and `MainWindow` UI composition layer.

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
- **The Solution:** Implemented robust fallback logic. First, attempt to load with `ignore_errors=true`. If strict inference fails, fallback to loading all columns as `VARCHAR` (`all_varchar=true`) to guarantee ingestion regardless of cleanliness.

### Pitfall 8: Cross-Platform Resource Pathing in PyInstaller
- **The Problem:** When packaged as a single executable, relative paths to images, icons, and QSS stylesheets break. Additionally, Windows paths with backslashes (`\`) break QSS `url()` statements.
- **The Solution:** Implemented a `resource_path()` utility that maps to `sys._MEIPASS` when frozen. Ensured paths used in QSS string replacements are explicitly converted to forward slashes (`/`), and bundled assets like `scripts.json` safely fallback/copy to the user's execution directory.

### Pitfall 9: DuckDB Catalog Errors on Overwrites
- **The Problem:** Executing `DROP TABLE IF EXISTS` throws a Catalog Error if the object is actually a View (and vice-versa). This crashed the app when saving views or reloading CSVs.
- **The Solution:** Implemented a `_drop_object` wrapper that sequentially catches exceptions for both `DROP VIEW IF EXISTS` and `DROP TABLE IF EXISTS` to safely overwrite references.

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
- **Resource Bundling:** All styling assets (`style.qss`), scripts (`scripts.json`), icons (`icon.ico`, `icon.png`), and UI control assets (`grip_horizontal.png`) are natively injected via `--add-data`.
- **GitHub Actions:** A fully automated `build-exe.yml` workflow triggers on tags, compiling Windows, macOS, and Linux executables concurrently and attaching them to GitHub Releases.

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
> Ensure `CSVDatabase.close()` is always called on exit. Failure to do so will leave multi-gigabyte `.duckdb` temp files stranded in the user's `/tmp` directory.
