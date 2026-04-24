import os
import time
import sqlparse
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QTableView, QHeaderView, QMessageBox, QFileDialog, QInputDialog,
    QSplitter, QApplication
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QShortcut, QKeySequence

from workers import QueryExecutionWorker
from models import CSVTableModel
from editor import SQLEditor


class QueryTab(QWidget):
    """Self-contained query tab: SQL editor + toolbar + results table."""

    schema_changed = pyqtSignal()

    def __init__(self, db, threadpool, parent=None):
        super().__init__(parent)
        self.db = db
        self.threadpool = threadpool

        self.query_history = []
        self.is_executing_query = False
        self._model = None
        self.query_start_time = 0.0
        self.loading_dots = 0

        self.loading_timer = QTimer()
        self.loading_timer.timeout.connect(self._animate_loading_text)

        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Editor pane ──────────────────────────────────────────────────────
        editor_pane = QWidget()
        editor_layout = QVBoxLayout(editor_pane)
        editor_layout.setContentsMargins(4, 4, 4, 0)
        editor_layout.setSpacing(4)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(4)
        toolbar_layout.addWidget(QLabel("History:"))

        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(200)
        self.history_combo.addItem("--- Recent Queries ---")
        self.history_combo.currentIndexChanged.connect(self._load_history_item)
        toolbar_layout.addWidget(self.history_combo)
        toolbar_layout.addSpacing(8)

        for label, slot in [
            ("Format", self.format_sql),
            ("Clear",  self.clear_editor),
            ("Copy",   self.copy_query),
            ("Save View", self.save_as_view),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar_layout.addWidget(btn)

        toolbar_layout.addStretch()
        editor_layout.addLayout(toolbar_layout)

        self.sql_editor = SQLEditor()
        self.sql_editor.setPlaceholderText("Write your SQL query here.")
        self.sql_editor.setFont(QFont("Consolas", 12))
        editor_layout.addWidget(self.sql_editor)

        action_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.export_btn = QPushButton("Export Results")
        self.export_btn.clicked.connect(self.export_results)

        self.execute_btn = QPushButton("Execute (F5)")
        self.execute_btn.setObjectName("executeBtn")
        self.execute_btn.setMinimumWidth(150)
        self.execute_btn.clicked.connect(self.on_execute_clicked)

        action_layout.addWidget(self.status_label, stretch=1)
        action_layout.addWidget(self.export_btn)
        action_layout.addWidget(self.execute_btn)
        editor_layout.addLayout(action_layout)

        splitter.addWidget(editor_pane)

        # ── Results pane ─────────────────────────────────────────────────────
        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.setSortingEnabled(True)
        self.table_view.setCornerButtonEnabled(False)

        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.table_view)
        copy_sc.activated.connect(self._copy_table_selection)

        splitter.addWidget(self.table_view)
        splitter.setStretchFactor(0, 40)
        splitter.setStretchFactor(1, 60)

        layout.addWidget(splitter)

    def _setup_shortcuts(self):
        for ks in ("Ctrl+Return", "Ctrl+Enter", "F5"):
            sc = QShortcut(QKeySequence(ks), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.on_execute_clicked)

    # ── Public interface ──────────────────────────────────────────────────────

    def sql_text(self):
        return self.sql_editor.toPlainText()

    def set_sql_text(self, text):
        self.sql_editor.setPlainText(text)

    def set_status(self, msg):
        self.status_label.setText(msg)

    def update_autocomplete(self, words, schema_map):
        self.sql_editor.set_completions(words)
        self.sql_editor.set_schema_map(schema_map)

    def set_execute_enabled(self, enabled):
        """Called by MainWindow during file loads to lock/unlock execute."""
        if not self.is_executing_query:
            self.execute_btn.setEnabled(enabled)

    # ── Execute / cancel ──────────────────────────────────────────────────────

    def on_execute_clicked(self):
        if self.is_executing_query:
            self._cancel_query()
        else:
            self.execute_query()

    def execute_query(self):
        query = self.sql_editor.toPlainText().strip()
        if not query:
            return

        self.status_label.setText("Executing query...")
        self.is_executing_query = True
        self.execute_btn.setText("Cancel Query")
        self.loading_dots = 0
        self.query_start_time = time.time()
        self.loading_timer.start(400)

        worker = QueryExecutionWorker(self.db, query)
        worker.signals.finished.connect(self._on_query_execution_finished)
        self.threadpool.start(worker)

    def _cancel_query(self):
        self.db.interrupt()
        self.status_label.setText("Canceling...")
        self.execute_btn.setEnabled(False)

    # ── Toolbar actions ───────────────────────────────────────────────────────

    def format_sql(self):
        query = self.sql_editor.toPlainText().strip()
        if query:
            self.sql_editor.setPlainText(
                sqlparse.format(query, reindent=True, keyword_case='upper')
            )

    def clear_editor(self):
        self.sql_editor.clear()

    def copy_query(self):
        QApplication.clipboard().setText(self.sql_editor.toPlainText())
        self.status_label.setText("Query copied to clipboard.")

    def save_as_view(self):
        query = self.sql_editor.toPlainText().strip()
        if not query:
            return

        view_name, ok = QInputDialog.getText(self, "Save as View", "Enter view name:")
        if ok and view_name:
            view_name = self.db.sanitize_table_name(view_name)
            try:
                self.db.con.execute(f'CREATE OR REPLACE VIEW "{view_name}" AS {query}')
                self.status_label.setText(f"View '{view_name}' created.")
                self.schema_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create view: {e}")

    def export_results(self):
        query = self.sql_editor.toPlainText().strip()
        if not query:
            return

        out_file, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "export.csv", "CSV Files (*.csv)"
        )
        if not out_file:
            return

        self.status_label.setText("Exporting data...")
        QApplication.processEvents()

        success, err = self.db.export_custom_query(query, out_file)
        if success:
            self.status_label.setText(f"Exported to {os.path.basename(out_file)}")
            QMessageBox.information(self, "Success", f"Data exported to {out_file}")
        else:
            self.status_label.setText("Export failed.")
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{err}")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _animate_loading_text(self):
        self.loading_dots = (self.loading_dots + 1) % 4
        dots = "." * self.loading_dots
        self.status_label.setText(f"Executing{dots}")

    @pyqtSlot(bool, int, str, str)
    def _on_query_execution_finished(self, success, total_rows, err_msg, query):
        self.loading_timer.stop()
        self.is_executing_query = False
        self.execute_btn.setText("Execute (F5)")
        self.execute_btn.setEnabled(True)

        elapsed = time.time() - self.query_start_time

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
            self._model = CSVTableModel(self.db, query, total_rows)
            self.table_view.setModel(self._model)

            font_metrics = self.table_view.fontMetrics()
            for i in range(self._model.columnCount()):
                header_text = str(self._model.headerData(
                    i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
                ))
                min_width = font_metrics.horizontalAdvance(header_text) + 35
                if self.table_view.columnWidth(i) < min_width:
                    self.table_view.setColumnWidth(i, min_width)

            self.status_label.setText(f"Query returned {total_rows:,} rows in {elapsed:.5f}s.")

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

    def _load_history_item(self, index):
        if 0 < index <= len(self.query_history):
            self.sql_editor.setPlainText(self.query_history[index - 1])

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
