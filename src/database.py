import duckdb
import os
import tempfile
import re

from utils import resource_path


class CSVDatabase:
    def __init__(self):
        # Create a persistent temporary database file to avoid RAM exhaustion
        self.db_path = tempfile.mktemp(prefix="csv_analyzer_", suffix=".duckdb")
        self.con = duckdb.connect(database=self.db_path, read_only=False)
        self._load_excel_extension()

    def _load_excel_extension(self):
        """
        Load the bundled DuckDB Excel extension so that read_xlsx is available.
        In development the extension is loaded from the system/user DuckDB directory.
        In a PyInstaller bundle the extension is loaded from the bundled 'extensions/'
        directory staged by src/bundle_ext.py.
        """
        try:
            ext_dir = resource_path("extensions")
            if os.path.isdir(ext_dir):
                # Bundled path — tell DuckDB exactly where to look
                safe_dir = ext_dir.replace("\\", "/")
                self.con.execute(f"SET extension_directory = '{safe_dir}'")
            self.con.execute("LOAD excel")
        except Exception as e:
            # Extension not available — xlsx loading will fail gracefully later
            print(f"Warning: Could not load DuckDB Excel extension: {e}")

    def close(self):
        """Clean up the DuckDB connection and delete the temporary file."""
        try:
            self.con.close()
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception as e:
            print(f"Error cleaning up database: {e}")

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
        Uses ignore_errors so that values which do not match the auto-detected type
        are set to NULL rather than aborting the load. Falls back to all VARCHAR
        only if the file cannot be parsed at all.
        """
        table_name = self.sanitize_table_name(file_path)
        escaped_path = file_path.replace("'", "''")

        try:
            self._drop_object(table_name)
            self.con.execute(
                f"CREATE TABLE \"{table_name}\" AS SELECT * FROM "
                f"read_csv_auto('{escaped_path}', ignore_errors=true)"
            )
            return True, table_name
        except Exception:
            pass

        try:
            self._drop_object(table_name)
            self.con.execute(
                f"CREATE TABLE \"{table_name}\" AS SELECT * FROM "
                f"read_csv_auto('{escaped_path}', all_varchar=true)"
            )
            return True, table_name
        except Exception as e:
            return False, str(e)

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
        for maximum performance — no Python-level row iteration.

        Table name: {sanitized_filename}_{sanitized_sheetname}
        """
        file_base = self.sanitize_table_name(file_path)
        sheet_sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', sheet_name)
        table_name = f"{file_base}_{sheet_sanitized}"
        escaped_path = file_path.replace("'", "''")
        escaped_sheet = sheet_name.replace("'", "''")

        try:
            self._drop_object(table_name)
            self.con.execute(
                f"CREATE TABLE \"{table_name}\" AS SELECT * FROM "
                f"read_xlsx('{escaped_path}', sheet='{escaped_sheet}')"
            )
            return True, table_name
        except Exception as e:
            return False, str(e)

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
            return 0

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
