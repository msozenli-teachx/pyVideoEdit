"""Timeline widget for multi-track video editing.

Displays clips on a timeline with support for multiple tracks.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QMenu, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QAction, QMouseEvent, QPaintEvent
from typing import Optional, List, Dict

from video_editor.services.editor_service import TimelineClip


class TimelineTrack(QWidget):
    """Single track in the timeline."""
    
    def __init__(self, track_id: int, name: str, height: int = 60, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.track_id = track_id
        self.track_name = name
        self.track_height = height
        self.clips: List[TimelineClip] = []
        self._pixels_per_second = 50  # Zoom level
        self._selected_clip_id: Optional[str] = None
        
        self.setFixedHeight(height)
        self.setMinimumWidth(1000)
    
    def add_clip(self, clip: TimelineClip):
        """Add a clip to this track."""
        self.clips.append(clip)
        self.update()
    
    def remove_clip(self, clip_id: str) -> bool:
        """Remove a clip from this track."""
        for i, clip in enumerate(self.clips):
            if clip.clip_id == clip_id:
                self.clips.pop(i)
                if self._selected_clip_id == clip_id:
                    self._selected_clip_id = None
                self.update()
                return True
        return False
    
    def clear(self):
        """Clear all clips."""
        self.clips.clear()
        self._selected_clip_id = None
        self.update()
    
    def set_zoom(self, pixels_per_second: float):
        """Set the zoom level."""
        self._pixels_per_second = pixels_per_second
        self.update()
    
    def paintEvent(self, event: QPaintEvent):
        """Paint the track and clips."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), QColor("#252525"))
        
        # Draw grid lines (every second)
        pen = QPen(QColor("#404040"))
        pen.setWidth(1)
        painter.setPen(pen)
        
        for i in range(0, int(self.width() / self._pixels_per_second) + 1):
            x = int(i * self._pixels_per_second)
            painter.drawLine(x, 0, x, self.height())
        
        # Draw clips
        for clip in self.clips:
            self._draw_clip(painter, clip)
        
        painter.end()
    
    def _draw_clip(self, painter: QPainter, clip: TimelineClip):
        """Draw a single clip."""
        x = int(clip.timeline_start * self._pixels_per_second)
        width = int(clip.duration * self._pixels_per_second)
        
        # Minimum width for visibility
        if width < 5:
            width = 5
        
        # Clip rectangle
        margin = 3
        rect = QRect(x, margin, width, self.height() - 2 * margin)
        
        # Determine color
        is_selected = clip.clip_id == self._selected_clip_id
        base_color = QColor(clip.color)
        
        if is_selected:
            base_color = base_color.lighter(120)
        
        # Draw clip background
        brush = QBrush(base_color)
        painter.setBrush(brush)
        
        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2 if is_selected else 1)
        painter.setPen(pen)
        
        painter.drawRoundedRect(rect, 4, 4)
        
        # Draw clip name
        painter.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        
        text_rect = rect.adjusted(5, 5, -5, -5)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, clip.name)
        
        # Draw duration
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        duration_text = f"{clip.duration:.1f}s"
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, duration_text)


class TimelineWidget(QWidget):
    """Multi-track timeline widget.
    
    Signals:
        clip_selected: Emitted when a clip is selected
        clip_double_clicked: Emitted when a clip is double-clicked
        position_changed: Emitted when playhead position changes
    """
    
    clip_selected = pyqtSignal(str)      # clip_id
    clip_double_clicked = pyqtSignal(str)  # clip_id
    position_changed = pyqtSignal(float)  # position in seconds
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._tracks: List[TimelineTrack] = []
        self._pixels_per_second = 50
        self._playhead_position = 0.0
        self._duration = 60.0  # Default 1 minute
        
        self._setup_ui()
        self._add_default_tracks()
    
    def _setup_ui(self):
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header with time ruler
        header_widget = QWidget()
        header_widget.setFixedHeight(30)
        header_widget.setStyleSheet("background-color: #2d2d2d;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 0, 10, 0)
        
        self.ruler_label = QLabel("Timeline")
        self.ruler_label.setObjectName("sectionHeader")
        header_layout.addWidget(self.ruler_label)
        
        header_layout.addStretch()
        
        # Zoom controls
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedSize(25, 25)
        zoom_out_btn.setToolTip("Zoom out")
        zoom_out_btn.clicked.connect(self._zoom_out)
        header_layout.addWidget(zoom_out_btn)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("timeLabel")
        header_layout.addWidget(self.zoom_label)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(25, 25)
        zoom_in_btn.setToolTip("Zoom in")
        zoom_in_btn.clicked.connect(self._zoom_in)
        header_layout.addWidget(zoom_in_btn)
        
        layout.addWidget(header_widget)
        
        # Tracks container
        self.tracks_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.tracks_container)
        self.tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_layout.setSpacing(2)
        
        # Scroll area for tracks
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.tracks_container)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        layout.addWidget(scroll)
        
        # Time display
        time_widget = QWidget()
        time_widget.setFixedHeight(35)
        time_widget.setStyleSheet("background-color: #2d2d2d; border-top: 1px solid #404040;")
        time_layout = QHBoxLayout(time_widget)
        time_layout.setContentsMargins(10, 5, 10, 5)
        
        self.time_label = QLabel("00:00:00.000")
        self.time_label.setObjectName("timeLabel")
        self.time_label.setStyleSheet("font-family: Consolas, Monaco, monospace; font-size: 14px; color: #00bcd4;")
        time_layout.addWidget(self.time_label)
        
        time_layout.addStretch()
        
        # Add track button
        add_track_btn = QPushButton("+ Add Track")
        add_track_btn.clicked.connect(self._add_track)
        time_layout.addWidget(add_track_btn)
        
        layout.addWidget(time_widget)
        
        self.setObjectName("timelineWidget")
    
    def _add_default_tracks(self):
        """Add default video and audio tracks."""
        self.add_track("Video 1", 80)
        self.add_track("Audio 1", 60)
    
    def add_track(self, name: str, height: int = 60) -> int:
        """Add a new track to the timeline.
        
        Returns:
            Track ID
        """
        track_id = len(self._tracks)
        track = TimelineTrack(track_id, name, height)
        
        # Track header
        track_header = QWidget()
        track_header.setFixedWidth(120)
        track_header.setStyleSheet("background-color: #2d2d2d; border-right: 1px solid #404040;")
        header_layout = QVBoxLayout(track_header)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        track_name_label = QLabel(name)
        track_name_label.setObjectName("timeLabel")
        header_layout.addWidget(track_name_label)
        
        # Track row container
        track_row = QWidget()
        row_layout = QHBoxLayout(track_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addWidget(track_header)
        row_layout.addWidget(track, stretch=1)
        
        self.tracks_layout.addWidget(track_row)
        self._tracks.append(track)
        
        return track_id
    
    def _add_track(self):
        """Add a new track via button."""
        track_num = len(self._tracks) + 1
        self.add_track(f"Track {track_num}")
    
    def add_clip_to_track(self, track_id: int, clip: TimelineClip):
        """Add a clip to a specific track."""
        if 0 <= track_id < len(self._tracks):
            self._tracks[track_id].add_clip(clip)
            self._update_duration()
    
    def remove_clip(self, clip_id: str):
        """Remove a clip from any track."""
        for track in self._tracks:
            if track.remove_clip(clip_id):
                break
    
    def clear(self):
        """Clear all tracks."""
        for track in self._tracks:
            track.clear()
    
    def set_playhead_position(self, position: float):
        """Set the playhead position."""
        self._playhead_position = position
        self._update_time_label()
        self.update()
    
    def _update_time_label(self):
        """Update the time display."""
        hours = int(self._playhead_position // 3600)
        minutes = int((self._playhead_position % 3600) // 60)
        seconds = int(self._playhead_position % 60)
        millis = int((self._playhead_position % 1) * 1000)
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}")
    
    def _zoom_in(self):
        """Zoom in on the timeline."""
        self._pixels_per_second = min(self._pixels_per_second * 1.2, 500)
        self._apply_zoom()
    
    def _zoom_out(self):
        """Zoom out on the timeline."""
        self._pixels_per_second = max(self._pixels_per_second / 1.2, 10)
        self._apply_zoom()
    
    def _apply_zoom(self):
        """Apply zoom to all tracks."""
        for track in self._tracks:
            track.set_zoom(self._pixels_per_second)
        
        # Update zoom label
        zoom_percent = int((self._pixels_per_second / 50) * 100)
        self.zoom_label.setText(f"{zoom_percent}%")
    
    def _update_duration(self):
        """Update timeline duration based on clips."""
        max_end = 0
        for track in self._tracks:
            for clip in track.clips:
                end = clip.timeline_start + clip.duration
                if end > max_end:
                    max_end = end
        
        if max_end > self._duration:
            self._duration = max_end + 10  # Add padding
