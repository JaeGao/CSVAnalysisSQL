from PyQt6.QtCore import Qt, QAbstractTableModel, QVariant, QModelIndex, QThreadPool, pyqtSlot, QTimer
from workers import FetchWorker

class CSVTableModel(QAbstractTableModel):
    def __init__(self, db, query, total_rows):
        super().__init__()
        self.db = db
        self.query = query
        self.total_rows = total_rows
        
        self.chunk_size = 500
        self.sort_col = None
        self.sort_dir = "ASC"
        
        self.loaded_chunks = {}
        self.fetching_chunks = set()
        self.chunk_cache = {}
        
        self.fetch_timer = QTimer()
        self.fetch_timer.setSingleShot(True)
        self.fetch_timer.timeout.connect(self._process_pending_chunks)
        self.pending_chunks = []
        
        # Fetch columns synchronously, it's virtually instant (limit 0)
        try:
            self.col_names, _ = self.db.execute_custom_query(self.query, limit=0)
        except:
            self.col_names = []
            
        self.threadpool = QThreadPool()
        self._load_chunk_async(0)

    def rowCount(self, parent=QModelIndex()):
        return self.total_rows

    def columnCount(self, parent=QModelIndex()):
        return len(self.col_names)

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if section < len(self.col_names):
                    return self.col_names[section]
                return ""
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return QVariant()

    def data(self, index, role):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return QVariant()

        row = index.row()
        col = index.column()

        # Check if the row is loaded
        chunk_idx = row // self.chunk_size
        
        if chunk_idx not in self.loaded_chunks:
            self._schedule_chunk_fetch(chunk_idx)
            return "Loading..."

        # The internal list index
        row_in_chunk = row % self.chunk_size

        if chunk_idx in self.chunk_cache:
            chunk_data = self.chunk_cache[chunk_idx]
            if row_in_chunk < len(chunk_data):
                val = chunk_data[row_in_chunk][col]
                if val is None:
                    return ""
                return str(val)
            
        return QVariant()
        
    def _load_chunk_async(self, chunk_idx):
        if chunk_idx in self.fetching_chunks:
            return
            
        self.fetching_chunks.add(chunk_idx)
        worker = FetchWorker(self.db, self.query, self.chunk_size, chunk_idx, self.sort_col, self.sort_dir)
        worker.signals.chunk_loaded.connect(self._on_chunk_loaded)
        self.threadpool.start(worker)

    def _schedule_chunk_fetch(self, chunk_idx):
        if chunk_idx in self.fetching_chunks or chunk_idx in self.loaded_chunks:
            return
            
        if chunk_idx in self.pending_chunks:
            self.pending_chunks.remove(chunk_idx)
            
        self.pending_chunks.append(chunk_idx)
        
        # Keep only the last 3 requested chunks
        if len(self.pending_chunks) > 3:
            self.pending_chunks.pop(0)
            
        self.fetch_timer.start(150)

    def _process_pending_chunks(self):
        for chunk_idx in self.pending_chunks:
            self._load_chunk_async(chunk_idx)
        self.pending_chunks.clear()

    @pyqtSlot(int, list, list)
    def _on_chunk_loaded(self, chunk_idx, col_names, new_data):
        # Ignore stale responses (e.g. from before a sort action)
        if chunk_idx not in self.fetching_chunks:
            return 
            
        self.fetching_chunks.remove(chunk_idx)
            
        if not new_data:
            return
            
        offset = chunk_idx * self.chunk_size
        self.chunk_cache[chunk_idx] = new_data
        self.loaded_chunks[chunk_idx] = True
        
        # Emit dataChanged to force UI update
        start_idx = self.index(offset, 0)
        end_idx = self.index(offset + len(new_data) - 1, self.columnCount() - 1)
        self.dataChanged.emit(start_idx, end_idx, [Qt.ItemDataRole.DisplayRole])

    def sort(self, column, order):
        # We handle sorting dynamically by telling DuckDB to wrap our query with an ORDER BY
        self.layoutAboutToBeChanged.emit()
        self.sort_col = self.col_names[column]
        self.sort_dir = "ASC" if order == Qt.SortOrder.AscendingOrder else "DESC"
        
        # Reset cache
        self.loaded_chunks.clear()
        self.fetching_chunks.clear() # This invalidates any running background workers
        self.chunk_cache.clear()
        self.pending_chunks.clear()
        self.fetch_timer.stop()
        
        self.layoutChanged.emit()
        
        # Re-fetch initial chunk with new sort
        self._load_chunk_async(0)
