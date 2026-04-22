import re
from PyQt6.QtWidgets import QPlainTextEdit, QCompleter
from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.QtGui import QTextCursor

class SQLEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Schema map: lowercase table name -> list of formatted column strings
        self._schema_map = {}
        # Tracks whether the current completer session is dot-triggered
        self._dot_mode = False

        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated.connect(self.insertCompletion)
        self.model = QStringListModel()
        self.completer.setModel(self.model)

    def set_completions(self, words):
        """Set the global word list used for normal prefix-based autocomplete."""
        self._global_words = words
        self.model.setStringList(words)

    def set_schema_map(self, schema_map):
        """
        Receive the full schema for dot-trigger autocomplete.
        schema_map: dict of {table_name: [col_name, ...]}
        Column names with special characters are pre-wrapped in double quotes.
        """
        self._schema_map = {k.lower(): v for k, v in schema_map.items()}

    def _word_left_of_dot(self):
        """
        Return the word immediately to the left of the cursor, stopping at
        whitespace, parentheses, commas, or the start of the document.
        The dot itself has already been inserted when this is called.
        """
        tc = self.textCursor()
        pos = tc.position()
        doc_text = self.toPlainText()
        # Walk left past the dot
        idx = pos - 1  # position of the dot character
        if idx < 0 or doc_text[idx] != '.':
            return ""
        idx -= 1
        start = idx
        while start >= 0 and not re.match(r'[\s,();]', doc_text[start]):
            start -= 1
        return doc_text[start + 1:idx + 1]

    def _build_alias_map(self):
        """
        Parse the current editor text and return a dict mapping each alias
        (lowercase) to the real table name (lowercase) it represents.

        Handles patterns like:
            FROM   table_name  alias
            FROM   table_name  AS alias
            JOIN   table_name  alias
            JOIN   table_name  AS alias
        Table names may be optionally double-quoted.
        """
        text = self.toPlainText()
        alias_map = {}
        # Match: (FROM|any JOIN) "table" [AS] alias
        pattern = re.compile(
            r'(?:FROM|JOIN)\s+"?([\w]+)"?\s+(?:AS\s+)?(\w+)',
            re.IGNORECASE
        )
        for match in pattern.finditer(text):
            table_name = match.group(1).lower()
            alias = match.group(2).lower()
            # Exclude SQL keywords that can follow a table name (WHERE, ON, SET...)
            if alias not in {'where', 'on', 'set', 'group', 'order', 'having',
                             'limit', 'offset', 'inner', 'left', 'right',
                             'full', 'cross', 'join', 'union', 'as'}:
                alias_map[alias] = table_name
        return alias_map

    def insertCompletion(self, completion):
        if self.completer.widget() != self:
            return

        tc = self.textCursor()
        prefix = self.completer.completionPrefix()

        if self._dot_mode:
            # In dot mode the prefix is empty; just insert the column name at cursor
            tc.insertText(completion)
            self.setTextCursor(tc)
            self._dot_mode = False
            # Restore global word list
            self.model.setStringList(getattr(self, '_global_words', []))
            return

        # Normal mode: replace the typed prefix
        tc.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(prefix))

        # If the character immediately before the prefix is a quote and the
        # completion also starts with a quote, extend the selection to cover it
        tc_check = self.textCursor()
        tc_check.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(prefix))
        tc_check.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1)
        prev_char = tc_check.selectedText()

        if prev_char == '"' and completion.startswith('"'):
            tc.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 1)

        tc.insertText(completion)
        self.setTextCursor(tc)

    def textUnderCursor(self):
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    def keyPressEvent(self, e):
        if self.completer and self.completer.popup().isVisible():
            if e.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                e.ignore()
                return

        super().keyPressEvent(e)

        ctrlOrShift = e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        if not self.completer or (ctrlOrShift and not e.text()):
            return

        # Dot-triggered column autocomplete
        if e.text() == '.':
            table_word = self._word_left_of_dot().lower()
            # Resolve alias -> real table name, then fall back to direct lookup
            alias_map = self._build_alias_map()
            resolved_table = alias_map.get(table_word, table_word)
            columns = self._schema_map.get(resolved_table, [])
            if columns:
                self._dot_mode = True
                self.model.setStringList(columns)
                self.completer.setCompletionPrefix("")
                self.completer.popup().setCurrentIndex(
                    self.completer.completionModel().index(0, 0)
                )
                cr = self.cursorRect()
                cr.setWidth(
                    self.completer.popup().sizeHintForColumn(0)
                    + self.completer.popup().verticalScrollBar().sizeHint().width()
                )
                self.completer.complete(cr)
                return

        # Normal prefix-based autocomplete
        self._dot_mode = False
        hasModifier = (e.modifiers() != Qt.KeyboardModifier.NoModifier) and not ctrlOrShift
        completionPrefix = self.textUnderCursor()

        if hasModifier or not e.text() or len(completionPrefix) < 1:
            self.completer.popup().hide()
            return

        if completionPrefix != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(completionPrefix)
            self.completer.popup().setCurrentIndex(
                self.completer.completionModel().index(0, 0)
            )

        cr = self.cursorRect()
        cr.setWidth(
            self.completer.popup().sizeHintForColumn(0)
            + self.completer.popup().verticalScrollBar().sizeHint().width()
        )
        self.completer.complete(cr)
