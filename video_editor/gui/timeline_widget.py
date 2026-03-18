"""Timeline widget for multi-track video editing.

Displays clips on a timeline with support for multiple tracks.
Supports drag and drop from media pool.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QMenu, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPointF, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QAction, QMouseEvent, QPaintEvent, QDragEnterEvent, QDropEvent, QPolygonF, QIcon, QPixmap
from typing import Optional, List
import json

from video_editor.services.editor_service import TimelineClip


def _create_split_icon() -> QIcon:
    """Create a simple split/scissors icon without external assets."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#ffffff"))
    pen.setWidth(1)
    painter.setPen(pen)

    # Handles (centered)
    painter.drawEllipse(1, 1, 3, 3)
    painter.drawEllipse(1, 8, 3, 3)

    # Blades (centered)
    painter.drawLine(4, 3, 11, 1)
    painter.drawLine(4, 8, 11, 11)

    painter.end()
    return QIcon(pixmap)


def _create_speaker_icon() -> QIcon:
    """Create a speaker/audio icon."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#ffffff"))
    pen.setWidth(1)
    painter.setPen(pen)

    speaker = QPolygonF([
        QPointF(2, 6),
        QPointF(6, 6),
        QPointF(10, 2),
        QPointF(10, 14),
        QPointF(6, 10),
        QPointF(2, 10)
    ])
    painter.drawPolygon(speaker)

    painter.end()
    return QIcon(pixmap)


def _create_muted_icon() -> QIcon:
    """Create a muted speaker icon with X."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#ff5555"))
    pen.setWidth(1)
    painter.setPen(pen)

    speaker = QPolygonF([
        QPointF(1, 6),
        QPointF(5, 6),
        QPointF(9, 2),
        QPointF(9, 14),
        QPointF(5, 10),
        QPointF(1, 10)
    ])
    painter.drawPolygon(speaker)

    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(11, 5, 15, 11)
    painter.drawLine(15, 5, 11, 11)

    painter.end()
    return QIcon(pixmap)


def _create_minus_icon() -> QIcon:
    """Create a compact minus icon that remains visible across styles."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(2, 6, 10, 6)
    painter.end()
    return QIcon(pixmap)


def _create_plus_icon() -> QIcon:
    """Create a compact plus icon that remains visible across styles."""
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(2, 6, 10, 6)
    painter.drawLine(6, 2, 6, 10)
    painter.end()
    return QIcon(pixmap)


class TimelineTrack(QWidget):
    """Single track in the timeline."""
    
    # Signals
    media_dropped = pyqtSignal(str, str, float, float)  # media_id, name, duration, timeline_start
    clip_moved = pyqtSignal(str, float)  # clip_id, new_timeline_start
    clip_trimmed = pyqtSignal(str, float, float)  # clip_id, new_timeline_start, new_timeline_end
    split_requested = pyqtSignal(str)  # clip_id
    playhead_moved = pyqtSignal(float)   # new_position in seconds
    clip_volume_changed = pyqtSignal(str, float)  # clip_id, volume (0.0 to 2.0)
    clip_mute_toggled = pyqtSignal(str)  # clip_id
    clip_fade_changed = pyqtSignal(str, float, float)  # clip_id, fade_in_duration, fade_out_duration
    
    # Fade handle constants
    FADE_HANDLE_SIZE = 20  # Size of fade handle area (pixels)
    FADE_HANDLE_MIN_DISTANCE = 10  # Minimum distance between fade handles (pixels)
    
    def __init__(self, track_id: int, name: str, height: int = 60, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.track_id = track_id
        self.track_name = name
        self.track_height = height
        self.clips: List[TimelineClip] = []
        self._pixels_per_second = 50  # Zoom level
        self._selected_clip_id: Optional[str] = None
        
        # Dragging state
        self._is_dragging_clip = False
        self._is_dragging_playhead = False
        self._drag_start_pos = None
        self._drag_clip_initial_start = 0
        self._drag_clip_initial_duration = 0
        self._drag_clip_source_start = 0.0
        self._drag_clip_source_end = 0.0
        self._drag_clip_id = None
        self._drag_mode = None  # move, trim_left, trim_right, fade_in, fade_out
        
        # Fade handle state
        self._is_dragging_fade = False
        self._fade_drag_initial_in = 0.0
        self._fade_drag_initial_out = 0.0
        
        # Hover state for fade handles
        self._hovered_fade_clip_id: Optional[str] = None
        self._hovered_fade_type: str = 'none'  # 'fade_in', 'fade_out', or 'none'
        
        self.setFixedHeight(height)
        self.setMinimumWidth(1000)
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    def _get_playhead_x(self) -> int:
        """Get the current playhead X position from parent TimelineWidget."""
        parent = self.parent()
        while parent:
            if isinstance(parent, TimelineWidget):
                return int(parent._playhead_position * self._pixels_per_second)
            parent = parent.parent()
        return 0
    
    def _is_on_playhead(self, x: float) -> bool:
        """Check if x coordinate is on the playhead line (with 5px tolerance)."""
        playhead_x = self._get_playhead_x()
        return abs(x - playhead_x) < 8  # 8px tolerance for easier grabbing

    def _get_clip_edge_at_position(self, x: float) -> tuple[Optional[str], str]:
        """Check if position is near a clip edge and return clip_id and edge type.

        Args:
            x: X coordinate in pixels

        Returns:
            Tuple of (clip_id, edge_type) where edge_type is 'left', 'right', or 'none'
        """
        click_time = x / self._pixels_per_second
        edge_tolerance = 6  # pixels

        for clip in self.clips:
            clip_start_time = clip.timeline_start
            clip_end_time = clip.timeline_start + clip.duration

            if clip_start_time <= click_time <= clip_end_time:
                left_edge = clip_start_time * self._pixels_per_second
                right_edge = clip_end_time * self._pixels_per_second

                if abs(x - left_edge) <= edge_tolerance:
                    return (clip.clip_id, 'left')
                elif abs(x - right_edge) <= edge_tolerance:
                    return (clip.clip_id, 'right')
                else:
                    return (clip.clip_id, 'none')

        return (None, 'none')

    def _get_fade_handle_at_position(self, x: float, y: float) -> tuple[Optional[str], str]:
        """Check if position is on a fade handle and return clip_id and handle type.

        Args:
            x: X coordinate in pixels
            y: Y coordinate in pixels

        Returns:
            Tuple of (clip_id, handle_type) where handle_type is 'fade_in', 'fade_out', or 'none'
        """
        click_time = x / self._pixels_per_second
        margin = 3  # Clip margin
        handle_size = self.FADE_HANDLE_SIZE

        for clip in self.clips:
            clip_start_time = clip.timeline_start
            clip_end_time = clip.timeline_start + clip.duration

            if clip_start_time <= click_time <= clip_end_time:
                left_edge = clip_start_time * self._pixels_per_second
                right_edge = clip_end_time * self._pixels_per_second
                clip_width = right_edge - left_edge

                # Clip must be wide enough to have fade handles
                if clip_width < handle_size * 2 + self.FADE_HANDLE_MIN_DISTANCE * 2:
                    continue

                # Check if click is in the top portion of the clip (handle area)
                if y > margin + handle_size:
                    continue

                # Fade in handle (top-left corner)
                fade_in_x = left_edge
                fade_in_width = min(handle_size, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)
                if fade_in_width > 0 and fade_in_x <= x <= fade_in_x + fade_in_width:
                    return (clip.clip_id, 'fade_in')

                # Fade out handle (top-right corner)
                fade_out_width = min(handle_size, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)
                if fade_out_width > 0 and right_edge - fade_out_width <= x <= right_edge:
                    return (clip.clip_id, 'fade_out')

        return (None, 'none')

    def _get_fade_constraints(self, clip_id: str, fade_type: str) -> tuple[float, float]:
        """Get min/max constraints for fade handles to avoid overlapping.

        Args:
            clip_id: ID of the clip
            fade_type: 'fade_in' or 'fade_out'

        Returns:
            Tuple of (min_duration, max_duration) in seconds
        """
        clip = next(c for c in self.clips if c.clip_id == clip_id)
        min_duration = 0.0
        max_duration = clip.duration

        if fade_type == 'fade_in':
            # Fade in cannot exceed duration - fade_out_duration
            max_duration = max(0.0, clip.duration - clip.fade_out_duration)
        else:
            # Fade out cannot exceed duration - fade_in_duration
            max_duration = max(0.0, clip.duration - clip.fade_in_duration)

        return (min_duration, max_duration)

    def mousePressEvent(self, event: QMouseEvent):
        click_x = event.position().x()
        click_y = event.position().y()
        click_time = click_x / self._pixels_per_second

        if event.button() == Qt.MouseButton.RightButton:
            # Right-click: show context menu for clip actions
            for clip in self.clips:
                if clip.timeline_start <= click_time <= clip.timeline_start + clip.duration:
                    self._selected_clip_id = clip.clip_id
                    self._notify_clip_selected(clip.clip_id)
                    self.update()
                    menu = QMenu(self)
                    split_action = QAction("Split at Playhead", self)
                    split_action.triggered.connect(lambda _, cid=clip.clip_id: self.split_requested.emit(cid))
                    menu.addAction(split_action)
                    menu.exec(self.mapToGlobal(event.position().toPoint()))
                    return
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Check if we clicked on the playhead first (higher priority)
            if self._is_on_playhead(click_x):
                self._is_dragging_playhead = True
                self.playhead_moved.emit(max(0, click_time))
                return

            # Check if we clicked on a fade handle first (for all clips)
            fade_clip_id, fade_handle_type = self._get_fade_handle_at_position(click_x, click_y)
            if fade_clip_id and fade_handle_type in ('fade_in', 'fade_out'):
                clip = next(c for c in self.clips if c.clip_id == fade_clip_id)
                self._is_dragging_fade = True
                self._drag_clip_id = fade_clip_id
                self._drag_start_pos = event.position()
                self._drag_mode = fade_handle_type
                self._fade_drag_initial_in = clip.fade_in_duration
                self._fade_drag_initial_out = clip.fade_out_duration
                self._selected_clip_id = fade_clip_id
                self._notify_clip_selected(fade_clip_id)
                self.update()
                return

            # Check if we clicked on a clip
            for clip in self.clips:
                if clip.timeline_start <= click_time <= clip.timeline_start + clip.duration:
                    self._is_dragging_clip = True
                    self._drag_clip_id = clip.clip_id
                    self._drag_start_pos = event.position()
                    self._drag_clip_initial_start = clip.timeline_start
                    self._drag_clip_initial_duration = clip.duration
                    self._drag_clip_source_start = clip.start_time
                    self._drag_clip_source_end = clip.end_time
                    self._selected_clip_id = clip.clip_id
                    self._notify_clip_selected(clip.clip_id)

                    # Determine if trimming left/right edge (skip fade handle areas)
                    left_edge = clip.timeline_start * self._pixels_per_second
                    right_edge = (clip.timeline_start + clip.duration) * self._pixels_per_second
                    edge_tolerance = 6
                    handle_size = self.FADE_HANDLE_SIZE
                    clip_width = right_edge - left_edge

                    # Calculate fade handle regions
                    fade_in_width = min(handle_size, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)
                    fade_out_width = min(handle_size, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)

                    # Check if we're in fade handle area (top portion only)
                    in_fade_area = click_y <= 3 + handle_size

                    if abs(click_x - left_edge) <= edge_tolerance and not in_fade_area:
                        self._drag_mode = "trim_left"
                    elif abs(click_x - right_edge) <= edge_tolerance and not in_fade_area:
                        self._drag_mode = "trim_right"
                    elif in_fade_area and click_x - left_edge <= fade_in_width:
                        # Fade in handle
                        self._is_dragging_clip = False
                        self._is_dragging_fade = True
                        self._drag_mode = "fade_in"
                        self._fade_drag_initial_in = clip.fade_in_duration
                        self._fade_drag_initial_out = clip.fade_out_duration
                    elif in_fade_area and right_edge - click_x <= fade_out_width:
                        # Fade out handle
                        self._is_dragging_clip = False
                        self._is_dragging_fade = True
                        self._drag_mode = "fade_out"
                        self._fade_drag_initial_in = clip.fade_in_duration
                        self._fade_drag_initial_out = clip.fade_out_duration
                    else:
                        self._drag_mode = "move"

                    self.update()
                    return

            # If not on clip or playhead, move playhead to clicked position
            self._is_dragging_playhead = True
            self.playhead_moved.emit(max(0, click_time))

    def _get_trim_constraints(self, clip_id: str, drag_mode: str) -> tuple[float, float]:
        """Get min/max constraints for trimming a clip to avoid overlapping.

        Args:
            clip_id: ID of the clip being trimmed
            drag_mode: 'trim_left' or 'trim_right'

        Returns:
            Tuple of (min_bound, max_bound) in timeline time
        """
        target_clip = next(c for c in self.clips if c.clip_id == clip_id)
        min_duration = 0.1

        if drag_mode == "trim_left":
            # Left trim: find the clip to the left
            min_bound = 0.0
            max_bound = target_clip.timeline_start + target_clip.duration - min_duration

            for clip in self.clips:
                if clip.clip_id == clip_id:
                    continue
                clip_end = clip.timeline_start + clip.duration
                # If this clip ends where our target clip starts (or before)
                if clip_end <= target_clip.timeline_start + 0.001:
                    min_bound = max(min_bound, clip_end)

            return (min_bound, max_bound)

        # trim_right
        min_bound = target_clip.timeline_start + min_duration
        max_bound = float('inf')

        for clip in self.clips:
            if clip.clip_id == clip_id:
                continue
            # If this clip starts where our target clip ends (or after)
            if clip.timeline_start >= target_clip.timeline_start + target_clip.duration - 0.001:
                max_bound = min(max_bound, clip.timeline_start)

        return (min_bound, max_bound)

    def _notify_clip_selected(self, clip_id: str):
        """Notify parent TimelineWidget when a clip becomes selected."""
        parent = self.parent()
        while parent:
            if isinstance(parent, TimelineWidget):
                parent.clip_selected.emit(clip_id)
                return
            parent = parent.parent()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging_fade and self._drag_clip_id:
            # Handle fade handle dragging
            target_clip = next(c for c in self.clips if c.clip_id == self._drag_clip_id)
            delta_x = event.position().x() - self._drag_start_pos.x()
            delta_time = delta_x / self._pixels_per_second

            if self._drag_mode == "fade_in":
                # Fade in: dragging right increases fade, dragging left decreases
                min_duration, max_duration = self._get_fade_constraints(self._drag_clip_id, "fade_in")

                new_fade_in = self._fade_drag_initial_in + delta_time
                new_fade_in = max(min_duration, min(new_fade_in, max_duration))

                target_clip.set_fade_in(new_fade_in)
                self.update()
            elif self._drag_mode == "fade_out":
                # Fade out: dragging left increases fade, dragging right decreases
                min_duration, max_duration = self._get_fade_constraints(self._drag_clip_id, "fade_out")

                new_fade_out = self._fade_drag_initial_out - delta_time
                new_fade_out = max(min_duration, min(new_fade_out, max_duration))

                target_clip.set_fade_out(new_fade_out)
                self.update()
        elif self._is_dragging_clip and self._drag_clip_id:
            target_clip = next(c for c in self.clips if c.clip_id == self._drag_clip_id)
            delta_x = event.position().x() - self._drag_start_pos.x()
            delta_time = delta_x / self._pixels_per_second
            min_duration = 0.1

            if self._drag_mode == "trim_left":
                # Get collision constraints
                min_bound, max_bound = self._get_trim_constraints(self._drag_clip_id, "trim_left")

                new_start = self._drag_clip_initial_start + delta_time
                new_start = max(min_bound, min(new_start, max_bound))

                target_clip.timeline_start = new_start
                target_clip.start_time = self._drag_clip_source_start + (new_start - self._drag_clip_initial_start)
                target_clip.end_time = self._drag_clip_source_end
                target_clip.duration = max(min_duration, target_clip.end_time - target_clip.start_time)
                # Clamp fade durations to new clip duration
                target_clip.clamp_fade_durations()
                self.update()
            elif self._drag_mode == "trim_right":
                # Get collision constraints
                min_bound, max_bound = self._get_trim_constraints(self._drag_clip_id, "trim_right")

                new_end = self._drag_clip_initial_start + self._drag_clip_initial_duration + delta_time
                new_end = max(min_bound, min(new_end, max_bound))

                target_clip.duration = max(min_duration, new_end - self._drag_clip_initial_start)
                target_clip.end_time = target_clip.start_time + target_clip.duration
                # Clamp fade durations to new clip duration
                target_clip.clamp_fade_durations()
                self.update()
            else:
                new_start = max(0, self._drag_clip_initial_start + delta_time)

                # Collision detection
                min_start = 0
                max_start = float('inf')

                for clip in self.clips:
                    if clip.clip_id == self._drag_clip_id:
                        continue

                    # If clip is to the left
                    if clip.timeline_start + clip.duration <= self._drag_clip_initial_start:
                        min_start = max(min_start, clip.timeline_start + clip.duration)
                    # If clip is to the right
                    elif clip.timeline_start >= self._drag_clip_initial_start + target_clip.duration:
                        max_start = min(max_start, clip.timeline_start - target_clip.duration)

                new_start = max(min_start, min(new_start, max_start))

                if new_start != target_clip.timeline_start:
                    target_clip.timeline_start = new_start
                    self.clip_moved.emit(self._drag_clip_id, new_start)
                    self.update()
        elif self._is_dragging_playhead:
            # Drag playhead
            click_time = event.position().x() / self._pixels_per_second
            self.playhead_moved.emit(max(0, click_time))
        else:
            # Not dragging - update cursor based on hover position
            hover_x = event.position().x()
            hover_y = event.position().y()
            clip_id, edge_type = self._get_clip_edge_at_position(hover_x)

            # Check for fade handle hover
            fade_clip_id, fade_handle_type = self._get_fade_handle_at_position(hover_x, hover_y)

            # Update hover state for fade handles
            if fade_clip_id != self._hovered_fade_clip_id or fade_handle_type != self._hovered_fade_type:
                self._hovered_fade_clip_id = fade_clip_id
                self._hovered_fade_type = fade_handle_type
                self.update()  # Repaint to show hover effect

            if fade_handle_type in ('fade_in', 'fade_out'):
                # Use pointing hand cursor for fade handles
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif edge_type in ('left', 'right'):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif clip_id:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_dragging_fade and self._drag_clip_id:
            target_clip = next((c for c in self.clips if c.clip_id == self._drag_clip_id), None)
            if target_clip:
                # Emit fade changed signal
                self.clip_fade_changed.emit(
                    target_clip.clip_id,
                    target_clip.fade_in_duration,
                    target_clip.fade_out_duration
                )

        if self._is_dragging_clip and self._drag_clip_id:
            target_clip = next((c for c in self.clips if c.clip_id == self._drag_clip_id), None)
            if target_clip:
                if self._drag_mode in ("trim_left", "trim_right"):
                    new_start = target_clip.timeline_start
                    new_end = target_clip.timeline_start + target_clip.duration
                    self.clip_trimmed.emit(target_clip.clip_id, new_start, new_end)
                elif self._drag_mode == "move":
                    self.clip_moved.emit(target_clip.clip_id, target_clip.timeline_start)

        self._is_dragging_clip = False
        self._is_dragging_playhead = False
        self._is_dragging_fade = False
        self._drag_clip_id = None
        self._drag_mode = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        """Handle mouse leaving the widget."""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # Clear hover state
        if self._hovered_fade_clip_id is not None:
            self._hovered_fade_clip_id = None
            self._hovered_fade_type = 'none'
            self.update()

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event."""
        if event.mimeData().hasText() or event.mimeData().hasFormat('application/x-media-item'):
            event.acceptProposedAction()
            self.setStyleSheet("background-color: #353535;")
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave event."""
        self.setStyleSheet("")
        self.update()
    
    def dragMoveEvent(self, event):
        """Handle drag move event."""
        if event.mimeData().hasText() or event.mimeData().hasFormat('application/x-media-item'):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        """Handle drop event."""
        self.setStyleSheet("")
        
        # Get the drop position in timeline time
        drop_x = event.position().x()
        timeline_start = drop_x / self._pixels_per_second
        
        # Parse the mime data
        mime_data = event.mimeData()
        if mime_data.hasFormat('application/x-media-item'):
            data = json.loads(bytes(mime_data.data('application/x-media-item')).decode())
        elif mime_data.hasText():
            data = json.loads(mime_data.text())
        else:
            event.ignore()
            return
        
        # Emit signal with media info
        self.media_dropped.emit(
            data.get('media_id', ''),
            data.get('name', ''),
            data.get('duration', 0.0),
            timeline_start
        )
        
        event.acceptProposedAction()
    
    def add_clip(self, clip: TimelineClip):
        """Add a clip to this track."""
        self.clips.append(clip)
        self.update()

    def update_clip_fade(self, clip_id: str, fade_in: float, fade_out: float) -> bool:
        """Update fade durations for a clip on this track."""
        for clip in self.clips:
            if clip.clip_id == clip_id:
                clip.set_fade_in(fade_in)
                clip.set_fade_out(fade_out)
                self.update()
                return True
        return False
    
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
        
        # Draw gap blocks (empty space between clips)
        self._draw_gap_blocks(painter)
        
        # Draw clips
        for clip in self.clips:
            self._draw_clip(painter, clip)
        
        # Get the playhead position from parent if available
        parent = self.parent()
        while parent:
            if isinstance(parent, TimelineWidget):
                playhead_x = int(parent._playhead_position * self._pixels_per_second)
                # Draw playhead line
                playhead_pen = QPen(QColor("#ff0000"))
                playhead_pen.setWidth(2)
                painter.setPen(playhead_pen)
                painter.drawLine(playhead_x, 0, playhead_x, self.height())
                break
            parent = parent.parent()
        
        painter.end()
    
    def _draw_gap_blocks(self, painter: QPainter):
        """Draw gap blocks (empty space visualization) between clips."""
        if not self.clips:
            return
        
        # Sort clips by timeline start
        sorted_clips = sorted(self.clips, key=lambda c: c.timeline_start)
        
        # Find gaps between clips
        gaps = []
        current_time = 0.0
        
        for clip in sorted_clips:
            if clip.timeline_start > current_time + 0.001:  # Small tolerance
                gap_duration = clip.timeline_start - current_time
                gaps.append((current_time, clip.timeline_start, gap_duration))
            current_time = clip.timeline_start + clip.duration
        
        # Draw each gap block
        for gap_start, gap_end, gap_duration in gaps:
            x = int(gap_start * self._pixels_per_second)
            width = int(gap_duration * self._pixels_per_second)
            
            if width < 5:
                continue  # Skip very small gaps
            
            margin = 3
            rect = QRect(x, margin, width, self.height() - 2 * margin)
            
            # Draw gap background with faded color
            gap_color = QColor(60, 60, 60, 180)  # Semi-transparent dark gray
            brush = QBrush(gap_color)
            painter.setBrush(brush)
            
            # Draw with dashed border
            pen = QPen(QColor(100, 100, 100, 150))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            
            painter.drawRoundedRect(rect, 4, 4)
            
            # Draw gap label
            painter.setPen(QColor(150, 150, 150))
            font = QFont("Segoe UI", 8)
            font.setItalic(True)
            painter.setFont(font)
            
            text_rect = rect.adjusted(5, 5, -5, -5)
            gap_text = f"Gap: {gap_duration:.1f}s"
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, gap_text)
    
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

        # Draw fade zones for all clips (both video and audio with detached audio)
        self._draw_fade_zones(painter, rect, clip)

        # Draw a simple waveform style for audio clips.
        if getattr(clip, "is_audio_only", False):
            self._draw_audio_waveform(painter, rect, clip)
        
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

    def _draw_fade_zones(self, painter: QPainter, rect: QRect, clip: TimelineClip):
        """Draw fade in/out zones as shaded, semi-transparent triangles on the clip.

        Fade in: triangle on the left, slope from top-right to bottom-left.
        Fade out: triangle on the right, slope from top-left to bottom-right.
        Shows hover highlight when mouse is over fade handle.
        """
        if clip.duration <= 0:
            return

        fade_in = clip.fade_in_duration
        fade_out = clip.fade_out_duration

        if fade_in <= 0 and fade_out <= 0:
            return

        # Calculate pixel positions
        clip_width = rect.width()
        clip_left = rect.left()
        clip_top = rect.top()
        clip_bottom = rect.bottom()

        # Check if this clip is being hovered
        is_hovered = (self._hovered_fade_clip_id == clip.clip_id)
        hover_fade_in = is_hovered and self._hovered_fade_type == 'fade_in'
        hover_fade_out = is_hovered and self._hovered_fade_type == 'fade_out'

        fade_fill = QColor(255, 255, 255, 110)  # Semi-transparent white fill
        fade_line = QPen(QColor(255, 255, 255, 160))
        fade_line.setWidth(2)

        # Hover highlight colors
        hover_fill = QColor(0, 188, 212, 80)  # Cyan-ish highlight
        hover_line = QPen(QColor(0, 188, 212, 200))
        hover_line.setWidth(3)

        # Fade in: shaded triangle on left, slope from top-right to bottom-left
        if fade_in > 0:
            fade_in_width = min(clip_width, int(fade_in * self._pixels_per_second))
            if fade_in_width > 0:
                fade_in_polygon = QPolygonF()
                fade_in_polygon.append(QPointF(clip_left, clip_top))
                fade_in_polygon.append(QPointF(clip_left + fade_in_width, clip_top))
                fade_in_polygon.append(QPointF(clip_left, clip_bottom))

                # Use hover highlight if hovering over fade in handle
                if hover_fade_in:
                    painter.setBrush(QBrush(hover_fill))
                    painter.setPen(hover_line)
                    painter.drawPolygon(fade_in_polygon)
                else:
                    painter.setBrush(QBrush(fade_fill))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(fade_in_polygon)

                    painter.setPen(fade_line)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawLine(clip_left + fade_in_width, clip_top, clip_left, clip_bottom)

                # Handle indicator (small filled triangle at top-left)
                handle_size = min(self.FADE_HANDLE_SIZE, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)
                if handle_size > 0:
                    handle_brush = QBrush(QColor(255, 255, 255, 200))
                    painter.setBrush(handle_brush)
                    handle_pen = QPen(QColor(255, 255, 255, 255))
                    handle_pen.setWidth(1)
                    painter.setPen(handle_pen)
                    handle_triangle = QPolygonF()
                    handle_triangle.append(QPointF(clip_left, clip_top))
                    handle_triangle.append(QPointF(clip_left + handle_size * 0.5, clip_top))
                    handle_triangle.append(QPointF(clip_left, clip_top + handle_size * 0.5))
                    painter.drawPolygon(handle_triangle)

        # Fade out: shaded triangle on right, slope from top-left to bottom-right
        if fade_out > 0:
            fade_out_width = min(clip_width, int(fade_out * self._pixels_per_second))
            if fade_out_width > 0:
                fade_out_start_x = clip_left + clip_width - fade_out_width
                fade_out_polygon = QPolygonF()
                fade_out_polygon.append(QPointF(fade_out_start_x, clip_top))
                fade_out_polygon.append(QPointF(clip_left + clip_width, clip_top))
                fade_out_polygon.append(QPointF(clip_left + clip_width, clip_bottom))

                # Use hover highlight if hovering over fade out handle
                if hover_fade_out:
                    painter.setBrush(QBrush(hover_fill))
                    painter.setPen(hover_line)
                    painter.drawPolygon(fade_out_polygon)
                else:
                    painter.setBrush(QBrush(fade_fill))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(fade_out_polygon)

                    painter.setPen(fade_line)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawLine(fade_out_start_x, clip_top, clip_left + clip_width, clip_bottom)

                # Handle indicator (small filled triangle at top-right)
                handle_size = min(self.FADE_HANDLE_SIZE, clip_width / 2 - self.FADE_HANDLE_MIN_DISTANCE)
                if handle_size > 0:
                    handle_brush = QBrush(QColor(255, 255, 255, 200))
                    painter.setBrush(handle_brush)
                    handle_pen = QPen(QColor(255, 255, 255, 255))
                    handle_pen.setWidth(1)
                    painter.setPen(handle_pen)
                    handle_triangle = QPolygonF()
                    handle_triangle.append(QPointF(clip_left + clip_width, clip_top))
                    handle_triangle.append(QPointF(clip_left + clip_width - handle_size * 0.5, clip_top))
                    handle_triangle.append(QPointF(clip_left + clip_width, clip_top + handle_size * 0.5))
                    painter.drawPolygon(handle_triangle)

    def _draw_audio_waveform(self, painter: QPainter, rect: QRect, clip: TimelineClip):
        """Draw stylized waveform bars for audio clips."""
        inner = rect.adjusted(6, 8, -6, -8)
        if inner.width() < 10 or inner.height() < 8:
            return

        center_y = inner.center().y()
        bar_count = max(8, inner.width() // 6)
        spacing = max(2, inner.width() // bar_count)
        seed = sum(ord(ch) for ch in clip.clip_id)

        waveform_pen = QPen(QColor("#e6f7ff"))
        waveform_pen.setWidth(1)
        painter.setPen(waveform_pen)

        for i in range(bar_count):
            # Deterministic pseudo-waveform so each clip looks consistent.
            amp_ratio = 0.2 + (((seed + i * 37) % 80) / 100.0)
            amp = int((inner.height() * amp_ratio) / 2)
            x = inner.left() + i * spacing
            painter.drawLine(x, center_y - amp, x, center_y + amp)


class TimeRuler(QWidget):
    """Time ruler widget for the timeline."""
    
    position_clicked = pyqtSignal(float)
    position_dragged = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixels_per_second = 50
        self._duration = 60.0
        self._playhead_position = 0.0
        self._is_dragging = False
        self.setFixedHeight(30)
        self.setMinimumWidth(1000)
        self.setMouseTracking(True)
    
    def set_zoom(self, pixels_per_second):
        self._pixels_per_second = pixels_per_second
        self.update()
        
    def set_duration(self, duration):
        self._duration = duration
        self.setMinimumWidth(int(duration * self._pixels_per_second) + 100)
        self.update()
    
    def set_playhead_position(self, position):
        self._playhead_position = position
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#2d2d2d"))
        
        pen = QPen(QColor("#888888"))
        painter.setPen(pen)
        
        # Draw ticks
        for i in range(0, int(self._duration) + 1):
            x = int(i * self._pixels_per_second)
            if i % 10 == 0:
                painter.drawLine(x, 10, x, 30)
                painter.drawText(x + 2, 12, f"{i}s")
            elif i % 5 == 0:
                painter.drawLine(x, 15, x, 30)
            else:
                painter.drawLine(x, 22, x, 30)
        
        # Draw playhead triangle marker
        playhead_x = int(self._playhead_position * self._pixels_per_second)
        triangle = QPolygonF()
        triangle.append(QPointF(playhead_x - 6, 0))
        triangle.append(QPointF(playhead_x + 6, 0))
        triangle.append(QPointF(playhead_x, 8))
        painter.setBrush(QBrush(QColor("#ff0000")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(triangle)
        
        # Draw playhead line on ruler too
        painter.setPen(QPen(QColor("#ff0000"), 1))
        painter.drawLine(playhead_x, 8, playhead_x, 30)
        
        painter.end()
                
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            pos = max(0, event.position().x() / self._pixels_per_second)
            self.position_clicked.emit(pos)
    
    def mouseMoveEvent(self, event):
        if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            pos = max(0, event.position().x() / self._pixels_per_second)
            self.position_dragged.emit(pos)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False

class TimelineWidget(QWidget):
    """Multi-track timeline widget.
    
    Signals:
        clip_selected: Emitted when a clip is selected
        clip_double_clicked: Emitted when a clip is double-clicked
        position_changed: Emitted when playhead position changes
        clip_added_to_track: Emitted when a clip is added to a track via drag-drop
        clip_trimmed: Emitted when a clip is trimmed (clip_id, new_start, new_end)
        split_requested: Emitted when split is requested for a clip
    """
    
    clip_selected = pyqtSignal(str)      # clip_id
    clip_double_clicked = pyqtSignal(str)  # clip_id
    position_changed = pyqtSignal(float)  # position in seconds
    clip_added_to_track = pyqtSignal(int, str, float, float)  # track_id, media_id, duration, timeline_start
    clip_trimmed = pyqtSignal(str, float, float)  # clip_id, new_timeline_start, new_timeline_end
    clip_moved = pyqtSignal(str, float)  # clip_id, new_timeline_start
    split_requested = pyqtSignal(str)
    detach_audio_requested = pyqtSignal(str)
    clip_volume_changed = pyqtSignal(str, float)  # clip_id, volume (0.0 to 2.0)
    clip_mute_toggled = pyqtSignal(str)  # clip_id
    clip_fade_changed = pyqtSignal(str, float, float)  # clip_id, fade_in_duration, fade_out_duration
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._tracks: List[TimelineTrack] = []
        self._pixels_per_second = 50
        self._playhead_position = 0.0
        self._duration = 60.0  # Default 1 minute
        
        self._setup_ui()
        self._add_default_tracks()

        # Keep a single selected clip across all tracks.
        self.clip_selected.connect(self._sync_selected_clip_across_tracks)
    
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
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self.ruler_label = QLabel("Timeline")
        self.ruler_label.setObjectName("sectionHeader")
        header_layout.addWidget(self.ruler_label)

        split_btn = QPushButton()
        split_btn.setToolTip("Split selected clip at playhead")
        split_btn.setFixedSize(24, 22)
        split_btn.setIcon(_create_split_icon())
        split_btn.setIconSize(QSize(12, 12))
        split_btn.setStyleSheet("background-color: #3a3a3a; border: 1px solid #555555; padding: 0px;")
        split_btn.clicked.connect(self._request_split_from_toolbar)
        header_layout.addWidget(split_btn)

        self.detach_btn = QPushButton()
        self.detach_btn.setToolTip("Detach audio for all timeline clips")
        self.detach_btn.setFixedSize(24, 22)
        self.detach_btn.setText("🔊↗")
        self.detach_btn.setStyleSheet("background-color: #3a3a3a; border: 1px solid #555555; padding: 0px; font-size: 10px;")
        self.detach_btn.clicked.connect(self._request_detach_audio)
        header_layout.addWidget(self.detach_btn)

        self.mute_btn = QPushButton()
        self.mute_btn.setToolTip("Mute/unmute selected clip")
        self.mute_btn.setFixedSize(24, 22)
        self.mute_btn.setIcon(_create_speaker_icon())
        self.mute_btn.setIconSize(QSize(12, 12))
        self.mute_btn.setStyleSheet("background-color: #3a3a3a; border: 1px solid #555555; padding: 0px;")
        self.mute_btn.clicked.connect(self._toggle_mute)
        header_layout.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(200)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setToolTip("Volume: 100%")
        self.volume_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            " border: 1px solid #555555;"
            " height: 6px;"
            " background: #2d2d2d;"
            " border-radius: 3px;"
            "}"
            "QSlider::handle:horizontal {"
            " background: #00bcd4;"
            " border: 1px solid #00bcd4;"
            " width: 12px;"
            " margin: -4px 0;"
            " border-radius: 6px;"
            "}"
            "QSlider::sub-page:horizontal {"
            " background: #00bcd4;"
            " border-radius: 3px;"
            "}"
        )
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        header_layout.addWidget(self.volume_slider)

        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("timeLabel")
        self.volume_label.setMinimumWidth(35)
        header_layout.addWidget(self.volume_label)

        self._set_audio_controls_enabled(False)
        
        header_layout.addStretch()
        
        # Zoom controls
        zoom_out_btn = QPushButton()
        zoom_out_btn.setFixedSize(24, 22)
        zoom_out_btn.setIcon(_create_minus_icon())
        zoom_out_btn.setIconSize(QSize(12, 12))
        zoom_out_btn.setStyleSheet(
            "background-color: #3a3a3a; border: 1px solid #555555; padding: 0px;"
        )
        zoom_out_btn.setToolTip("Zoom out")
        zoom_out_btn.clicked.connect(self._zoom_out)
        header_layout.addWidget(zoom_out_btn)
        
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("timeLabel")
        header_layout.addWidget(self.zoom_label)
        
        zoom_in_btn = QPushButton()
        zoom_in_btn.setFixedSize(24, 22)
        zoom_in_btn.setIcon(_create_plus_icon())
        zoom_in_btn.setIconSize(QSize(12, 12))
        zoom_in_btn.setStyleSheet(
            "background-color: #3a3a3a; border: 1px solid #555555; padding: 0px;"
        )
        zoom_in_btn.setToolTip("Zoom in")
        zoom_in_btn.clicked.connect(self._zoom_in)
        header_layout.addWidget(zoom_in_btn)
        
        layout.addWidget(header_widget)
        
        # Tracks container
        self.tracks_container = QWidget()
        self.tracks_layout = QVBoxLayout(self.tracks_container)
        self.tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.tracks_layout.setSpacing(2)
        
        # Add TimeRuler to tracks layout
        ruler_row = QWidget()
        ruler_layout = QHBoxLayout(ruler_row)
        ruler_layout.setContentsMargins(0, 0, 0, 0)
        ruler_layout.setSpacing(0)
        
        ruler_header = QWidget()
        ruler_header.setFixedWidth(120)
        ruler_header.setStyleSheet("background-color: #2d2d2d; border-right: 1px solid #404040;")
        
        self.time_ruler = TimeRuler()
        self.time_ruler.position_clicked.connect(self.set_playhead_position)
        self.time_ruler.position_dragged.connect(self.set_playhead_position)
        
        ruler_layout.addWidget(ruler_header)
        ruler_layout.addWidget(self.time_ruler, stretch=1)
        
        self.tracks_layout.addWidget(ruler_row)
        
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
        
        # Connect signals
        track.media_dropped.connect(self._on_media_dropped)
        track.clip_moved.connect(self._on_clip_moved)
        track.clip_trimmed.connect(self._on_clip_trimmed)
        track.split_requested.connect(self._on_split_requested)
        track.playhead_moved.connect(self.set_playhead_position)
        track.clip_volume_changed.connect(self.clip_volume_changed.emit)
        track.clip_mute_toggled.connect(self.clip_mute_toggled.emit)
        track.clip_fade_changed.connect(self._on_clip_fade_changed)
        
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

    def _on_clip_fade_changed(self, clip_id: str, fade_in: float, fade_out: float):
        """Handle fade changed signal from track."""
        self.clip_fade_changed.emit(clip_id, fade_in, fade_out)
        # Update local track model so fades are reflected in UI and preview
        for track in self._tracks:
            if track.update_clip_fade(clip_id, fade_in, fade_out):
                break
    
    def _on_media_dropped(self, media_id: str, name: str, duration: float, timeline_start: float):
        """Handle media dropped on a track."""
        # Find which track emitted the signal
        track = self.sender()
        if isinstance(track, TimelineTrack):
            self.clip_added_to_track.emit(track.track_id, media_id, duration, timeline_start)

    def _on_clip_moved(self, clip_id: str, new_timeline_start: float):
        """Handle clip moved signal from track."""
        # Update project duration if needed
        self._update_duration()
        self.clip_moved.emit(clip_id, new_timeline_start)

    def _request_split_from_toolbar(self):
        """Request split for selected clip or clip under playhead."""
        clip_id = self._get_selected_clip_id()
        if not clip_id:
            clip_id = self._get_clip_at_playhead()
        if clip_id:
            self.split_requested.emit(clip_id)

    def _request_detach_audio(self):
        """Request audio detach for timeline."""
        clip_id = self._get_selected_clip_id() or ""
        self.detach_audio_requested.emit(clip_id)

    def _find_clip_by_id(self, clip_id: str) -> Optional[TimelineClip]:
        """Find clip by id across all tracks."""
        for track in self._tracks:
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return clip
        return None

    def _get_controllable_clip_for_audio_controls(self) -> Optional[TimelineClip]:
        """Return selected clip if it is eligible for direct audio control."""
        clip_id = self._get_selected_clip_id()
        if not clip_id:
            return None

        clip = self._find_clip_by_id(clip_id)
        if not clip:
            return None

        # If a video clip has detached audio, only the detached/audio clip
        # itself is allowed to be controlled.
        if getattr(clip, "has_detached_audio", False) and not getattr(clip, "is_audio_only", False):
            return None

        return clip

    def _set_audio_controls_enabled(self, enabled: bool):
        self.mute_btn.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled)

    def _on_volume_slider_changed(self, value: int):
        """Handle volume slider change for selected eligible clip."""
        self.volume_label.setText(f"{value}%")
        self.volume_slider.setToolTip(f"Volume: {value}%")

        clip = self._get_controllable_clip_for_audio_controls()
        if not clip:
            return

        self.clip_volume_changed.emit(clip.clip_id, value / 100.0)

    def _toggle_mute(self):
        """Toggle mute on selected eligible clip."""
        clip = self._get_controllable_clip_for_audio_controls()
        if not clip:
            return
        self.clip_mute_toggled.emit(clip.clip_id)

    def update_mute_button_state(self, muted: bool):
        """Update mute button icon for selected clip state."""
        self.mute_btn.setIcon(_create_muted_icon() if muted else _create_speaker_icon())

    def update_volume_slider_for_clip(self, clip: Optional[TimelineClip]):
        """Sync header controls with selected clip volume and mute values."""
        if not clip:
            self._set_audio_controls_enabled(False)
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(100)
            self.volume_slider.blockSignals(False)
            self.volume_label.setText("100%")
            self.volume_slider.setToolTip("Volume: 100%")
            self.update_mute_button_state(False)
            return

        selected_clip_id = self._get_selected_clip_id()
        is_selected = bool(selected_clip_id and selected_clip_id == clip.clip_id)
        is_detached_parent = bool(
            getattr(clip, "has_detached_audio", False) and not getattr(clip, "is_audio_only", False)
        )

        self._set_audio_controls_enabled(is_selected and not is_detached_parent)

        volume_pct = int(max(0.0, min(2.0, float(getattr(clip, "volume", 1.0)))) * 100)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume_pct)
        self.volume_slider.blockSignals(False)

        self.volume_label.setText(f"{volume_pct}%")
        self.volume_slider.setToolTip(f"Volume: {volume_pct}%")
        self.update_mute_button_state(bool(getattr(clip, "muted", False)))

    def _get_selected_clip_id(self) -> Optional[str]:
        """Get selected clip id from tracks."""
        for track in self._tracks:
            if track._selected_clip_id:
                return track._selected_clip_id
        return None

    def _sync_selected_clip_across_tracks(self, clip_id: str):
        """Ensure only one clip is selected at a time across all tracks."""
        for track in self._tracks:
            has_clip = any(c.clip_id == clip_id for c in track.clips)
            track._selected_clip_id = clip_id if has_clip else None
            track.update()

    def _get_clip_at_playhead(self) -> Optional[str]:
        """Get first clip id under playhead."""
        pos = self._playhead_position
        for track in self._tracks:
            for clip in track.clips:
                if clip.timeline_start <= pos <= clip.timeline_start + clip.duration:
                    return clip.clip_id
        return None

    def _on_clip_trimmed(self, clip_id: str, new_start: float, new_end: float):
        """Handle clip trimmed signal from track."""
        self._update_duration()
        self.clip_trimmed.emit(clip_id, new_start, new_end)

    def _on_split_requested(self, clip_id: str):
        """Handle split request from track."""
        self.split_requested.emit(clip_id)
    
    def _add_track(self):
        """Add a new track via button."""
        track_num = len(self._tracks) + 1
        self.add_track(f"Track {track_num}")
    
    def add_clip_to_track(self, track_id: int, clip: TimelineClip):
        """Add a clip to a specific track."""
        if 0 <= track_id < len(self._tracks):
            self._tracks[track_id].add_clip(clip)
            self._update_duration()

    def get_clip_track_id(self, clip_id: str) -> Optional[int]:
        """Get the track ID that contains the clip."""
        for track in self._tracks:
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return track.track_id
        return None

    def replace_clip_with(self, track_id: int, clip_id: str, new_clips: List[TimelineClip]):
        """Replace a clip with new clips on a track."""
        if 0 <= track_id < len(self._tracks):
            track = self._tracks[track_id]
            track.remove_clip(clip_id)
            for clip in new_clips:
                track.add_clip(clip)
            self._update_duration()
            self.update()

    def refresh_duration(self):
        """Refresh timeline duration and redraw."""
        self._update_duration()
        self.update()
    
    def remove_clip(self, clip_id: str):
        """Remove a clip from any track."""
        for track in self._tracks:
            if track.remove_clip(clip_id):
                break
    
    def clear(self):
        """Clear all tracks."""
        for track in self._tracks:
            track.clear()
    
    def is_dragging_clip(self) -> bool:
        """Check if any track is currently dragging a clip."""
        for track in self._tracks:
            if track._is_dragging_clip:
                return True
        return False

    def is_dragging_playhead(self) -> bool:
        """Check if any track or ruler is currently dragging the playhead."""
        if self.time_ruler._is_dragging:
            return True
        for track in self._tracks:
            if track._is_dragging_playhead:
                return True
        return False

    def get_dragging_clip_info(self) -> Optional[tuple]:
        """Get info about the clip currently being dragged."""
        for track in self._tracks:
            if track._is_dragging_clip and track._drag_clip_id:
                for clip in track.clips:
                    if clip.clip_id == track._drag_clip_id:
                        return clip, track.track_id
        return None

    def set_playhead_position(self, position: float):
        """Set the playhead position."""
        self._playhead_position = max(0, position)
        self._update_time_label()
        # Update all tracks to redraw playhead
        for track in self._tracks:
            track.update()
        # Update time ruler
        self.time_ruler.set_playhead_position(self._playhead_position)
        
        # Emit signal to sync with player
        self.position_changed.emit(self._playhead_position)
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
        
        # Update ruler zoom
        self.time_ruler.set_zoom(self._pixels_per_second)
        
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
            self.time_ruler.set_duration(self._duration)
