"""Media pool widget for managing imported media files.

Displays imported media in a list/tree view with thumbnails and metadata.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QMenu,
    QFileDialog, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QAction
from typing import Optional, Callable

from video_editor.services.editor_service import MediaInfo
from video_editor.gui.styles import get_dark_theme


class MediaPoolWidget(QWidget):
    """Widget for displaying and managing the media pool.
    
    Signals:
        media_selected: Emitted when a media item is selected
        media_double_clicked: Emitted when a media item is double-clicked
        import_requested: Emitted when import button is clicked
        remove_requested: Emitted when remove action is triggered
    """
    
    media_selected = pyqtSignal(str)      # media_id
    media_double_clicked = pyqtSignal(str)  # media_id
    import_requested = pyqtSignal()
    remove_requested = pyqtSignal(str)    # media_id
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._media_items: dict[str, QTreeWidgetItem] = {}
        self._current_media_id: Optional[str] = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Media Pool")
        title_label.setObjectName("sectionHeader")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Import button
        self.import_btn = QPushButton("+ Import")
        self.import_btn.setToolTip("Import media files")
        self.import_btn.clicked.connect(self._on_import_clicked)
        header_layout.addWidget(self.import_btn)
        
        layout.addLayout(header_layout)
        
        # Media tree
        self.media_tree = QTreeWidget()
        self.media_tree.setObjectName("mediaPoolWidget")
        self.media_tree.setHeaderLabels(["Name", "Duration", "Resolution", "Size"])
        self.media_tree.setColumnWidth(0, 150)
        self.media_tree.setColumnWidth(1, 80)
        self.media_tree.setColumnWidth(2, 80)
        self.media_tree.setColumnWidth(3, 60)
        self.media_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.media_tree.setAlternatingRowColors(True)
        self.media_tree.setRootIsDecorated(False)
        self.media_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Header styling
        header = self.media_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        
        # Connections
        self.media_tree.itemClicked.connect(self._on_item_clicked)
        self.media_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.media_tree.customContextMenuRequested.connect(self._on_context_menu)
        
        layout.addWidget(self.media_tree)
        
        # Stats label
        self.stats_label = QLabel("0 items")
        self.stats_label.setObjectName("timeLabel")
        layout.addWidget(self.stats_label)
        
        self.setObjectName("mediaPoolWidget")
    
    def _on_import_clicked(self):
        """Handle import button click."""
        self.import_requested.emit()
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item selection."""
        media_id = item.data(0, Qt.ItemDataRole.UserRole)
        if media_id:
            self._current_media_id = media_id
            self.media_selected.emit(media_id)
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item double click."""
        media_id = item.data(0, Qt.ItemDataRole.UserRole)
        if media_id:
            self.media_double_clicked.emit(media_id)
    
    def _on_context_menu(self, position):
        """Show context menu for media items."""
        item = self.media_tree.itemAt(position)
        if not item:
            return
        
        media_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not media_id:
            return
        
        menu = QMenu(self)
        
        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(lambda: self.remove_requested.emit(media_id))
        menu.addAction(remove_action)
        
        menu.exec(self.media_tree.viewport().mapToGlobal(position))
    
    def add_media(self, media_info: MediaInfo):
        """Add a media item to the pool display.
        
        Args:
            media_info: Media information to display
        """
        item = QTreeWidgetItem([
            media_info.name,
            media_info.duration_formatted,
            media_info.resolution,
            media_info.file_size_formatted
        ])
        
        # Store media_id in the item
        item.setData(0, Qt.ItemDataRole.UserRole, media_info.media_id)
        item.setToolTip(0, f"{media_info.name}\n{media_info.file_path}")
        
        self.media_tree.addTopLevelItem(item)
        self._media_items[media_info.media_id] = item
        
        self._update_stats()
    
    def remove_media(self, media_id: str):
        """Remove a media item from the pool display.
        
        Args:
            media_id: ID of the media to remove
        """
        item = self._media_items.pop(media_id, None)
        if item:
            index = self.media_tree.indexOfTopLevelItem(item)
            self.media_tree.takeTopLevelItem(index)
        
        if self._current_media_id == media_id:
            self._current_media_id = None
        
        self._update_stats()
    
    def clear(self):
        """Clear all media items."""
        self.media_tree.clear()
        self._media_items.clear()
        self._current_media_id = None
        self._update_stats()
    
    def select_media(self, media_id: str):
        """Select a specific media item.
        
        Args:
            media_id: ID of the media to select
        """
        item = self._media_items.get(media_id)
        if item:
            self.media_tree.setCurrentItem(item)
            self._current_media_id = media_id
    
    def get_selected_media_id(self) -> Optional[str]:
        """Get the currently selected media ID."""
        return self._current_media_id
    
    def _update_stats(self):
        """Update the stats label."""
        count = len(self._media_items)
        self.stats_label.setText(f"{count} item{'s' if count != 1 else ''}")
