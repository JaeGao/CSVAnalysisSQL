from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

class FetchSignals(QObject):
    chunk_loaded = pyqtSignal(int, list, list) # chunk_idx, col_names, new_data

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
                self.query, limit=self.chunk_size, offset=offset, sort_col=self.sort_col, sort_dir=self.sort_dir
            )
            self.signals.chunk_loaded.emit(self.chunk_idx, col_names, new_data)
        except Exception as e:
            print(f"Async fetch error: {e}")

class LoadSignals(QObject):
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
