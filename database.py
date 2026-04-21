import duckdb
import os
import tempfile
import re

class CSVDatabase:
    def __init__(self):
        # Create a persistent temporary database file to avoid RAM exhaustion
        self.db_path = tempfile.mktemp(prefix="csv_analyzer_", suffix=".duckdb")
        self.con = duckdb.connect(database=self.db_path, read_only=False)

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

    def load_csv(self, file_path):
        """
        Creates a table from the CSV into memory.
        This allows the user to simply query: SELECT * FROM table_name
        """
        try:
            table_name = self.sanitize_table_name(file_path)
            self.con.execute(f"DROP TABLE IF EXISTS {table_name}")
            self.con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{file_path}')")
            return True, table_name
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
            result = self.con.execute(f"DESCRIBE {table_name}").fetchall()
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
                
            copy_query = f"COPY ({query}) TO '{out_file}' (HEADER, DELIMITER '|')"
            self.con.execute(copy_query)
            return True, None
        except Exception as e:
            return False, str(e)
