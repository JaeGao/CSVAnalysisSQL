# Master Work Log: Architecture, Optimizations, and Guidelines

This document serves as the master record for the `CSV Analyzer SQL` application. It details the core implementation, the performance optimizations made, the pitfalls encountered, and the strict guidelines required to maintain stability moving forward.

---

## 1. Implementation Summary
`CSV Analyzer SQL` is a robust PyQt6 application designed to ingest and analyze massive CSV datasets using SQL. 
To ensure maintainability, the application was recently refactored from a monolithic script into a clean, modular architecture:
- **`database.py`**: Handles all DuckDB interactions, schema fetching, and query execution.
- **`workers.py`**: Contains background thread logic (`QRunnable`) to prevent UI blocking.
- **`models.py`**: Contains the virtualized data model (`CSVTableModel`) for the Qt Table View.
- **`editor.py`**: Encapsulates the custom `SQLEditor` component with advanced autocomplete functionality.
- **`main.py`**: The application entry point and `MainWindow` UI composition layer.

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

---

## 3. Performance Optimizations

Beyond crash prevention, the following systemic optimizations exist:
- **OLAP Engine:** DuckDB's columnar layout evaluates analytical queries (like `GROUP BY` and `SUM`) exponentially faster than row-based databases like SQLite.
- **Deep Paging (O(1) Seek):** Because DuckDB compiles the CSV into an internal binary format upon load, scrolling to the absolute bottom of a 50M row dataset (`OFFSET 49999500`) does **not** result in a sequential scan. It seeks instantly.
- **Native Data Export:** The `Export Results` feature leverages DuckDB's `COPY (...) TO '...'` command, streaming results directly to disk at C++ speed without ever pulling the data into Python RAM.

---

## 4. Development Guidelines

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
