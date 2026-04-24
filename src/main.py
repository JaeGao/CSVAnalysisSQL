import sys
import os
import glob
import json
import sqlparse
import time
import atexit
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QLabel, QTableView, QHeaderView,
    QMessageBox, QSplitter, QListWidget, QPlainTextEdit, QTreeWidget, QTreeWidgetItem,
    QFileDialog, QInputDialog, QLineEdit, QCompleter, QProgressBar, QMenu,
    QAbstractItemView, QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThreadPool, pyqtSlot, QTimer
from PyQt6.QtGui import QFont, QIcon, QShortcut, QKeySequence

from database import CSVDatabase
from utils import resource_path
from workers import LoadWorker, XlsxSheetScanWorker, XlsxLoadWorker, QueryExecutionWorker
from models import CSVTableModel
from editor import SQLEditor



class SheetSelectorDialog(QDialog):
    """Modal dialog for selecting one or more sheets from an XLSX workbook."""

    def __init__(self, sheet_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Sheets")
        self.setMinimumWidth(340)
        self.setMinimumHeight(320)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Select the sheets to load:"))

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.addItems(sheet_names)
        # Pre-select all sheets
        self._list.selectAll()
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        sel_all_btn = QPushButton("Select All")
        sel_all_btn.clicked.connect(self._list.selectAll)
        desel_all_btn = QPushButton("Deselect All")
        desel_all_btn.clicked.connect(self._list.clearSelection)
        btn_row.addWidget(sel_all_btn)
        btn_row.addWidget(desel_all_btn)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sheets(self):
        return [item.text() for item in self._list.selectedItems()]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSVAnalysisSQL")
        self.setWindowIcon(QIcon(resource_path("icon.png")))
        self.resize(1200, 800)
        
        CSVDatabase.cleanup_stale_sessions()
        self.db = CSVDatabase()
        atexit.register(self.db.close)
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
                qss = f.read()
            # Resolve relative image paths for PyInstaller compatibility
            qss = qss.replace("url(grip_horizontal.png)", f"url({resource_path('grip_horizontal.png').replace(os.sep, '/')})")
            qss = qss.replace("url(grip_vertical.png)", f"url({resource_path('grip_vertical.png').replace(os.sep, '/')})")
            self.setStyleSheet(qss)
        except Exception as e:
            print(f"Could not load stylesheet: {e}")
            
        self.setup_ui()
        self.update_autocomplete()

    def load_scripts(self):
        import shutil
        if not os.path.exists(self.scripts_file):
            bundled_scripts = resource_path("scripts.json")
            if os.path.exists(bundled_scripts) and os.path.abspath(bundled_scripts) != os.path.abspath(self.scripts_file):
                try:
                    shutil.copy2(bundled_scripts, self.scripts_file)
                except Exception as e:
                    print(f"Could not copy bundled scripts: {e}")

        if os.path.exists(self.scripts_file):
            try:
                with open(self.scripts_file, 'r') as f:
                    self.saved_scripts = json.load(f)
            except:
                self.saved_scripts = {}
        else:
            self.saved_scripts = {}
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
        
        # File loader - single button
        self.load_file_btn = QPushButton("Load File")
        self.load_file_btn.clicked.connect(self.on_load_file_clicked)
        left_layout.addWidget(self.load_file_btn)
        
        # Splitter between schema and saved scripts
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Schema section
        schema_pane = QWidget()
        schema_layout = QVBoxLayout(schema_pane)
        schema_layout.setContentsMargins(0, 4, 0, 0)
        
        schema_layout.addWidget(QLabel("Database Schema:"))
        self.schema_tree = QTreeWidget()
        self.schema_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.schema_tree.setHeaderLabels(["Column Name", "Type"])
        self.schema_tree.setAlternatingRowColors(True)
        self.schema_tree.header().setStretchLastSection(True)
        self.schema_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.schema_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        
        original_resize = self.schema_tree.resizeEvent
        def schema_resize(event):
            original_resize(event)
            self.schema_tree.setColumnWidth(0, int(self.schema_tree.viewport().width() * 0.60))
        self.schema_tree.resizeEvent = schema_resize
        self.schema_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(self.show_schema_context_menu)
        schema_layout.addWidget(self.schema_tree)
        
        schema_btn_layout = QHBoxLayout()
        self.copy_all_btn = QPushButton("Copy All Schemas")
        self.copy_all_btn.clicked.connect(self.copy_all_schemas)
        self.remove_dataset_btn = QPushButton("Remove Selected")
        self.remove_dataset_btn.clicked.connect(self.remove_selected_dataset)
        schema_btn_layout.addWidget(self.copy_all_btn)
        schema_btn_layout.addWidget(self.remove_dataset_btn)
        schema_layout.addLayout(schema_btn_layout)
        
        left_splitter.addWidget(schema_pane)
        
        # Saved Scripts section
        scripts_pane = QWidget()
        scripts_layout = QVBoxLayout(scripts_pane)
        scripts_layout.setContentsMargins(0, 4, 0, 0)
        
        scripts_layout.addWidget(QLabel("Saved Scripts:"))
        self.scripts_list = QListWidget()
        self.refresh_scripts_list()
        self.scripts_list.itemDoubleClicked.connect(self.load_script_to_editor)
        scripts_layout.addWidget(self.scripts_list)
        
        script_btn_layout = QHBoxLayout()
        save_script_btn = QPushButton("Save")
        save_script_btn.clicked.connect(self.save_current_script)
        del_script_btn = QPushButton("Delete")
        del_script_btn.clicked.connect(self.delete_current_script)
        script_btn_layout.addWidget(save_script_btn)
        script_btn_layout.addWidget(del_script_btn)
        scripts_layout.addLayout(script_btn_layout)
        
        left_splitter.addWidget(scripts_pane)
        
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        
        left_layout.addWidget(left_splitter)
        
        parent_splitter.addWidget(left_pane)

    def _setup_right_pane(self, parent_splitter):
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Editor Toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(QLabel("History:"))
        
        self.query_history = []
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(200)
        self.history_combo.addItem("--- Recent Queries ---")
        self.history_combo.currentIndexChanged.connect(self.load_history_item)
        toolbar_layout.addWidget(self.history_combo)
        
        toolbar_layout.addSpacing(10)
        
        format_btn = QPushButton("Format")
        format_btn.clicked.connect(self.format_sql)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_editor)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self.copy_query)
        save_view_btn = QPushButton("Save View")
        save_view_btn.clicked.connect(self.save_as_view)
        
        toolbar_layout.addWidget(format_btn)
        toolbar_layout.addWidget(clear_btn)
        toolbar_layout.addWidget(copy_btn)
        toolbar_layout.addWidget(save_view_btn)
        
        toolbar_layout.addStretch()
        right_layout.addLayout(toolbar_layout)
        
        self.sql_editor = SQLEditor()
        self.sql_editor.setPlaceholderText("Write your SQL query here.")
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
        self.execute_btn.clicked.connect(self.on_execute_clicked)
        
        self.execute_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.execute_shortcut.activated.connect(self.on_execute_clicked)
        self.execute_shortcut_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        self.execute_shortcut_enter.activated.connect(self.on_execute_clicked)
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
        self.table_view.setCornerButtonEnabled(False)

        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table_view)
        copy_shortcut.activated.connect(self._copy_table_selection)

        parent_splitter.addWidget(self.table_view)
        parent_splitter.setStretchFactor(0, 40)
        parent_splitter.setStretchFactor(1, 60)

    def on_load_file_clicked(self):
        if getattr(self, 'is_loading_file', False):
            self.cancel_operation()
        else:
            self.load_file()

    def on_execute_clicked(self):
        if getattr(self, 'is_executing_query', False):
            self.cancel_operation()
        else:
            self.execute_query()

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "",
            "Supported Files (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx);;All Files (*)"
        )
        if not file_path:
            return

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".xlsx":
            self._start_xlsx_scan(file_path)
        else:
            self._start_csv_load(file_path)

    def _start_csv_load(self, file_path):
        self.current_loading_file = os.path.basename(file_path)
        self.loading_dots = 0
        self.set_ui_loading_state(True, operation="load")
        self.animate_loading_text()
        self.loading_timer.start(400)

        worker = LoadWorker(self.db, file_path)
        worker.signals.finished.connect(self._on_load_finished)
        self.threadpool.start(worker)

    def _start_xlsx_scan(self, file_path):
        self.current_loading_file = os.path.basename(file_path)
        self.status_label.setText(f"Reading sheet list from {self.current_loading_file}...")
        self.set_ui_loading_state(True, operation="load")
        QApplication.processEvents()

        worker = XlsxSheetScanWorker(self.db, file_path)
        worker.signals.finished.connect(self._on_xlsx_scan_finished)
        self.threadpool.start(worker)

    @pyqtSlot(str, list)
    def _on_xlsx_scan_finished(self, file_path, sheets):
        self.set_ui_loading_state(False)
        if not sheets:
            QMessageBox.critical(self, "Load Error",
                f"Could not read sheet names from {os.path.basename(file_path)}.\n"
                "Ensure the file is a valid XLSX workbook.")
            self.status_label.setText("Load failed.")
            return

        if len(sheets) == 1:
            # Single sheet — no dialog needed
            selected = sheets
        else:
            dialog = SheetSelectorDialog(sheets, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.status_label.setText("Load cancelled.")
                return
            selected = dialog.selected_sheets()
            if not selected:
                self.status_label.setText("No sheets selected.")
                return

        self._start_xlsx_load(file_path, selected)

    def _start_xlsx_load(self, file_path, sheet_names):
        self.current_loading_file = os.path.basename(file_path)
        self.loading_dots = 0
        self.set_ui_loading_state(True, operation="load")
        self.animate_loading_text()
        self.loading_timer.start(400)

        worker = XlsxLoadWorker(self.db, file_path, sheet_names)
        worker.signals.finished.connect(self._on_xlsx_load_finished)
        self.threadpool.start(worker)

    @pyqtSlot(bool, str, str)
    def _on_xlsx_load_finished(self, success, result, file_path):
        self.loading_timer.stop()
        self.set_ui_loading_state(False)
        if not success:
            if 'Interrupt' in result or 'interrupt' in result:
                self.status_label.setText("Load canceled by user.")
            else:
                QMessageBox.critical(self, "Load Error", result)
                self.status_label.setText("Load failed.")
            return

        self.refresh_schema_tree()
        self.update_autocomplete()
        table_names = result
        self.status_label.setText(
            f"Loaded {os.path.basename(file_path)}: tables {table_names}."
        )


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

    def animate_loading_text(self):
        self.loading_dots = (self.loading_dots + 1) % 4
        dots = "." * self.loading_dots
        self.status_label.setText(f"Loading {self.current_loading_file}{dots}")

    @pyqtSlot(bool, str, str)
    def _on_load_finished(self, success, err_or_table, file_path):
        self.loading_timer.stop()
        self.set_ui_loading_state(False)
            
        if not success:
            if 'Interrupt' in err_or_table or 'interrupt' in err_or_table:
                self.status_label.setText("Load canceled by user.")
            else:
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
        if not item:
            return
            
        menu = QMenu()
        
        if item.parent() is not None:
            # It's a column
            selected_items = self.schema_tree.selectedItems()
            col_items = [it for it in selected_items if it.parent() is not None]
            
            # If clicked item is not in selection, use just the clicked item
            if item not in col_items:
                col_items = [item]
                
            col_names = [it.text(0) for it in col_items]
            
            if len(col_names) > 1:
                action_text = f"Copy {len(col_names)} Columns"
            else:
                action_text = f"Copy '{col_names[0]}'"
                
            copy_col_action = menu.addAction(action_text)
            action = menu.exec(self.schema_tree.mapToGlobal(position))
            
            if action == copy_col_action:
                import re
                formatted_cols = [f'"{c}"' if not re.match(r'^[a-zA-Z0-9_]+$', c) else c for c in col_names]
                QApplication.clipboard().setText(", ".join(formatted_cols))
                self.status_label.setText(f"Copied {len(col_names)} column(s) to clipboard.")
            return
            
        table_name = item.text(0)
        copy_action = menu.addAction("Copy Schema")
        query_top_action = menu.addAction("Query Top 500 Rows")
        remove_action = menu.addAction(f"Remove '{table_name}'")
        
        action = menu.exec(self.schema_tree.mapToGlobal(position))
        
        if action == remove_action:
            self.remove_dataset(table_name)
        elif action == copy_action:
            self.copy_schema_to_clipboard(table_name)
        elif action == query_top_action:
            query = f'SELECT * FROM "{table_name}" LIMIT 500;'
            self.sql_editor.setPlainText(query)
            self.execute_query()
            
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
        schema_map = {}
        for table in tables:
            schema = self.db.get_schema(table)
            col_completions = []
            for col in schema:
                col_name = col['name']
                if not re.match(r'^[a-zA-Z0-9_]+$', col_name):
                    words.append(f'"{col_name}"')
                    col_completions.append(f'"{col_name}"')
                else:
                    words.append(col_name)
                    col_completions.append(col_name)
            schema_map[table] = col_completions
        
        words = list(set(words))
        words.sort()
        self.sql_editor.set_completions(words)
        self.sql_editor.set_schema_map(schema_map)

    def load_history_item(self, index):
        if index > 0 and index <= len(self.query_history):
            self.sql_editor.setPlainText(self.query_history[index - 1])

    def format_sql(self):
        query = self.sql_editor.toPlainText().strip()
        if query:
            formatted = sqlparse.format(query, reindent=True, keyword_case='upper')
            self.sql_editor.setPlainText(formatted)

    def clear_editor(self):
        self.sql_editor.clear()

    def copy_query(self):
        QApplication.clipboard().setText(self.sql_editor.toPlainText())
        self.status_label.setText("Query copied to clipboard.")

    def _copy_table_selection(self):
        indexes = self.table_view.selectedIndexes()
        if not indexes:
            return
        rows = sorted(set(i.row() for i in indexes))
        cols = sorted(set(i.column() for i in indexes))
        model = self.table_view.model()
        lines = []
        for row in rows:
            cells = [str(model.index(row, col).data() or '') for col in cols]
            lines.append('\t'.join(cells))
        QApplication.clipboard().setText('\n'.join(lines))

    def save_as_view(self):
        query = self.sql_editor.toPlainText().strip()
        if not query: return
        
        view_name, ok = QInputDialog.getText(self, "Save as View", "Enter view name:")
        if ok and view_name:
            view_name = self.db.sanitize_table_name(view_name)
            try:
                self.db.con.execute(f'CREATE OR REPLACE VIEW "{view_name}" AS {query}')
                self.refresh_schema_tree()
                self.status_label.setText(f"View '{view_name}' created successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create view: {e}")



    def set_ui_loading_state(self, is_loading, operation=None):
        """Disables UI elements to prevent concurrent operations during load or query."""
        is_enabled = not is_loading
        self.export_btn.setEnabled(is_enabled)
        self.copy_all_btn.setEnabled(is_enabled)
        self.remove_dataset_btn.setEnabled(is_enabled)
        self.schema_tree.setEnabled(is_enabled)
        self.history_combo.setEnabled(is_enabled)
        
        if is_loading:
            if operation == "query":
                self.is_executing_query = True
                self.execute_btn.setText("Cancel Query")
                self.execute_btn.setEnabled(True)
                self.load_file_btn.setEnabled(False)
            elif operation == "load":
                self.is_loading_file = True
                self.load_file_btn.setText("Cancel Load")
                self.load_file_btn.setEnabled(True)
                self.execute_btn.setEnabled(False)
        else:
            self.is_executing_query = False
            self.is_loading_file = False
            self.execute_btn.setText("Execute (F5)")
            self.execute_btn.setEnabled(True)
            self.load_file_btn.setText("Load File")
            self.load_file_btn.setEnabled(True)
        
    def cancel_operation(self):
        self.db.interrupt()
        self.status_label.setText("Canceling...")
        if getattr(self, 'is_executing_query', False):
            self.execute_btn.setEnabled(False)
        if getattr(self, 'is_loading_file', False):
            self.load_file_btn.setEnabled(False)

    def execute_query(self):
        query = self.sql_editor.toPlainText().strip()
        if not query: return
        
        self.status_label.setText("Executing query...")
        self.set_ui_loading_state(True, operation="query")
        self.loading_dots = 0
        self.current_loading_file = "query"
        self.query_start_time = time.time()
        self.loading_timer.start(400)
        
        worker = QueryExecutionWorker(self.db, query)
        worker.signals.finished.connect(self._on_query_execution_finished)
        self.threadpool.start(worker)

    @pyqtSlot(bool, int, str, str)
    def _on_query_execution_finished(self, success, total_rows, err_msg, query):
        self.loading_timer.stop()
        self.set_ui_loading_state(False)
        
        elapsed = time.time() - getattr(self, 'query_start_time', time.time())
        
        if not success:
            if 'Interrupt' in err_msg or 'interrupt' in err_msg:
                self.status_label.setText(f"Query canceled after {elapsed:.5f}s.")
            else:
                QMessageBox.critical(self, "Query Error", err_msg)
                self.status_label.setText(f"Error executing query (failed after {elapsed:.5f}s).")
            return

        if total_rows == 0:
            self.status_label.setText(f"Query returned 0 rows in {elapsed:.5f}s.")
            self.table_view.setModel(None)
            return
            
        try:
            self.model = CSVTableModel(self.db, query, total_rows)
            self.table_view.setModel(self.model)
            # Remove resizeColumnsToContents to prevent UI freeze on large datasets
            # self.table_view.resizeColumnsToContents()
            
            # Ensure columns are wide enough for their headers
            font_metrics = self.table_view.fontMetrics()
            for i in range(self.model.columnCount()):
                header_text = str(self.model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole))
                min_width = font_metrics.horizontalAdvance(header_text) + 35 # add padding
                if self.table_view.columnWidth(i) < min_width:
                    self.table_view.setColumnWidth(i, min_width)
            
            self.status_label.setText(f"Query returned {total_rows} rows in {elapsed:.5f}s.")
            
            if not self.query_history or self.query_history[0] != query:
                self.query_history.insert(0, query)
                self.query_history = self.query_history[:20]
                
                self.history_combo.blockSignals(True)
                self.history_combo.clear()
                self.history_combo.addItem("--- Recent Queries ---")
                for q in self.query_history:
                    display_q = q.replace('\n', ' ')
                    if len(display_q) > 40:
                        display_q = display_q[:37] + "..."
                    self.history_combo.addItem(display_q)
                self.history_combo.blockSignals(False)
                
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
