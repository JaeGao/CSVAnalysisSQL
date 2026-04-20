import sys
import os
import glob
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QLabel, QTableView, QHeaderView,
    QMessageBox, QSplitter, QListWidget, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog, QInputDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QVariant, QModelIndex, QRunnable, QThreadPool, pyqtSignal, pyqtSlot, QObject, QTimer
from PyQt6.QtGui import QFont, QIcon

from database import CSVDatabase

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))

    return os.path.join(base_path, relative_path)

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SQL Editor Studio - CSV Analyzer")
        self.resize(1200, 800)
        
        self.db = CSVDatabase()
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.scripts_file = os.path.join(app_dir, "scripts.json")
        self.saved_scripts = {}
        self.load_scripts()
        
        # Load Stylesheet
        try:
            with open(resource_path("style.qss"), "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Could not load stylesheet: {e}")
            
        self.setup_ui()

    def load_scripts(self):
        if os.path.exists(self.scripts_file):
            try:
                with open(self.scripts_file, 'r') as f:
                    self.saved_scripts = json.load(f)
            except:
                self.saved_scripts = {}
        else:
            self.saved_scripts = {
                "Example: Grand Total Store Sales": "SELECT \n  Store,\n  COUNT(*) as Rows,\n  SUM(CAST(\"Qty Sold\" AS DOUBLE)) as Qty,\n  SUM(CAST(\"Qty Sold\" AS DOUBLE) * CAST(Price AS DOUBLE)) as \"Total Price\",\n  SUM(CASE WHEN CAST(\"Qty Sold\" AS DOUBLE) * CAST(Price AS DOUBLE) < 0 THEN CAST(\"Qty Sold\" AS DOUBLE) * CAST(Price AS DOUBLE) ELSE 0 END) as \"Neg Total\"\nFROM dataset\nGROUP BY ROLLUP(Store)\nORDER BY Store"
            }
            self.save_scripts()

    def save_scripts(self):
        with open(self.scripts_file, 'w') as f:
            json.dump(self.saved_scripts, f, indent=4)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main Layout: 3 panes using QSplitter
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # --- LEFT PANE (Schema & Files) ---
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # File selector
        left_layout.addWidget(QLabel("1. Select Dataset:"))
        file_layout = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("No CSV selected...")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_dataset)
        
        file_layout.addWidget(self.file_path_edit)
        file_layout.addWidget(browse_btn)
        file_layout.addWidget(load_btn)
        left_layout.addLayout(file_layout)
        
        # Schema Viewer
        left_layout.addWidget(QLabel("Schema (Table: 'dataset'):"))
        self.schema_tree = QTreeWidget()
        self.schema_tree.setHeaderLabels(["Column Name", "Type"])
        self.schema_tree.setAlternatingRowColors(True)
        left_layout.addWidget(self.schema_tree)
        
        # Saved Scripts
        left_layout.addWidget(QLabel("Saved Scripts:"))
        self.scripts_list = QListWidget()
        self.refresh_scripts_list()
        self.scripts_list.itemDoubleClicked.connect(self.load_script_to_editor)
        left_layout.addWidget(self.scripts_list)
        
        script_btn_layout = QHBoxLayout()
        save_script_btn = QPushButton("Save")
        save_script_btn.clicked.connect(self.save_current_script)
        del_script_btn = QPushButton("Delete")
        del_script_btn.clicked.connect(self.delete_current_script)
        script_btn_layout.addWidget(save_script_btn)
        script_btn_layout.addWidget(del_script_btn)
        left_layout.addLayout(script_btn_layout)
        
        top_splitter.addWidget(left_pane)
        
        # --- RIGHT PANE (Editor & Results) ---
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Editor Toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(QLabel("SQL Editor:"))
        
        # Snippets
        snip_select = QPushButton("SELECT *")
        snip_select.clicked.connect(lambda: self.sql_editor.insertPlainText("SELECT * FROM dataset\n"))
        snip_groupby = QPushButton("GROUP BY")
        snip_groupby.clicked.connect(lambda: self.sql_editor.insertPlainText("GROUP BY "))
        snip_sum = QPushButton("SUM()")
        snip_sum.clicked.connect(lambda: self.sql_editor.insertPlainText("SUM()"))
        snip_case = QPushButton("CASE WHEN")
        snip_case.clicked.connect(lambda: self.sql_editor.insertPlainText("CASE WHEN condition THEN true_val ELSE false_val END"))
        
        toolbar_layout.addWidget(snip_select)
        toolbar_layout.addWidget(snip_groupby)
        toolbar_layout.addWidget(snip_sum)
        toolbar_layout.addWidget(snip_case)
        toolbar_layout.addStretch()
        right_layout.addLayout(toolbar_layout)
        
        self.sql_editor = QPlainTextEdit()
        self.sql_editor.setPlaceholderText("Write your SQL query here. You can query the 'dataset' view.")
        font = QFont("Consolas", 12)
        self.sql_editor.setFont(font)
        right_layout.addWidget(self.sql_editor)
        
        # Action Bar
        action_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        
        self.export_btn = QPushButton("Export Results")
        self.export_btn.clicked.connect(self.export_results)
        
        self.execute_btn = QPushButton("Execute (F5)")
        self.execute_btn.setObjectName("executeBtn")
        self.execute_btn.setMinimumWidth(150)
        self.execute_btn.clicked.connect(self.execute_query)
        self.execute_btn.setShortcut("F5")
        
        action_layout.addWidget(self.status_label)
        action_layout.addStretch()
        action_layout.addWidget(self.export_btn)
        action_layout.addWidget(self.execute_btn)
        right_layout.addLayout(action_layout)
        
        # Add Editor to vertical splitter
        main_splitter.addWidget(right_pane)
        
        # --- BOTTOM PANE (Table) ---
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Enable sorting on the table view!
        self.table_view.setSortingEnabled(True)
        
        main_splitter.addWidget(self.table_view)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        
        top_splitter.addWidget(main_splitter)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(top_splitter)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)")
        if file_path:
            self.file_path_edit.setText(file_path)

    def refresh_scripts_list(self):
        self.scripts_list.clear()
        for name in self.saved_scripts.keys():
            self.scripts_list.addItem(name)

    def save_current_script(self):
        text = self.sql_editor.toPlainText().strip()
        if not text:
            return
            
        name, ok = QInputDialog.getText(self, "Save Script", "Enter script name:")
        if ok and name:
            self.saved_scripts[name] = text
            self.save_scripts()
            self.refresh_scripts_list()

    def delete_current_script(self):
        item = self.scripts_list.currentItem()
        if item:
            name = item.text()
            if name in self.saved_scripts:
                del self.saved_scripts[name]
                self.save_scripts()
                self.refresh_scripts_list()

    def load_script_to_editor(self, item):
        name = item.text()
        if name in self.saved_scripts:
            self.sql_editor.setPlainText(self.saved_scripts[name])

    def load_dataset(self):
        file_path = self.file_path_edit.text()
        if not file_path: return
        
        self.status_label.setText(f"Loading {file_path} into DuckDB view...")
        QApplication.processEvents()
        
        success, err = self.db.load_csv(file_path)
        if not success:
            QMessageBox.critical(self, "Load Error", err)
            self.status_label.setText("Load failed.")
            return
            
        # Update schema viewer
        schema = self.db.get_schema()
        self.schema_tree.clear()
        for col in schema:
            item = QTreeWidgetItem([col['name'], col['type']])
            self.schema_tree.addTopLevelItem(item)
            
        self.status_label.setText(f"Loaded {file_path}. You can now query 'dataset'.")

    def execute_query(self):
        query = self.sql_editor.toPlainText().strip()
        if not query: return
        
        self.status_label.setText("Executing query...")
        QApplication.processEvents()
        
        try:
            total_rows = self.db.get_custom_query_total_rows(query)
            
            if total_rows == 0:
                self.status_label.setText("Query returned 0 rows.")
                self.table_view.setModel(None)
                return
                
            self.model = CSVTableModel(self.db, query, total_rows)
            self.table_view.setModel(self.model)
            # Remove resizeColumnsToContents to prevent UI freeze on large datasets
            # self.table_view.resizeColumnsToContents()
            
            self.status_label.setText(f"Query returned {total_rows} rows.")
        except Exception as e:
            QMessageBox.critical(self, "Query Error", str(e))
            self.status_label.setText("Error executing query.")

    def export_results(self):
        query = self.sql_editor.toPlainText().strip()
        if not query: return
        
        out_file, _ = QFileDialog.getSaveFileName(self, "Export CSV", "export.csv", "CSV Files (*.csv)")
        if not out_file: return
        
        self.status_label.setText("Exporting data...")
        QApplication.processEvents()
        
        success, err = self.db.export_custom_query(query, out_file)
        if success:
            self.status_label.setText(f"Exported successfully to {os.path.basename(out_file)}")
            QMessageBox.information(self, "Success", f"Data exported successfully to {out_file}")
        else:
            self.status_label.setText("Export failed.")
            QMessageBox.critical(self, "Export Error", f"Failed to export data:\n{err}")

    def closeEvent(self, event):
        """Clean up resources before closing the application."""
        if hasattr(self, 'db'):
            self.db.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
