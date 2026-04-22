from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


# ---------------------------------------------------------------------------
# Chunked fetch worker (used by the table model for paginated query display)
# ---------------------------------------------------------------------------

class FetchSignals(QObject):
    chunk_loaded = pyqtSignal(int, list, list)  # chunk_idx, col_names, new_data


class FetchWorker(QRunnable):
    def __init__(self, db, query, chunk_size, chunk_idx, sort_col, sort_dir):
        super().__init__()
        self.db = db
        self.query = query
        self.chunk_size = chunk_size
        self.chunk_idx = chunk_idx
        self.sort_col = sort_col
        self.sort_dir = sort_dir
        self.signals = FetchSignals()

    @pyqtSlot()
    def run(self):
        offset = self.chunk_idx * self.chunk_size
        try:
            col_names, new_data = self.db.execute_custom_query(
                self.query, limit=self.chunk_size, offset=offset,
                sort_col=self.sort_col, sort_dir=self.sort_dir
            )
            self.signals.chunk_loaded.emit(self.chunk_idx, col_names, new_data)
        except Exception as e:
            print(f"Async fetch error: {e}")


# ---------------------------------------------------------------------------
# CSV load worker
# ---------------------------------------------------------------------------

class LoadSignals(QObject):
    # success, err_or_table_name, original_file_path
    finished = pyqtSignal(bool, str, str)


class LoadWorker(QRunnable):
    def __init__(self, db, file_path):
        super().__init__()
        self.db = db
        self.file_path = file_path
        self.signals = LoadSignals()

    @pyqtSlot()
    def run(self):
        try:
            success, err_or_table = self.db.load_csv(self.file_path)
            self.signals.finished.emit(success, err_or_table, self.file_path)
        except Exception as e:
            self.signals.finished.emit(False, str(e), self.file_path)


# ---------------------------------------------------------------------------
# XLSX sheet scan worker
# Reads only the workbook ZIP manifest (via openpyxl read_only=True) so it
# is instantaneous regardless of file size.
# ---------------------------------------------------------------------------

class XlsxSheetScanSignals(QObject):
    # file_path, list of sheet names (empty list on failure)
    finished = pyqtSignal(str, list)


class XlsxSheetScanWorker(QRunnable):
    def __init__(self, db, file_path):
        super().__init__()
        self.db = db
        self.file_path = file_path
        self.signals = XlsxSheetScanSignals()

    @pyqtSlot()
    def run(self):
        sheets = self.db.get_xlsx_sheets(self.file_path)
        self.signals.finished.emit(self.file_path, sheets)


# ---------------------------------------------------------------------------
# XLSX load worker
# Loads one or more sheets using DuckDB's native C++ read_xlsx reader.
# ---------------------------------------------------------------------------

class XlsxLoadSignals(QObject):
    # success, comma-separated table names (or error message), file_path
    finished = pyqtSignal(bool, str, str)
    # sheet_done: sheet_name, table_name (emitted after each sheet)
    sheet_done = pyqtSignal(str, str)


class XlsxLoadWorker(QRunnable):
    def __init__(self, db, file_path, sheet_names):
        super().__init__()
        self.db = db
        self.file_path = file_path
        self.sheet_names = sheet_names
        self.signals = XlsxLoadSignals()

    @pyqtSlot()
    def run(self):
        loaded_tables = []
        for sheet in self.sheet_names:
            try:
                success, result = self.db.load_xlsx(self.file_path, sheet)
                if success:
                    loaded_tables.append(result)
                    self.signals.sheet_done.emit(sheet, result)
                else:
                    self.signals.finished.emit(False, result, self.file_path)
                    return
            except Exception as e:
                self.signals.finished.emit(False, str(e), self.file_path)
                return

        self.signals.finished.emit(True, ", ".join(loaded_tables), self.file_path)
