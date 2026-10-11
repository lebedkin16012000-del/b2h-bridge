try:
    from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QLabel,
        QProgressBar, QPushButton, QSizePolicy, QTableWidget,
        QTableWidgetItem, QVBoxLayout, QWidget,
    )
except ImportError:
    from PySide2.QtCore import QObject, QThread, Qt, Signal, Slot
    from PySide2.QtWidgets import (
        QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QLabel,
        QProgressBar, QPushButton, QSizePolicy, QTableWidget,
        QTableWidgetItem, QVBoxLayout, QWidget,
    )

import importlib
import os
import traceback

import b2h_manifest
import b2h_materials
import b2h_importer
import b2h_library
import b2h_settings as settings


ADDON_VERSION = "0.5.0"
DEVELOPMENT_STAGE = 10
STAGE_NAME = "Unified Production Importer"
DISPLAY_NAME = "B2H Model Import v%s" % ADDON_VERSION
BUILD_LABEL = "Stage %d — %s" % (DEVELOPMENT_STAGE, STAGE_NAME)

# Reload in dependency order when Houdini's panel reload button is used.
for module in (settings, b2h_manifest, b2h_materials, b2h_importer, b2h_library):
    importlib.reload(module)

try:
    Expanding = QSizePolicy.Policy.Expanding
    Fixed = QSizePolicy.Policy.Fixed
    USER_ROLE = Qt.ItemDataRole.UserRole
    SELECT_ROWS = QAbstractItemView.SelectionBehavior.SelectRows
    NO_EDIT = QAbstractItemView.EditTrigger.NoEditTriggers
except AttributeError:
    Expanding = QSizePolicy.Expanding
    Fixed = QSizePolicy.Fixed
    USER_ROLE = Qt.UserRole
    SELECT_ROWS = QAbstractItemView.SelectRows
    NO_EDIT = QAbstractItemView.NoEditTriggers


class AssetScanWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, root, max_depth, limit):
        super().__init__()
        self.root = root
        self.max_depth = max_depth
        self.limit = limit

    @Slot()
    def run(self):
        try:
            self.completed.emit(b2h_library.scan_b2h_assets(self.root, self.max_depth, self.limit))
        except Exception as error:
            self.failed.emit(str(error))


class B2HAssetLibraryPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(Expanding, Expanding)
        self.b2h_assets = []
        self._scan_thread = None
        self._scan_worker = None
        self.b2h_library_root = self._initial_b2h_root()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        self.setLayout(main_layout)
        self._build_header(main_layout)
        self._build_actions(main_layout)
        self._build_table(main_layout)
        self.clear_b2h_table("Select a B2H export folder, then press Refresh.")

    def _initial_b2h_root(self):
        roots = settings.load_settings().get("b2h_library_roots", []) or []
        return next((root for root in roots if os.path.isdir(root)), "")

    def _build_header(self, layout):
        title = QLabel(DISPLAY_NAME)
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding-top: 2px;")
        layout.addWidget(title)
        build = QLabel(BUILD_LABEL)
        build.setStyleSheet("color: #9aa0a6; padding-bottom: 4px;")
        layout.addWidget(build)
        self.root_label = QLabel("Root: %s" % (self.b2h_library_root or "not selected"))
        self.root_label.setWordWrap(True)
        self.root_label.setSizePolicy(Expanding, Fixed)
        layout.addWidget(self.root_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(Expanding, Fixed)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        layout.addWidget(self.progress)

    def _build_actions(self, layout):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.button_select_root = QPushButton("Select Export Folder")
        self.button_select_root.clicked.connect(self.select_b2h_root)
        self.button_refresh = QPushButton("Refresh")
        self.button_refresh.clicked.connect(self.populate_b2h_table)
        self.button_import = QPushButton("Import / Update Selected")
        self.button_import.clicked.connect(self.import_selected_b2h_asset)
        for widget in (self.button_select_root, self.button_refresh, self.button_import):
            widget.setSizePolicy(Fixed, Fixed)
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)

    def _build_table(self, layout):
        self.b2h_table = QTableWidget()
        self.b2h_table.setColumnCount(6)
        self.b2h_table.setHorizontalHeaderLabels(["Asset", "Revision", "Materials", "Assignments", "Status", "Path"])
        self.b2h_table.horizontalHeader().setStretchLastSection(True)
        self.b2h_table.setSelectionBehavior(SELECT_ROWS)
        self.b2h_table.setEditTriggers(NO_EDIT)
        self.b2h_table.setMinimumHeight(260)
        self.b2h_table.doubleClicked.connect(self.import_selected_b2h_asset)
        layout.addWidget(self.b2h_table, 1)

    def _set_busy(self, busy, text=None):
        for widget in (self.button_select_root, self.button_refresh, self.button_import):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy and text:
            self.status_label.setText(text)
        if not busy:
            self.progress.setValue(0)

    def select_b2h_root(self):
        start = self.b2h_library_root or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Select B2H Export Folder", start)
        if not folder:
            return
        self.b2h_library_root = folder
        self.root_label.setText("Root: %s" % folder)
        settings.remember_root(folder)
        self.clear_b2h_table("Folder selected. Press Refresh to scan B2H exports.")

    def clear_b2h_table(self, message=""):
        self.b2h_assets = []
        self.b2h_table.setRowCount(0)
        if message:
            self.status_label.setText(message)

    def populate_b2h_table(self):
        if self._scan_thread is not None:
            return
        if not self.b2h_library_root or not os.path.isdir(self.b2h_library_root):
            self.clear_b2h_table("Select a B2H export folder first.")
            return
        config = settings.load_settings()
        self._set_busy(True, "Scanning: %s" % self.b2h_library_root)
        self.progress.setRange(0, 0)
        self._scan_thread = QThread(self)
        self._scan_worker = AssetScanWorker(
            self.b2h_library_root,
            int(config.get("scan_depth", 6)),
            int(config.get("scan_limit", 2000)),
        )
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.completed.connect(self._scan_complete)
        self._scan_worker.failed.connect(self._scan_failed)
        self._scan_worker.completed.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_finished)
        self._scan_thread.start()

    @Slot(object)
    def _scan_complete(self, assets):
        self.b2h_assets = list(assets or [])
        self.b2h_table.setRowCount(len(self.b2h_assets))
        for row, asset in enumerate(self.b2h_assets):
            values = [
                asset.get("asset_name", "Asset"), str(asset.get("revision", "")),
                str(asset.get("material_count", 0)), str(asset.get("assignment_count", 0)),
                asset.get("status", ""), asset.get("base_dir", ""),
            ]
            details = []
            report = asset.get("report") or {}
            details.extend(report.get("errors") or [])
            details.extend(report.get("warnings") or [])
            tooltip = "\n".join(details)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(USER_ROLE, row)
                if tooltip:
                    item.setToolTip(tooltip)
                self.b2h_table.setItem(row, column, item)
        valid = sum(1 for asset in self.b2h_assets if asset.get("meta") is not None)
        self.status_label.setText("Assets found: %d; ready: %d; invalid/skipped: %d" % (len(self.b2h_assets), valid, len(self.b2h_assets) - valid))

    @Slot(str)
    def _scan_failed(self, message):
        self.clear_b2h_table("Scan failed: %s" % message)

    @Slot()
    def _scan_finished(self):
        if self._scan_worker:
            self._scan_worker.deleteLater()
        if self._scan_thread:
            self._scan_thread.deleteLater()
        self._scan_worker = None
        self._scan_thread = None
        self.progress.setRange(0, 100)
        self._set_busy(False)

    def selected_b2h_asset(self):
        selected = self.b2h_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        return self.b2h_assets[row] if 0 <= row < len(self.b2h_assets) else None

    def _import_progress(self, fraction, message):
        self.progress.setValue(int(round(fraction * 100)))
        self.status_label.setText(message)
        QApplication.processEvents()

    def import_selected_b2h_asset(self, *_args):
        asset = self.selected_b2h_asset()
        if not asset:
            self.status_label.setText("Select an asset first.")
            return
        if asset.get("meta") is None:
            self.status_label.setText("Cannot import: %s" % asset.get("status", "invalid manifest"))
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_busy(True, "Starting import...")
        try:
            result = b2h_library.import_b2h_asset(asset["meta"], progress=self._import_progress)
            diagnostics = result["diagnostics"]
            message = "%s: %s — materials %d/%d, assignments %d/%d" % (
                asset.get("asset_name", "Asset"), diagnostics["status"],
                diagnostics["created_materials"], diagnostics["expected_materials"],
                diagnostics["created_assignments"], diagnostics["expected_assignments"],
            )
            if diagnostics["replaced_nodes"]:
                message += "; updated previous import"
            self.status_label.setText(message)
        except Exception as error:
            self.status_label.setText("Import failed; previous import preserved: %s" % error)
            print("[B2H] Import failed: %s" % error)
            traceback.print_exc()
        finally:
            self._set_busy(False)

    def closeEvent(self, event):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.requestInterruption()
            self._scan_thread.quit()
            self._scan_thread.wait(1000)
        super().closeEvent(event)


def createInterface():
    return B2HAssetLibraryPanel()
