import sys
import os
import glob
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QLabel, QTableView, QHeaderView,
    QMessageBox, QSplitter, QListWidget, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog, QInputDialog, QLineEdit, QCompleter, QProgressBar, QMenu
)
from PyQt6.QtCore import Qt, QThreadPool, pyqtSlot, QTimer
from PyQt6.QtGui import QFont, QIcon

from database import CSVDatabase
from utils import resource_path
from workers import LoadWorker
from models import CSVTableModel
from editor import SQLEditor

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
        
        self.threadpool = QThreadPool()
        
        # Load Stylesheet
        try:
            with open(resource_path("style.qss"), "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Could not load stylesheet: {e}")
            
        self.setup_ui()
        self.update_autocomplete()

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
        
        self._setup_left_pane(top_splitter)
        self._setup_right_pane(main_splitter)
        self._setup_bottom_pane(main_splitter)
        
        top_splitter.addWidget(main_splitter)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(top_splitter)

    def _setup_left_pane(self, parent_splitter):
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # File selector
        left_layout.addWidget(QLabel("1. Select Dataset:"))
        file_layout = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("No CSV selected")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_file)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_dataset)
        
        file_layout.addWidget(self.file_path_edit)
        file_layout.addWidget(browse_btn)
        file_layout.addWidget(load_btn)
        left_layout.addLayout(file_layout)
        
        # Schema Viewer
        left_layout.addWidget(QLabel("Database Schema:"))
        self.schema_tree = QTreeWidget()
        self.schema_tree.setHeaderLabels(["Column Name", "Type"])
        self.schema_tree.setAlternatingRowColors(True)
        self.schema_tree.header().setStretchLastSection(False)
        self.schema_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.schema_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.schema_tree.setColumnWidth(1, 100)
        self.schema_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(self.show_schema_context_menu)
        left_layout.addWidget(self.schema_tree)
        
        schema_btn_layout = QHBoxLayout()
        self.copy_all_btn = QPushButton("Copy All Schemas")
        self.copy_all_btn.clicked.connect(self.copy_all_schemas)
        self.remove_dataset_btn = QPushButton("Remove Selected")
        self.remove_dataset_btn.clicked.connect(self.remove_selected_dataset)
        schema_btn_layout.addWidget(self.copy_all_btn)
        schema_btn_layout.addWidget(self.remove_dataset_btn)
        left_layout.addLayout(schema_btn_layout)
        
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
        
        parent_splitter.addWidget(left_pane)

    def _setup_right_pane(self, parent_splitter):
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Editor Toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(QLabel("SQL Editor:"))
        
        # Snippets
        snip_select = QPushButton("SELECT *")
        snip_select.clicked.connect(lambda: self.sql_editor.insertPlainText("SELECT * FROM \n"))
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
        
        self.sql_editor = SQLEditor()
        self.sql_editor.setPlaceholderText("Write your SQL query here. Try Ctrl+Space for autocomplete.")
        font = QFont("Consolas", 12)
        self.sql_editor.setFont(font)
        right_layout.addWidget(self.sql_editor)
        
        # Action Bar
        action_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        
        self.loading_timer = QTimer()
        self.loading_timer.timeout.connect(self.animate_loading_text)
        self.loading_dots = 0
        self.current_loading_file = ""
        
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
        
        parent_splitter.addWidget(right_pane)

    def _setup_bottom_pane(self, parent_splitter):
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.setSortingEnabled(True)
        
        parent_splitter.addWidget(self.table_view)
        parent_splitter.setStretchFactor(0, 40)
        parent_splitter.setStretchFactor(1, 60)

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
        
        self.current_loading_file = os.path.basename(file_path)
        self.loading_dots = 0
        self.animate_loading_text()
        self.loading_timer.start(400)
        
        worker = LoadWorker(self.db, file_path)
        worker.signals.finished.connect(self._on_load_finished)
        self.threadpool.start(worker)

    def animate_loading_text(self):
        self.loading_dots = (self.loading_dots + 1) % 4
        dots = "." * self.loading_dots
        self.status_label.setText(f"Loading {self.current_loading_file}{dots}")

    @pyqtSlot(bool, str, str)
    def _on_load_finished(self, success, err_or_table, file_path):
        self.loading_timer.stop()
            
        if not success:
            QMessageBox.critical(self, "Load Error", err_or_table)
            self.status_label.setText("Load failed.")
            return
            
        table_name = err_or_table
        self.refresh_schema_tree()
        self.update_autocomplete()
            
        self.status_label.setText(f"Loaded {file_path}. You can now query '{table_name}'.")

    def remove_selected_dataset(self):
        item = self.schema_tree.currentItem()
        if not item or item.parent() is not None:
            QMessageBox.warning(self, "Remove Dataset", "Please select a dataset (top-level item) to remove.")
            return
            
        table_name = item.text(0)
        self.remove_dataset(table_name)

    def show_schema_context_menu(self, position):
        item = self.schema_tree.itemAt(position)
        if not item or item.parent() is not None:
            return
            
        table_name = item.text(0)
        menu = QMenu()
        copy_action = menu.addAction("Copy Schema")
        remove_action = menu.addAction(f"Remove '{table_name}'")
        
        action = menu.exec(self.schema_tree.mapToGlobal(position))
        
        if action == remove_action:
            self.remove_dataset(table_name)
        elif action == copy_action:
            self.copy_schema_to_clipboard(table_name)
            
    def copy_all_schemas(self):
        tables = self.db.get_tables()
        if not tables:
            QMessageBox.information(self, "Copy Schema", "No datasets loaded to copy.")
            return
            
        self._copy_schemas_to_clipboard(tables)
        self.status_label.setText(f"Copied {len(tables)} schemas to clipboard.")

    def copy_schema_to_clipboard(self, table_name):
        self._copy_schemas_to_clipboard([table_name])
        self.status_label.setText(f"Copied schema for '{table_name}' to clipboard.")

    def _copy_schemas_to_clipboard(self, tables_to_copy):
        schema_text = []
        for table_name in tables_to_copy:
            schema = self.db.get_schema(table_name)
            lines = [f"CREATE TABLE {table_name} ("]
            col_lines = []
            for col in schema:
                col_lines.append(f"    \"{col['name']}\" {col['type']}")
            lines.append(",\n".join(col_lines))
            lines.append(");")
            schema_text.append("\n".join(lines))
            
        final_text = "\n\n".join(schema_text)
        QApplication.clipboard().setText(final_text)
            
    def remove_dataset(self, table_name):
        reply = QMessageBox.question(self, "Confirm Remove", f"Are you sure you want to remove the dataset '{table_name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, err = self.db.remove_table(table_name)
            if success:
                self.refresh_schema_tree()
                self.update_autocomplete()
                self.status_label.setText(f"Removed dataset '{table_name}'.")
            else:
                QMessageBox.critical(self, "Remove Error", err)

    def refresh_schema_tree(self):
        self.schema_tree.clear()
        tables = self.db.get_tables()
        for table in tables:
            table_item = QTreeWidgetItem([table, "TABLE"])
            font = QFont()
            font.setBold(True)
            table_item.setFont(0, font)
            self.schema_tree.addTopLevelItem(table_item)
            
            schema = self.db.get_schema(table)
            for col in schema:
                col_item = QTreeWidgetItem([col['name'], col['type']])
                table_item.addChild(col_item)
            
            table_item.setExpanded(True)

    def update_autocomplete(self):
        import re
        words = ["SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET", "JOIN", "LEFT JOIN", "ON", "AS", "COUNT", "SUM", "AVG", "MIN", "MAX", "CASE", "WHEN", "THEN", "ELSE", "END"]
        tables = self.db.get_tables()
        words.extend(tables)
        for table in tables:
            schema = self.db.get_schema(table)
            for col in schema:
                col_name = col['name']
                if not re.match(r'^[a-zA-Z0-9_]+$', col_name):
                    words.append(f'"{col_name}"')
                else:
                    words.append(col_name)
        
        words = list(set(words))
        words.sort()
        self.sql_editor.set_completions(words)

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
