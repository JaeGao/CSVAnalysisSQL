import sys
import os
import json
import re
import datetime
import atexit
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QHeaderView,
    QMessageBox, QSplitter, QListWidget, QTreeWidget,
    QTreeWidgetItem, QFileDialog, QInputDialog, QTabWidget, QTabBar,
    QAbstractItemView, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QMenu
)
from PyQt6.QtCore import Qt, QThreadPool, pyqtSlot
from PyQt6.QtGui import QFont, QIcon, QAction

from database import CSVDatabase
from utils import resource_path
from workers import LoadWorker, XlsxSheetScanWorker, XlsxLoadWorker
from tab import QueryTab


_PLUS_TAB = "+"


# ── Dialogs ───────────────────────────────────────────────────────────────────

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
        self._list.selectAll()
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_all.clicked.connect(self._list.selectAll)
        desel_all = QPushButton("Deselect All")
        desel_all.clicked.connect(self._list.clearSelection)
        btn_row.addWidget(sel_all)
        btn_row.addWidget(desel_all)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sheets(self):
        return [item.text() for item in self._list.selectedItems()]


class WorkspaceManagerDialog(QDialog):
    """List saved workspaces with Open / Delete actions."""

    def __init__(self, workspaces_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Workspaces")
        self.setMinimumSize(480, 320)
        self.workspaces_dir = workspaces_dir
        self.selected_path = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Saved workspaces:"))

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Last Modified"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        open_btn   = QPushButton("Open")
        delete_btn = QPushButton("Delete")
        close_btn  = QPushButton("Close")
        open_btn.clicked.connect(self._on_open)
        delete_btn.clicked.connect(self._on_delete)
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(open_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._refresh()

    def _refresh(self):
        self.table.setRowCount(0)
        if not os.path.isdir(self.workspaces_dir):
            return
        entries = []
        for fname in os.listdir(self.workspaces_dir):
            if fname.endswith(".json"):
                path  = os.path.join(self.workspaces_dir, fname)
                name  = fname[:-5]
                mtime = os.path.getmtime(path)
                entries.append((name, path, mtime))
        entries.sort(key=lambda x: x[2], reverse=True)

        for name, path, mtime in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, path)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(dt_str))

    def _selected_row_path(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _on_open(self):
        path = self._selected_row_path()
        if path:
            self.selected_path = path
            self.accept()

    def _on_delete(self):
        path = self._selected_row_path()
        if not path:
            return
        name = os.path.basename(path)[:-5]
        reply = QMessageBox.question(
            self, "Delete Workspace",
            f"Permanently delete workspace '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(path)
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not delete workspace:\n{e}")


# ── Main window ───────────────────────────────────────────────────────────────

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

        self.scripts_file    = os.path.join(app_dir, "scripts.json")
        self.workspaces_dir  = os.path.join(app_dir, "workspaces")

        self.saved_scripts         = {}
        self.current_workspace_name = None  # None = unsaved session

        # Loaded-file tracking for workspace persistence.
        # Each record: {path, type, table_names, [sheets for xlsx]}
        self._loaded_file_records = []
        self._pending_load_info   = {}
        self._restore_file_queue  = []
        self._restore_total       = 0
        self._in_add_tab          = False
        self.is_loading_file      = False

        self.load_scripts()

        self.threadpool = QThreadPool()

        try:
            with open(resource_path("style.qss"), "r") as f:
                qss = f.read()
            qss = qss.replace(
                "url(grip_horizontal.png)",
                f"url({resource_path('grip_horizontal.png').replace(os.sep, '/')})"
            )
            qss = qss.replace(
                "url(grip_vertical.png)",
                f"url({resource_path('grip_vertical.png').replace(os.sep, '/')})"
            )
            self.setStyleSheet(qss)
        except Exception as e:
            print(f"Could not load stylesheet: {e}")

        self._setup_menu_bar()
        self.setup_ui()
        self.statusBar().setVisible(False)
        self.update_autocomplete()

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _setup_menu_bar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        load_action = QAction("Load File…", self)
        load_action.triggered.connect(self.load_file)
        file_menu.addAction(load_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        ws_menu = mb.addMenu("Workspace")

        new_action = QAction("New Workspace", self)
        new_action.triggered.connect(self.new_workspace)
        ws_menu.addAction(new_action)

        open_action = QAction("Open / Manage…", self)
        open_action.triggered.connect(self.open_workspace_dialog)
        ws_menu.addAction(open_action)

        ws_menu.addSeparator()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_workspace_action)
        ws_menu.addAction(save_action)

        save_as_action = QAction("Save As…", self)
        save_as_action.triggered.connect(self.save_workspace_as)
        ws_menu.addAction(save_as_action)

    # ── Workspace operations ──────────────────────────────────────────────────

    def _workspace_path(self, name):
        safe = re.sub(r'[^\w\- ]', '_', name).strip()
        if not safe:
            safe = "workspace"
        return os.path.join(self.workspaces_dir, f"{safe}.json")

    def _update_title(self):
        if self.current_workspace_name:
            self.setWindowTitle(f"CSVAnalysisSQL — {self.current_workspace_name}")
        else:
            self.setWindowTitle("CSVAnalysisSQL")

    def new_workspace(self):
        self._clear_session()
        self.current_workspace_name = None
        self._update_title()
        self._add_tab()
        self._set_status("New workspace.")

    def open_workspace_dialog(self):
        dialog = WorkspaceManagerDialog(self.workspaces_dir, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_path:
            self._load_workspace_from_file(dialog.selected_path)

    def save_workspace_action(self):
        if self.current_workspace_name:
            self._save_workspace_to_file(self.current_workspace_name)
        else:
            self.save_workspace_as()

    def save_workspace_as(self):
        name, ok = QInputDialog.getText(
            self, "Save Workspace As", "Workspace name:",
            text=self.current_workspace_name or "",
        )
        if ok and name.strip():
            self._save_workspace_to_file(name.strip())

    def _save_workspace_to_file(self, name):
        os.makedirs(self.workspaces_dir, exist_ok=True)

        seen_paths: set = set()
        files_to_save = []
        for record in self._loaded_file_records:
            path = record["path"]
            if path in seen_paths or not os.path.exists(path):
                continue
            seen_paths.add(path)
            entry = {"path": path, "type": record["type"]}
            if record["type"] == "xlsx":
                entry["sheets"] = record.get("sheets", [])
            files_to_save.append(entry)

        tabs_to_save = []
        active_real  = 0
        real_count   = 0
        current_tab  = self.current_tab()
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab):
                tabs_to_save.append({
                    "name": self.tab_widget.tabText(i),
                    "sql":  w.sql_text(),
                })
                if w is current_tab:
                    active_real = real_count
                real_count += 1

        workspace = {
            "version":      1,
            "name":         name,
            "loaded_files": files_to_save,
            "tabs":         tabs_to_save,
            "active_tab":   active_real,
        }

        path = self._workspace_path(name)
        try:
            with open(path, 'w') as f:
                json.dump(workspace, f, indent=4)
            self.current_workspace_name = name
            self._update_title()
            self._set_status(f"Workspace '{name}' saved.")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save workspace:\n{e}")

    def _load_workspace_from_file(self, path):
        try:
            with open(path, 'r') as f:
                workspace = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Could not open workspace:\n{e}")
            return

        self._clear_session()
        self._restore_workspace(workspace)
        self.current_workspace_name = workspace.get("name", os.path.basename(path)[:-5])
        self._update_title()
        self._set_status(f"Workspace '{self.current_workspace_name}' loaded.")

    def _clear_session(self):
        """Remove all loaded tables and tabs to start fresh."""
        self._restore_file_queue = []

        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab) and w.is_executing_query:
                w._cancel_query()

        # Guard so that Qt making "+" current during removal doesn't trigger _add_tab
        self._in_add_tab = True
        try:
            for i in range(self.tab_widget.count() - 1, -1, -1):
                if isinstance(self.tab_widget.widget(i), QueryTab):
                    w = self.tab_widget.widget(i)
                    self.tab_widget.removeTab(i)
                    w.deleteLater()
        finally:
            self._in_add_tab = False

        for table in list(self.db.get_tables()):
            self.db.remove_table(table)

        self._loaded_file_records.clear()
        self.refresh_schema_tree()
        self.update_autocomplete()

    def _restore_workspace(self, workspace):
        tabs = workspace.get("tabs", [])
        if not tabs:
            self._add_tab()
            return

        for i, tab_data in enumerate(tabs):
            tab = self._add_tab(name=tab_data.get("name", f"Query {i + 1}"))
            tab.set_sql_text(tab_data.get("sql", ""))

        # Set active tab (index among real tabs)
        active_real = workspace.get("active_tab", 0)
        real_count  = 0
        for i in range(self.tab_widget.count()):
            if isinstance(self.tab_widget.widget(i), QueryTab):
                if real_count == active_real:
                    self.tab_widget.setCurrentIndex(i)
                    break
                real_count += 1

        # Queue file re-loads
        self._restore_file_queue = [
            f for f in workspace.get("loaded_files", [])
            if os.path.exists(f.get("path", ""))
        ]
        self._restore_total = len(self._restore_file_queue)
        self._restore_next_file()

    def _restore_next_file(self):
        if not self._restore_file_queue:
            return
        info  = self._restore_file_queue.pop(0)
        path  = info["path"]
        ftype = info.get("type", "csv")
        current = self._restore_total - len(self._restore_file_queue)
        basename = os.path.basename(path)
        if ftype == "csv":
            self._start_csv_load(path)
        elif ftype == "xlsx":
            sheets = info.get("sheets", [])
            if sheets:
                self._start_xlsx_load(path, sheets)
            else:
                self._restore_next_file()
                return
        self._set_status(f"Loading file {current} of {self._restore_total}: {basename}…")

    # ── UI setup ──────────────────────────────────────────────────────────────

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._setup_left_pane(top_splitter)
        self._setup_tab_area(top_splitter)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 3)

        main_layout.addWidget(top_splitter)

    def _setup_left_pane(self, parent_splitter):
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.load_file_btn = QPushButton("Load File")
        self.load_file_btn.clicked.connect(self.on_load_file_clicked)
        left_layout.addWidget(self.load_file_btn)

        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # Schema pane
        schema_pane   = QWidget()
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
            self.schema_tree.setColumnWidth(
                0, int(self.schema_tree.viewport().width() * 0.60)
            )
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

        # Scripts pane
        scripts_pane   = QWidget()
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
        del_script_btn  = QPushButton("Delete")
        del_script_btn.clicked.connect(self.delete_current_script)
        script_btn_layout.addWidget(save_script_btn)
        script_btn_layout.addWidget(del_script_btn)
        scripts_layout.addLayout(script_btn_layout)

        left_splitter.addWidget(scripts_pane)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)

        left_layout.addWidget(left_splitter)
        parent_splitter.addWidget(left_pane)

    def _setup_tab_area(self, parent_splitter):
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(False)   # we manage our own close buttons
        self.tab_widget.tabBar().tabBarDoubleClicked.connect(self._rename_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        parent_splitter.addWidget(self.tab_widget)

        # First real tab, then the permanent "+" tab
        self._add_tab()
        self._append_plus_tab()

    def _append_plus_tab(self):
        placeholder = QWidget()
        idx = self.tab_widget.addTab(placeholder, _PLUS_TAB)
        # Hide the close button on the "+" tab
        self.tab_widget.tabBar().setTabButton(
            idx, QTabBar.ButtonPosition.RightSide, None
        )
        self.tab_widget.tabBar().setTabButton(
            idx, QTabBar.ButtonPosition.LeftSide, None
        )

    def _find_plus_tab(self):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == _PLUS_TAB:
                return i
        return -1

    # ── Tab management ────────────────────────────────────────────────────────

    def current_tab(self):
        w = self.tab_widget.currentWidget()
        if isinstance(w, QueryTab):
            return w
        # Fall back to the last real tab if "+" is somehow current
        for i in range(self.tab_widget.count() - 1, -1, -1):
            if isinstance(self.tab_widget.widget(i), QueryTab):
                return self.tab_widget.widget(i)
        return None

    def _next_tab_name(self):
        """Return the lowest 'Query N' name not already used by an open tab."""
        used = set()
        for i in range(self.tab_widget.count()):
            text = self.tab_widget.tabText(i)
            if text.startswith("Query "):
                try:
                    used.add(int(text[6:]))
                except ValueError:
                    pass
        n = 1
        while n in used:
            n += 1
        return f"Query {n}"

    def _add_tab(self, name: str = None, sql: str = "") -> QueryTab:
        self._in_add_tab = True
        try:
            tab = QueryTab(self.db, self.threadpool)
            tab.schema_changed.connect(self._on_schema_changed)
            if sql:
                tab.set_sql_text(sql)
            self._push_autocomplete_to(tab)

            tab_name = name or self._next_tab_name()
            plus_idx = self._find_plus_tab()

            if plus_idx >= 0:
                self.tab_widget.insertTab(plus_idx, tab, tab_name)
                new_idx = plus_idx
            else:
                new_idx = self.tab_widget.addTab(tab, tab_name)

            # Custom styled close button — replaces Qt's invisible platform button
            close_btn = QPushButton("×")
            close_btn.setFixedSize(18, 18)
            close_btn.setObjectName("tabCloseBtn")
            close_btn.clicked.connect(lambda _checked, t=tab: self._close_tab_by_widget(t))
            self.tab_widget.tabBar().setTabButton(
                new_idx, QTabBar.ButtonPosition.RightSide, close_btn
            )

            self.tab_widget.setCurrentIndex(new_idx)
            return tab
        finally:
            self._in_add_tab = False

    def _close_tab_by_widget(self, tab: QueryTab):
        idx = self.tab_widget.indexOf(tab)
        if idx >= 0:
            self._close_tab(idx)

    def _close_tab(self, index: int):
        if self.tab_widget.tabText(index) == _PLUS_TAB:
            return
        real_count = sum(
            1 for i in range(self.tab_widget.count())
            if isinstance(self.tab_widget.widget(i), QueryTab)
        )
        if real_count <= 1:
            return

        # Pre-select a different real tab BEFORE removing so Qt never auto-
        # selects "+" (which would trigger _on_tab_changed → _add_tab).
        if self.tab_widget.currentIndex() == index:
            safe = next(
                (i for i in range(self.tab_widget.count())
                 if i != index and isinstance(self.tab_widget.widget(i), QueryTab)),
                -1,
            )
            if safe >= 0:
                self.tab_widget.setCurrentIndex(safe)

        w = self.tab_widget.widget(index)
        if isinstance(w, QueryTab) and w.is_executing_query:
            w._cancel_query()
        self.tab_widget.removeTab(index)
        if isinstance(w, QueryTab):
            w.deleteLater()

    def _rename_tab(self, index: int):
        if index < 0 or self.tab_widget.tabText(index) == _PLUS_TAB:
            return
        current_name = self.tab_widget.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "Rename Tab", "Tab name:", text=current_name
        )
        if ok and new_name.strip():
            self.tab_widget.setTabText(index, new_name.strip())

    def _set_status(self, msg: str):
        tab = self.current_tab()
        if tab:
            tab.set_status(msg)

    def _on_tab_changed(self, index: int):
        if self._in_add_tab:
            return
        if self.tab_widget.tabText(index) == _PLUS_TAB:
            self._add_tab()

    def _on_schema_changed(self):
        self.refresh_schema_tree()
        self.update_autocomplete()

    # ── Autocomplete ──────────────────────────────────────────────────────────

    def _build_completions(self):
        keywords = [
            "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING",
            "LIMIT", "OFFSET", "JOIN", "LEFT JOIN", "ON", "AS",
            "COUNT", "SUM", "AVG", "MIN", "MAX",
            "CASE", "WHEN", "THEN", "ELSE", "END",
        ]
        tables     = self.db.get_tables()
        words      = list(keywords) + list(tables)
        schema_map = {}
        for table in tables:
            col_completions = []
            for col in self.db.get_schema(table):
                col_name = col['name']
                if not re.match(r'^[a-zA-Z0-9_]+$', col_name):
                    entry = f'"{col_name}"'
                else:
                    entry = col_name
                words.append(entry)
                col_completions.append(entry)
            schema_map[table] = col_completions
        return sorted(set(words)), schema_map

    def _push_autocomplete_to(self, tab: QueryTab):
        words, schema_map = self._build_completions()
        tab.update_autocomplete(words, schema_map)

    def update_autocomplete(self):
        words, schema_map = self._build_completions()
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab):
                w.update_autocomplete(words, schema_map)

    # ── File loading ──────────────────────────────────────────────────────────

    def on_load_file_clicked(self):
        if self.is_loading_file:
            self._cancel_load()
        else:
            self.load_file()

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "",
            "Supported Files (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx);;All Files (*)",
        )
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".xlsx":
            self._start_xlsx_scan(file_path)
        else:
            self._start_csv_load(file_path)

    def _start_csv_load(self, file_path):
        self._pending_load_info = {"path": file_path, "type": "csv"}
        self._set_loading_state(True)
        self._set_status(f"Loading {os.path.basename(file_path)}…")

        worker = LoadWorker(self.db, file_path)
        worker.signals.finished.connect(self._on_load_finished)
        self.threadpool.start(worker)

    def _start_xlsx_scan(self, file_path):
        self._set_loading_state(True)
        self._set_status(f"Reading sheet list from {os.path.basename(file_path)}…")
        worker = XlsxSheetScanWorker(self.db, file_path)
        worker.signals.finished.connect(self._on_xlsx_scan_finished)
        self.threadpool.start(worker)

    @pyqtSlot(str, list)
    def _on_xlsx_scan_finished(self, file_path, sheets):
        self._set_loading_state(False)
        if not sheets:
            QMessageBox.critical(
                self, "Load Error",
                f"Could not read sheet names from {os.path.basename(file_path)}.",
            )
            self._set_status("Load failed.")
            self._restore_next_file()
            return

        if len(sheets) == 1:
            selected = sheets
        else:
            dialog = SheetSelectorDialog(sheets, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._set_status("Load cancelled.")
                self._restore_next_file()
                return
            selected = dialog.selected_sheets()
            if not selected:
                self._set_status("No sheets selected.")
                self._restore_next_file()
                return

        self._start_xlsx_load(file_path, selected)

    def _start_xlsx_load(self, file_path, sheet_names):
        self._pending_load_info = {
            "path": file_path, "type": "xlsx", "sheets": sheet_names
        }
        self._set_loading_state(True)
        self._set_status(f"Loading {os.path.basename(file_path)}…")

        worker = XlsxLoadWorker(self.db, file_path, sheet_names)
        worker.signals.finished.connect(self._on_xlsx_load_finished)
        self.threadpool.start(worker)

    @pyqtSlot(bool, str, str)
    def _on_load_finished(self, success, err_or_table, file_path):
        self._set_loading_state(False)
        if not success:
            if 'Interrupt' in err_or_table or 'interrupt' in err_or_table:
                self._set_status("Load canceled.")
            else:
                QMessageBox.critical(self, "Load Error", err_or_table)
                self._set_status("Load failed.")
        else:
            info = dict(self._pending_load_info)
            info["table_names"] = [err_or_table]
            self._loaded_file_records.append(info)
            self.refresh_schema_tree()
            self.update_autocomplete()
            self._set_status(f"Loaded '{os.path.basename(file_path)}' → table '{err_or_table}'.")
        self._restore_next_file()

    @pyqtSlot(bool, str, str)
    def _on_xlsx_load_finished(self, success, result, file_path):
        self._set_loading_state(False)
        if not success:
            if 'Interrupt' in result or 'interrupt' in result:
                self._set_status("Load canceled.")
            else:
                QMessageBox.critical(self, "Load Error", result)
                self._set_status("Load failed.")
        else:
            table_names = [t.strip() for t in result.split(",")]
            info = dict(self._pending_load_info)
            info["table_names"] = table_names
            self._loaded_file_records.append(info)
            self.refresh_schema_tree()
            self.update_autocomplete()
            self._set_status(f"Loaded '{os.path.basename(file_path)}': {result}.")
        self._restore_next_file()

    def _set_loading_state(self, is_loading: bool):
        self.is_loading_file = is_loading
        is_enabled = not is_loading

        self.copy_all_btn.setEnabled(is_enabled)
        self.remove_dataset_btn.setEnabled(is_enabled)
        self.schema_tree.setEnabled(is_enabled)
        self.load_file_btn.setText("Cancel Load" if is_loading else "Load File")
        self.load_file_btn.setEnabled(True)

        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if isinstance(w, QueryTab):
                w.set_execute_enabled(is_enabled)

    def _cancel_load(self):
        self.db.interrupt()
        self._set_status("Canceling load…")
        self.load_file_btn.setEnabled(False)

    # ── Schema tree ───────────────────────────────────────────────────────────

    def refresh_schema_tree(self):
        self.schema_tree.clear()
        for table in self.db.get_tables():
            table_item = QTreeWidgetItem([table, "TABLE"])
            font = QFont()
            font.setBold(True)
            table_item.setFont(0, font)
            self.schema_tree.addTopLevelItem(table_item)
            for col in self.db.get_schema(table):
                table_item.addChild(QTreeWidgetItem([col['name'], col['type']]))
            table_item.setExpanded(True)

    def show_schema_context_menu(self, position):
        item = self.schema_tree.itemAt(position)
        if not item:
            return

        menu = QMenu()

        if item.parent() is not None:
            selected = self.schema_tree.selectedItems()
            col_items = [it for it in selected if it.parent() is not None]
            if item not in col_items:
                col_items = [item]
            col_names = [it.text(0) for it in col_items]
            action_text = (
                f"Copy {len(col_names)} Columns"
                if len(col_names) > 1
                else f"Copy '{col_names[0]}'"
            )
            copy_col_action = menu.addAction(action_text)
            action = menu.exec(self.schema_tree.mapToGlobal(position))
            if action == copy_col_action:
                formatted = [
                    f'"{c}"' if not re.match(r'^[a-zA-Z0-9_]+$', c) else c
                    for c in col_names
                ]
                QApplication.clipboard().setText(", ".join(formatted))
            return

        table_name    = item.text(0)
        copy_action   = menu.addAction("Copy Schema")
        query_top     = menu.addAction("Query Top 500 Rows")
        remove_action = menu.addAction(f"Remove '{table_name}'")

        action = menu.exec(self.schema_tree.mapToGlobal(position))
        if action == remove_action:
            self.remove_dataset(table_name)
        elif action == copy_action:
            self.copy_schema_to_clipboard(table_name)
        elif action == query_top:
            tab = self.current_tab()
            if tab:
                tab.set_sql_text(f'SELECT * FROM "{table_name}" LIMIT 500;')
                tab.execute_query()

    def copy_all_schemas(self):
        tables = self.db.get_tables()
        if not tables:
            QMessageBox.information(self, "Copy Schema", "No datasets loaded.")
            return
        self._copy_schemas_to_clipboard(tables)
        self._set_status(f"Copied {len(tables)} schemas to clipboard.")

    def copy_schema_to_clipboard(self, table_name):
        self._copy_schemas_to_clipboard([table_name])
        self._set_status(f"Copied schema for '{table_name}'.")

    def _copy_schemas_to_clipboard(self, tables_to_copy):
        schema_text = []
        for table_name in tables_to_copy:
            schema = self.db.get_schema(table_name)
            lines = [f"CREATE TABLE {table_name} ("]
            col_lines = [f'    "{col["name"]}" {col["type"]}' for col in schema]
            lines.append(",\n".join(col_lines))
            lines.append(");")
            schema_text.append("\n".join(lines))
        QApplication.clipboard().setText("\n\n".join(schema_text))

    def remove_selected_dataset(self):
        item = self.schema_tree.currentItem()
        if not item or item.parent() is not None:
            QMessageBox.warning(
                self, "Remove Dataset",
                "Please select a dataset (top-level item) to remove.",
            )
            return
        self.remove_dataset(item.text(0))

    def remove_dataset(self, table_name):
        reply = QMessageBox.question(
            self, "Confirm Remove",
            f"Remove dataset '{table_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        success, err = self.db.remove_table(table_name)
        if success:
            remaining = set(self.db.get_tables())
            self._loaded_file_records = [
                r for r in self._loaded_file_records
                if any(t in remaining for t in r.get("table_names", []))
            ]
            self.refresh_schema_tree()
            self.update_autocomplete()
            self._set_status(f"Removed '{table_name}'.")
        else:
            QMessageBox.critical(self, "Remove Error", err)

    # ── Scripts ───────────────────────────────────────────────────────────────

    def load_scripts(self):
        import shutil
        if not os.path.exists(self.scripts_file):
            bundled = resource_path("scripts.json")
            if (
                os.path.exists(bundled)
                and os.path.abspath(bundled) != os.path.abspath(self.scripts_file)
            ):
                try:
                    shutil.copy2(bundled, self.scripts_file)
                except Exception as e:
                    print(f"Could not copy bundled scripts: {e}")
        if os.path.exists(self.scripts_file):
            try:
                with open(self.scripts_file, 'r') as f:
                    self.saved_scripts = json.load(f)
            except Exception:
                self.saved_scripts = {}
        else:
            self.saved_scripts = {}
            self.save_scripts()

    def save_scripts(self):
        with open(self.scripts_file, 'w') as f:
            json.dump(self.saved_scripts, f, indent=4)

    def refresh_scripts_list(self):
        self.scripts_list.clear()
        for name in self.saved_scripts:
            self.scripts_list.addItem(name)

    def save_current_script(self):
        tab = self.current_tab()
        if not tab:
            return
        text = tab.sql_text().strip()
        if not text:
            return
        name, ok = QInputDialog.getText(self, "Save Script", "Enter script name:")
        if ok and name:
            self.saved_scripts[name] = text
            self.save_scripts()
            self.refresh_scripts_list()

    def delete_current_script(self):
        item = self.scripts_list.currentItem()
        if item and item.text() in self.saved_scripts:
            del self.saved_scripts[item.text()]
            self.save_scripts()
            self.refresh_scripts_list()

    def load_script_to_editor(self, item):
        tab = self.current_tab()
        if tab and item.text() in self.saved_scripts:
            tab.set_sql_text(self.saved_scripts[item.text()])

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if hasattr(self, 'db'):
            self.db.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
