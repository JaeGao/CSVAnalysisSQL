import duckdb
import os
import shutil
import tempfile
import zipfile
import re

from utils import resource_path


class CSVDatabase:
    def __init__(self):
        # Create a persistent temporary database file to avoid RAM exhaustion
        self.db_path = tempfile.mktemp(prefix="csv_analyzer_", suffix=".duckdb")
        self._ext_temp_dir = None
        self.con = duckdb.connect(database=self.db_path, read_only=False)
        self._load_excel_extension()

    def _load_excel_extension(self):
        """
        Load the DuckDB Excel extension so that read_xlsx is available.

        The extension is bundled as excel_ext.zip by src/bundle_ext.py to
        prevent PyInstaller's macOS codesign pipeline from attempting to
        re-sign the Mach-O plugin file (which it cannot do successfully).

        At runtime the zip is extracted to a session-scoped temp directory
        that preserves the version/platform subdirectory structure DuckDB
        expects. extension_directory is then pointed at that base directory.

        Falls back to INSTALL excel for development environments where
        bundle_ext.py has not been run.
        """
        zip_path = os.path.join(resource_path("extensions"), "excel_ext.zip")

        if os.path.isfile(zip_path):
            try:
                self._ext_temp_dir = tempfile.mkdtemp(prefix="csv_analyzer_ext_")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(self._ext_temp_dir)
                safe_dir = self._ext_temp_dir.replace("\\", "/")
                self.con.execute(f"SET extension_directory = '{safe_dir}'")
                self.con.execute("LOAD excel")
                return
            except Exception as e:
                print(f"Warning: Could not load bundled Excel extension: {e}")

        # Fallback: online install for development or if zip extraction fails.
        try:
            self.con.execute("INSTALL excel")
            self.con.execute("LOAD excel")
        except Exception as e:
            print(f"Warning: Could not load DuckDB Excel extension: {e}")

    def close(self):
        """Clean up the DuckDB connection, temp database file, and extension temp dir."""
        try:
            self.con.close()
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception as e:
            print(f"Error cleaning up database: {e}")

        if self._ext_temp_dir and os.path.exists(self._ext_temp_dir):
            try:
                shutil.rmtree(self._ext_temp_dir)
            except Exception as e:
                print(f"Error cleaning up extension temp directory: {e}")

    def interrupt(self):
        """Interrupts the currently running query on the connection."""
        try:
            self.con.interrupt()
        except Exception as e:
            print(f"Error interrupting query: {e}")

    @staticmethod
    def sanitize_table_name(filename):
        """
        Converts a filename into a valid SQL identifier.
        """
        basename = os.path.splitext(os.path.basename(filename))[0]
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', basename)
        if not sanitized or not sanitized[0].isalpha():
            sanitized = 't_' + sanitized
        return sanitized

    def _drop_object(self, name):
        """Safely drop a table or view by trying both."""
        try:
            self.con.execute(f"DROP VIEW IF EXISTS \"{name}\"")
        except Exception:
            pass
        try:
            self.con.execute(f"DROP TABLE IF EXISTS \"{name}\"")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CSV Loading
    # ------------------------------------------------------------------

    def load_csv(self, file_path):
        """
        Creates a table from the CSV file.
        Attempts a fast-path load using default type inference (samples 20k rows).
        For extremely large, well-formed CSVs, this is incredibly fast.
        If a type anomaly exists further down the file (e.g., UUIDs in a numeric column),
        DuckDB will throw a Conversion Error.
        If a structurally malformed row exists (e.g., 9 columns instead of 8), the strict
        sniffer gives up and parses the file as a single column. We detect this by checking
        if the resulting single column name contains common delimiters.
        In either failure case, we catch the error and fall back to the safe type-recovery pass.
        """
        table_name = self.sanitize_table_name(file_path)
        escaped_path = file_path.replace("'", "''")

        # Pass 1: Maximum speed native type inference
        try:
            self._drop_object(table_name)
            self.con.execute(
                f"CREATE TABLE \"{table_name}\" AS SELECT * FROM "
                f"read_csv_auto('{escaped_path}')"
            )
            
            # Check if sniffer failed and fell back to 1 column
            schema = self.get_schema(table_name)
            if len(schema) == 1:
                col_name = schema[0]['name']
                if any(char in col_name for char in [',', '|', '\t', ';']):
                    raise Exception("Sniffer failed to detect delimiter (likely malformed rows).")
                    
            return True, table_name
        except Exception as e:
            if "Interrupt" in str(e) or "interrupted" in str(e).lower():
                return False, str(e)
            print(f"Notice: CSV fast path load aborted, falling back to safe type recovery. Reason: {e}")

        # Pass 2: Safe type recovery for messy CSVs (no data loss for type anomalies)
        staging = f"__csv_stage_{table_name}"
        try:
            self._drop_object(staging)
            # ignore_errors=true allows the sniffer to ignore malformed rows to find the delimiter.
            # all_varchar=true prevents any data loss from type inference mismatches.
            self.con.execute(
                f"CREATE TABLE \"{staging}\" AS SELECT * FROM "
                f"read_csv_auto('{escaped_path}', all_varchar=true, ignore_errors=true)"
            )
            col_exprs = self._infer_column_casts(staging)
            self._drop_object(table_name)
            self.con.execute(
                f'CREATE TABLE "{table_name}" AS SELECT {col_exprs} FROM "{staging}"'
            )
            return True, table_name
        except Exception as e:
            return False, str(e)
        finally:
            self._drop_object(staging)

    # ------------------------------------------------------------------
    # XLSX Loading
    # ------------------------------------------------------------------

    @staticmethod
    def get_xlsx_sheets(file_path):
        """
        Returns the list of sheet names in an XLSX workbook.
        Uses openpyxl in read_only mode so that only the ZIP manifest is
        parsed — no row data is read, making this instantaneous regardless
        of file size.
        """
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheets = wb.sheetnames
            wb.close()
            return sheets
        except Exception as e:
            print(f"Error reading XLSX sheet names: {e}")
            return []

    def load_xlsx(self, file_path, sheet_name):
        """
        Creates a DuckDB table from a single sheet of an XLSX workbook.
        Uses DuckDB's native read_xlsx (C++ reader via the Excel extension)
        for maximum performance -- no Python-level row iteration.

        Table name: {sanitized_filename}_{sanitized_sheetname}

        If native type inference fails (e.g. a column that is mostly empty
        so DuckDB infers DOUBLE but some rows contain UUID strings), falls back
        to a column-level type recovery pass: all data is loaded as VARCHAR to
        preserve every row, then each column is probed with TRY_CAST to recover
        its natural type. Columns where any non-empty value cannot be cast remain
        as VARCHAR. No rows are dropped.
        """
        file_base = self.sanitize_table_name(file_path)
        sheet_sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)
        table_name = f"{file_base}_{sheet_sanitized}"
        escaped_path = file_path.replace("'", "''")
        escaped_sheet = sheet_name.replace("'", "''")

        # Pass 1: native type inference (fast path for clean sheets)
        try:
            self._drop_object(table_name)
            self.con.execute(
                f"CREATE TABLE \"{table_name}\" AS SELECT * FROM "
                f"read_xlsx('{escaped_path}', sheet='{escaped_sheet}')"
            )
            return True, table_name
        except Exception as e:
            if "Interrupt" in str(e) or "interrupted" in str(e).lower():
                return False, str(e)
            print(f"Notice: XLSX fast path load aborted, falling back to safe type recovery. Reason: {e}")

        # Pass 2: column-level type recovery.
        # Load everything as VARCHAR into a staging table to guarantee all rows
        # are preserved, then probe each column with TRY_CAST to recover its
        # natural type. Columns where any non-empty value fails all candidates
        # remain as VARCHAR.
        staging = f"__xlsx_stage_{table_name}"
        try:
            self._drop_object(staging)
            self.con.execute(
                f"CREATE TABLE \"{staging}\" AS SELECT * FROM "
                f"read_xlsx('{escaped_path}', sheet='{escaped_sheet}', all_varchar=true)"
            )
            col_exprs = self._infer_column_casts(staging)
            self._drop_object(table_name)
            self.con.execute(
                f'CREATE TABLE "{table_name}" AS SELECT {col_exprs} FROM "{staging}"'
            )
            return True, table_name
        except Exception as e:
            return False, str(e)
        finally:
            self._drop_object(staging)

    def _infer_column_casts(self, staging_table):
        """
        For each column in the staging table (all VARCHAR), determine the most
        specific type that is safe to apply without losing any non-empty values.
        Returns a comma-separated SELECT expression string.

        Type candidates are checked in preference order:
          BIGINT -> DOUBLE -> DATE -> TIMESTAMP -> VARCHAR (default)
        """
        cols = self.get_schema(staging_table)
        type_candidates = ["BIGINT", "DOUBLE", "DATE", "TIMESTAMP"]
        exprs = []

        for col in cols:
            name = col['name']
            quoted = f'"{name}"'
            chosen_type = None

            for t in type_candidates:
                try:
                    # Count non-empty values where TRY_CAST returns NULL,
                    # meaning the value exists but cannot be converted.
                    fail_count = self.con.execute(
                        f'SELECT COUNT(*) FROM "{staging_table}" '
                        f'WHERE {quoted} IS NOT NULL '
                        f"AND TRIM({quoted}) != '' "
                        f'AND TRY_CAST({quoted} AS {t}) IS NULL'
                    ).fetchone()[0]
                    if fail_count == 0:
                        chosen_type = t
                        break
                except Exception as e:
                    if "Interrupt" in str(e) or "interrupted" in str(e).lower():
                        raise e
                    continue

            if chosen_type:
                exprs.append(f'TRY_CAST({quoted} AS {chosen_type}) AS {quoted}')
            else:
                exprs.append(quoted)

        return ", ".join(exprs)

    # ------------------------------------------------------------------
    # Table Management
    # ------------------------------------------------------------------

    def remove_table(self, table_name):
        """
        Drops the specified table from the database.
        """
        try:
            self._drop_object(table_name)
            return True, None
        except Exception as e:
            return False, str(e)

    def get_tables(self):
        """
        Returns a list of all loaded tables.
        """
        try:
            result = self.con.execute("SHOW TABLES").fetchall()
            return [row[0] for row in result]
        except Exception as e:
            print(f"Error getting tables: {e}")
            return []

    def get_schema(self, table_name):
        """
        Returns a list of dictionaries with column names and types for the given table.
        """
        try:
            result = self.con.execute(f"DESCRIBE \"{table_name}\"").fetchall()
            columns = [{"name": row[0], "type": row[1]} for row in result]
            return columns
        except Exception as e:
            print(f"Error reading schema: {e}")
            return []

    def get_custom_query_total_rows(self, query):
        """
        Wraps the user query to count total rows.
        """
        try:
            # Strip trailing semicolons
            query = query.strip()
            if query.endswith(';'):
                query = query[:-1]

            count_query = f"SELECT COUNT(*) FROM ({query}) as user_subquery"
            result = self.con.execute(count_query).fetchone()
            return result[0] if result else 0
        except Exception as e:
            print(f"Error counting rows: {e}")
            raise e

    def execute_custom_query(self, query, limit=500, offset=0, sort_col=None, sort_dir="ASC"):
        """
        Executes the user query, applying pagination and dynamic sorting.
        """
        try:
            query = query.strip()
            if query.endswith(';'):
                query = query[:-1]

            final_query = f"SELECT * FROM ({query}) as user_subquery"

            if sort_col:
                final_query += f' ORDER BY "{sort_col}" {sort_dir}'

            final_query += f" LIMIT {limit} OFFSET {offset}"
            cursor = self.con.cursor()
            result = cursor.execute(final_query)
            col_names = [desc[0] for desc in result.description]
            data = result.fetchall()
            cursor.close()

            return col_names, data
        except Exception as e:
            print(f"Query error: {e}")
            # Raise so the UI can catch and display the exact DuckDB error to the user
            raise e

    def export_custom_query(self, query, out_file):
        """
        Export the results of the custom query to a CSV.
        """
        try:
            query = query.strip()
            if query.endswith(';'):
                query = query[:-1]

            copy_query = f"COPY ({query}) TO '{out_file}' (HEADER, DELIMITER ',')"
            self.con.execute(copy_query)
            return True, None
        except Exception as e:
            return False, str(e)
