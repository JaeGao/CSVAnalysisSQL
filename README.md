# SQL Editor Studio - CSV Analyzer

A desktop application for analyzing CSV datasets of any size using SQL. Built with PyQt6 and powered by DuckDB's columnar OLAP engine.

Load multi-gigabyte CSV files, write SQL queries with autocomplete, and export results -- all without ever running out of memory.

---

## Features

- **Unlimited file size** -- DuckDB processes data on disk, so CSV files of any size can be loaded without exhausting RAM.
- **Full SQL support** -- Write analytical queries with `GROUP BY`, `ROLLUP`, `CASE WHEN`, window functions, and more.
- **Instant scrolling** -- A virtualized table model lazily fetches only the rows visible on screen. Scrolling through 50 million rows is instantaneous.
- **Multi-dataset workspace** -- Load multiple CSV files simultaneously and `JOIN` across them.
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

1. **Load a dataset** -- Click **Browse** to select a CSV file, then click **Load**. The file is imported into DuckDB and appears in the schema tree.
2. **Write a query** -- Type SQL in the editor. Use `Ctrl+Space` for autocomplete. Table names are derived from the CSV filename (e.g., `sales_data.csv` becomes the table `sales_data`).
3. **Execute** -- Press **F5** or click **Execute**. Results appear in the table below.
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
main.py        -- Application entry point and MainWindow UI composition
database.py    -- DuckDB wrapper: load, query, schema, export
models.py      -- Virtualized QAbstractTableModel with lazy chunk loading
workers.py     -- Background QRunnable workers for file loading and data fetching
editor.py      -- Custom SQL editor widget with Ctrl+Space autocomplete
utils.py       -- Resource path resolution (supports PyInstaller bundling)
style.qss      -- Qt stylesheet (light theme)
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

The output executable is placed in the `dist/` directory.

### Build via GitHub Actions

The repository includes a CI workflow that builds executables for all three platforms automatically.

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

---

## License

This project is provided as-is for personal and educational use.
