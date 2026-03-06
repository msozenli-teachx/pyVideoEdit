"""Media pool widget for managing imported media files.

Displays imported media in a list/tree view with thumbnails and metadata.
Supports drag and drop to timeline.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QMenu,
    QFileDialog, QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QMimeData
from PyQt6.QtGui import QAction, QDrag
from typing import Optional, Callable
import json

from video_editor.services.editor_service import MediaInfo
from video_editor.gui.styles import get_dark_theme


class MediaPoolTreeWidget(QTreeWidget):
    """Custom tree widget that supports dragging media items."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._media_items: dict[str, MediaInfo] = {}
    
    def set_media_items(self, media_items: dict[str, MediaInfo]):
        """Update the reference to media items dictionary."""
        self._media_items = media_items
    
    def startDrag(self, supportedActions):
        """Start drag operation with media data."""
        item = self.currentItem()
        if not item:
            return
        
        media_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not media_id or media_id not in self._media_items:
            return
        
        media_info = self._media_items[media_id]
        
        # Create mime data with media info
        mime_data = QMimeData()
        drag_data = {
            'media_id': media_info.media_id,
            'name': media_info.name,
            'file_path': media_info.file_path,
            'duration': media_info.duration
        }
        mime_data.setText(json.dumps(drag_data))
        mime_data.setData('application/x-media-item', json.dumps(drag_data).encode())
        
        # Create drag object
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        
        # Execute drag
        drag.exec(supportedActions)


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
    add_to_timeline_requested = pyqtSignal(str) # media_id
    remove_requested = pyqtSignal(str)    # media_id
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._media_items: dict[str, MediaInfo] = {}
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

        # Add to Timeline button
        self.add_to_timeline_btn = QPushButton("+ Timeline")
        self.add_to_timeline_btn.setToolTip("Add selected media to timeline")
        self.add_to_timeline_btn.setEnabled(False)  # Disabled until media is selected
        self.add_to_timeline_btn.clicked.connect(self._on_add_to_timeline_clicked)
        header_layout.addWidget(self.add_to_timeline_btn)
        
        layout.addLayout(header_layout)
        
        # Media tree - using custom tree widget
        self.media_tree = MediaPoolTreeWidget()
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
        
        # Enable drag and drop
        self.media_tree.setDragEnabled(True)
        self.media_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        
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
    
    def _on_add_to_timeline_clicked(self):
        """Handle add to timeline button click."""
        if self._current_media_id:
            self.add_to_timeline_requested.emit(self._current_media_id)
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item selection."""
        media_id = item.data(0, Qt.ItemDataRole.UserRole)
        if media_id:
            self._current_media_id = media_id
            self.add_to_timeline_btn.setEnabled(True)
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
        self._media_items[media_info.media_id] = media_info
        
        # Update the tree widget's reference
        self.media_tree.set_media_items(self._media_items)
        
        self._update_stats()
    
    def remove_media(self, media_id: str):
        """Remove a media item from the pool display.
        
        Args:
            media_id: ID of the media to remove
        """
        # Find and remove the tree item
        for i in range(self.media_tree.topLevelItemCount()):
            item = self.media_tree.topLevelItem(i)
            if item and item.data(0, Qt.ItemDataRole.UserRole) == media_id:
                self.media_tree.takeTopLevelItem(i)
                break
        
        # Remove from our dictionary
        self._media_items.pop(media_id, None)
        
        # Update the tree widget's reference
        self.media_tree.set_media_items(self._media_items)
        
        if self._current_media_id == media_id:
            self._current_media_id = None
            self.add_to_timeline_btn.setEnabled(False)
        
        self._update_stats()
    
    def clear(self):
        """Clear all media items."""
        self.media_tree.clear()
        self._media_items.clear()
        self._current_media_id = None
        self.add_to_timeline_btn.setEnabled(False)
        self.media_tree.set_media_items(self._media_items)
        self._update_stats()
    
    def select_media(self, media_id: str):
        """Select a specific media item.
        
        Args:
            media_id: ID of the media to select
        """
        for i in range(self.media_tree.topLevelItemCount()):
            item = self.media_tree.topLevelItem(i)
            if item and item.data(0, Qt.ItemDataRole.UserRole) == media_id:
                self.media_tree.setCurrentItem(item)
                self._current_media_id = media_id
                self.add_to_timeline_btn.setEnabled(True)
                break
    
    def get_selected_media_id(self) -> Optional[str]:
        """Get the currently selected media ID."""
        return self._current_media_id
    
    def get_media_info(self, media_id: str) -> Optional[MediaInfo]:
        """Get media info for a specific media ID."""
        return self._media_items.get(media_id)
    
    def _update_stats(self):
        """Update the stats label."""
        count = len(self._media_items)
        self.stats_label.setText(f"{count} item{'s' if count != 1 else ''}")
