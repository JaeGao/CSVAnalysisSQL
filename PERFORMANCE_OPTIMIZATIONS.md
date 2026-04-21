# Performance Optimizations in CSV Analyzer SQL

The following performance optimizations have been implemented in the CSV Analyzer app to ensure it can handle large datasets efficiently without freezing the user interface or exhausting system resources.

## 1. DuckDB Backend
- **OLAP Engine:** The application uses DuckDB, a highly optimized, columnar SQL engine tailored for fast analytical queries on large datasets.
- **Disk-Backed Temporary Database:** Instead of loading the database entirely into memory (which could cause RAM exhaustion on large files), it connects to a temporary disk-backed file (`tempfile.mktemp(..., suffix=".duckdb")`). This allows the OS and DuckDB to page memory to disk efficiently.

## 2. Asynchronous Data Fetching
- **Background Threads:** Executing queries and fetching row data runs in a background thread using `QThreadPool` and `QRunnable` (`FetchWorker`). This ensures the main PyQt6 GUI thread remains responsive during heavy database operations.
- **Signals and Slots:** The background worker safely communicates loaded data back to the main UI thread via `pyqtSignal`.

## 3. Pagination and Lazy Loading
- **Chunked Loading:** Data is not fetched all at once. The `CSVTableModel` loads data in chunks of 500 rows based on the user's viewport.
- **LIMIT and OFFSET:** The backend modifies user queries by appending `LIMIT <chunk_size> OFFSET <calculated_offset>` so DuckDB only evaluates and returns the required subset of rows.

## 4. Caching, Throttling, and Rapid Scroll Handling
- **Chunk Caching:** Fetched data chunks are temporarily held in `self.chunk_cache` so that scrolling back up does not re-trigger database queries.
- **Scroll Throttling (Debouncing):** A `QTimer` handles a 150ms delay for fetching chunks during rapid scrolling. The fetch is only triggered when the user pauses scrolling for 150ms, preventing the thread pool from being flooded with redundant fetch requests.
- **Dropping Stale Requests:** During a rapid drag of the scrollbar from top to bottom, the app queues multiple intermediate chunks. The application maintains a maximum of 3 pending chunks (`if len(self.pending_chunks) > 3`). It actively pops the oldest requests, ensuring that the background thread only fetches the data where the scrollbar actually landed, discarding the intermediate areas the user flew past.

## 5. Fast Deep Paging (Scrolling to the Bottom)
- **O(1) Data Seeking:** When a user scrolls to the absolute bottom of a massive dataset, the backend requests something like `LIMIT 500 OFFSET 1000000`.
- **No Sequential Scanning:** DuckDB does **not** scan the CSV from the top. When the file was initially loaded, it was parsed into DuckDB's internal binary columnar format (`CREATE TABLE dataset AS...`). Because of this, DuckDB already mapped the data and can jump directly to the 1,000,000th row instantly.

## 6. Edge Cases and Index Error Protection
- **Chunk Boundary Protection:** When Qt requests data for a specific row, the model calculates its relative position within the chunk (`row_in_chunk = row % self.chunk_size`). It explicitly checks `if row_in_chunk < len(chunk_data):` to prevent `IndexError` on the very last chunk of the dataset, which is usually partially filled (less than 500 rows).
- **Accurate Row Counts:** The table explicitly knows the bounds of the data because a lightweight `SELECT COUNT(*)` is executed before rendering the table. Qt will never request a row beyond `self.total_rows`.
- **Null Handling:** If a value is `None` in the database, the code safely catches it and returns an empty string `""` to prevent UI rendering errors.

## 7. Preventing Segmentation Faults (Thread Safety)
Segmentation faults (crashing the entire Python runtime) are common in PyQt when background threads interact with the UI or C++ objects incorrectly. The app prevents this through:
- **Thread-Safe Signals:** The background `FetchWorker` never directly modifies the table or the UI. Instead, it emits a `pyqtSignal` (`chunk_loaded`). Qt automatically queues this signal and safely executes the `_on_chunk_loaded` method back on the main UI thread.
- **Orphaned Object Catching:** If the user closes a table or changes a query while a background worker is still running, the `FetchSignals` object might be destroyed before the worker finishes. The `run()` method in the worker wraps the fetch and emit in a `try...except Exception as e` block. This catches the `wrapped C/C++ object has been deleted` error gracefully instead of letting it segfault the application.
- **Stale Response Invalidation:** If a background worker returns data *after* the user has already sorted or changed the table, the `_on_chunk_loaded` method checks `if chunk_idx not in self.fetching_chunks: return`. This prevents the injection of stale data into the model, which could corrupt the C++ model state and cause a crash.

## 8. UI Optimizations
- **Disabled Automatic Column Resizing:** In `main.py`, `self.table_view.resizeColumnsToContents()` is explicitly disabled. Calculating column widths for millions of rows is a common cause of UI freezes in Qt; turning this off ensures immediate render times.
- **QAbstractTableModel:** Using a custom model rather than a standard `QTableWidget` allows the application to virtualize the table. Qt only requests data for the rows currently visible on the screen.

## 9. Native Data Export
- **DuckDB COPY Statement:** When exporting results to a CSV, the app avoids pulling data into Python memory and writing it row-by-row. Instead, it leverages DuckDB's native `COPY (...) TO '...'` command to stream the results directly to the disk at C++ speed.

## 10. Resource Management
- **Automatic Cleanup:** The `CSVDatabase.close()` method gracefully shuts down the DuckDB connection and deletes the temporary database file upon application exit, preventing orphaned large files from consuming disk space.
