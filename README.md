# SQL Editor Studio - CSV Analyzer

A desktop application for analyzing CSV and Excel datasets of any size using SQL. Built with PyQt6 and powered by DuckDB's columnar OLAP engine.

Load multi-gigabyte CSV or XLSX files, write SQL queries with autocomplete, and export results -- all without ever running out of memory.

---

## Features

- **CSV and XLSX support** -- Load `.csv` and `.xlsx` files. XLSX workbooks with multiple sheets show a sheet selection dialog; each sheet is registered as its own queryable table.
- **Unlimited file size** -- DuckDB processes data on disk, so files of any size can be loaded without exhausting RAM.
- **Full SQL support** -- Write analytical queries with `GROUP BY`, `ROLLUP`, `CASE WHEN`, window functions, and more.
- **Instant scrolling** -- A virtualized table model lazily fetches only the rows visible on screen. Scrolling through 50 million rows is instantaneous.
- **Multi-dataset workspace** -- Load multiple files simultaneously and `JOIN` across them, including across sheets from the same workbook.
- **SQL autocomplete** -- Press `Ctrl+Space` for context-aware completions of SQL keywords, table names, and column names. Column names with special characters are automatically quoted.
- **Schema browser** -- Inspect loaded tables and their column types in a collapsible tree view. Right-click to copy a table's `CREATE TABLE` statement.
- **Saved scripts** -- Save frequently used queries and load them with a double-click.
- **CSV export** -- Export query results directly to disk at native speed using DuckDB's `COPY` command.
- **Non-blocking UI** -- File loading and data fetching run on background threads. The interface never freezes.
- **Clean light theme** -- A polished Qt stylesheet with clear typography and subtle hover states.

---

## Quick Start

### Option A: Run from source

**Prerequisites:** Python 3.10+

```bash
# Clone the repository
git clone https://github.com/JaeGao/CSVAnalysisSQL.git
cd CSVAnalysisSQL

# Linux / macOS
./start.sh

# Windows
start.bat
```

The start script creates a virtual environment, installs dependencies, and launches the application.

### Option B: Download a pre-built executable

Go to [Releases](https://github.com/JaeGao/CSVAnalysisSQL/releases) and download the executable for your platform:

| Platform | File |
|---|---|
| Windows | `CSV_Analyzer.exe` |
| macOS | `CSV_Analyzer` (macOS) |
| Linux | `CSV_Analyzer` (Linux) |

No Python installation required. Just download and run.

---

## Usage

1. **Load a file** -- Click **Load File** to select a `.csv` or `.xlsx` file.
   - CSV files are imported immediately.
   - XLSX files with a single sheet are imported immediately.
   - XLSX files with multiple sheets show a dialog -- select one or more sheets to load. Each sheet becomes its own table.
2. **Write a query** -- Type SQL in the editor. Use `Ctrl+Space` for autocomplete. Table names are derived from the filename (e.g., `sales_data.csv` → `sales_data`, `report.xlsx` sheet `Q1` → `report_Q1`).
3. **Execute** -- Press **F5** or `Ctrl+Enter`. Results appear in the table below.
4. **Sort** -- Click any column header to sort results. Sorting is handled server-side by DuckDB for maximum speed.
5. **Export** -- Click **Export Results** to save the current query output as a CSV file.

### Example Query

```sql
SELECT
  Store,
  COUNT(*) as Rows,
  SUM(CAST("Qty Sold" AS DOUBLE)) as Qty,
  SUM(CAST("Qty Sold" AS DOUBLE) * CAST(Price AS DOUBLE)) as "Total Price"
FROM sales_data
GROUP BY ROLLUP(Store)
ORDER BY Store
```

---

## Architecture

```
main.py          -- Application entry point, MainWindow, SheetSelectorDialog
database.py      -- DuckDB wrapper: load CSV/XLSX, query, schema, export
models.py        -- Virtualized QAbstractTableModel with lazy chunk loading
workers.py       -- Background QRunnable workers: CSV load, XLSX scan, XLSX load
editor.py        -- Custom SQL editor widget with Ctrl+Space autocomplete
utils.py         -- Resource path resolution (supports PyInstaller bundling)
bundle_ext.py    -- Pre-downloads the DuckDB Excel extension for bundling
style.qss        -- Qt stylesheet (light theme)
```

---

## Building from Source

### Build locally

```bash
# Linux / macOS
./build.sh

# Windows
build.bat
```

The build script installs dependencies, pre-downloads the DuckDB Excel extension (`src/bundle_ext.py`), and runs PyInstaller. The output executable is placed in the `dist/` directory.

### Build via GitHub Actions

The repository includes a CI workflow that builds executables for all three platforms automatically. Each platform runner downloads and bundles its own correct DuckDB Excel extension binary.

- **Manual trigger:** Go to Actions > Build Executables > Run workflow
- **Release trigger:** Push a version tag to build and attach binaries to a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

## Dependencies

| Package | Purpose |
|---|---|
| [PyQt6](https://pypi.org/project/PyQt6/) | Desktop GUI framework |
| [DuckDB](https://duckdb.org/) | In-process OLAP SQL engine |
| [sqlparse](https://pypi.org/project/sqlparse/) | SQL formatting |
| [openpyxl](https://pypi.org/project/openpyxl/) | XLSX sheet name enumeration (metadata only) |

---

## License

This project is provided as-is for personal and educational use.
