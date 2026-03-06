"""Video preview widget for displaying video frames.

Provides a video preview area with transport controls and processing options.
Uses QMediaPlayer and QVideoWidget for real video playback.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QFileDialog, QSizePolicy, QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QUrl
from PyQt6.QtGui import QImage, QPixmap, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from typing import Optional, List, Callable
from pathlib import Path
import os


class PreviewWidget(QWidget):
    """Widget for video preview and transport controls.
    
    Signals:
        play_clicked: Emitted when play button is clicked
        pause_clicked: Emitted when pause button is clicked
        stop_clicked: Emitted when stop button is clicked
        position_changed: Emitted when position slider is moved
        time_input_requested: Emitted when user wants to set time range
        process_clicked: Emitted when process button is clicked
    """
    
    play_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    position_changed = pyqtSignal(float)  # position in seconds
    time_input_requested = pyqtSignal()
    process_clicked = pyqtSignal()  # Emitted when Process button is clicked
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self._duration: float = 0.0
        self._current_position: float = 0.0
        self._is_playing: bool = False
        self._clip_start: float = 0.0
        self._clip_end: float = 0.0
        self._current_file_path: Optional[str] = None
        self._slider_is_dragging: bool = False
        
        # Timeline playback state
        self._timeline_mode: bool = False
        self._timeline_clips: List = []
        self._current_clip_index: int = -1
        self._timeline_start_position: float = 0.0
        self._gap_timer: Optional[QTimer] = None
        self._black_screen: Optional[QWidget] = None
        
        self._setup_ui()
        self._setup_media_player()
    
    def _setup_ui(self):
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Preview")
        title_label.setObjectName("sectionHeader")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Current media label
        self.media_label = QLabel("No media selected")
        self.media_label.setObjectName("timeLabel")
        header_layout.addWidget(self.media_label)
        
        layout.addLayout(header_layout)
        
        # Video container
        self.preview_container = QFrame()
        self.preview_container.setObjectName("previewWidget")
        self.preview_container.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_container.setMinimumSize(320, 180)
        
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        
        # Placeholder label (shown when no video loaded)
        self.placeholder_label = QLabel("No video loaded\n\nSelect a media file from the pool")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setObjectName("timeLabel")
        preview_layout.addWidget(self.placeholder_label)
        
        # Video widget (hidden initially)
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_widget.hide()
        preview_layout.addWidget(self.video_widget)
        
        # Black screen widget for gaps (hidden initially)
        self._black_screen = QWidget()
        self._black_screen.setStyleSheet("background-color: black;")
        self._black_screen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._black_screen.hide()
        preview_layout.addWidget(self._black_screen)
        
        layout.addWidget(self.preview_container, stretch=1)
        
        # Time display and slider
        time_layout = QHBoxLayout()
        
        self.time_display = QLabel("00:00:00 / 00:00:00")
        self.time_display.setObjectName("timeLabel")
        time_layout.addWidget(self.time_display)
        
        time_layout.addStretch()
        
        # Set time range button
        self.set_range_btn = QPushButton("Set Range")
        self.set_range_btn.setToolTip("Set start/end time for clipping")
        self.set_range_btn.clicked.connect(self._on_set_range_clicked)
        time_layout.addWidget(self.set_range_btn)
        
        layout.addLayout(time_layout)
        
        # Position slider
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setValue(0)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self.position_slider)
        
        # Transport controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(15)
        controls_layout.addStretch()
        
        # Stop button
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setToolTip("Stop")
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        controls_layout.addWidget(self.stop_btn)
        
        # Play/Pause button
        self.play_btn = QPushButton("▶")
        self.play_btn.setToolTip("Play")
        self.play_btn.setFixedSize(50, 50)
        self.play_btn.setObjectName("primaryButton")
        self.play_btn.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self.play_btn)
        
        # Step back/forward
        self.step_back_btn = QPushButton("⏮")
        self.step_back_btn.setToolTip("Step back 1 second")
        self.step_back_btn.setFixedSize(40, 40)
        self.step_back_btn.clicked.connect(lambda: self._step_position(-1))
        controls_layout.addWidget(self.step_back_btn)
        
        self.step_forward_btn = QPushButton("⏭")
        self.step_forward_btn.setToolTip("Step forward 1 second")
        self.step_forward_btn.setFixedSize(40, 40)
        self.step_forward_btn.clicked.connect(lambda: self._step_position(1))
        controls_layout.addWidget(self.step_forward_btn)
        
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # Clip settings group
        clip_group = QGroupBox("Clip Settings")
        clip_layout = QVBoxLayout(clip_group)
        
        # Time inputs row
        time_input_layout = QHBoxLayout()
        
        time_input_layout.addWidget(QLabel("Start:"))
        self.start_time_input = QLineEdit("00:00:00")
        self.start_time_input.setPlaceholderText("HH:MM:SS")
        self.start_time_input.setMaximumWidth(100)
        self.start_time_input.setToolTip("Start time (HH:MM:SS or seconds)")
        time_input_layout.addWidget(self.start_time_input)
        
        time_input_layout.addWidget(QLabel("End:"))
        self.end_time_input = QLineEdit("00:00:00")
        self.end_time_input.setPlaceholderText("HH:MM:SS")
        self.end_time_input.setMaximumWidth(100)
        self.end_time_input.setToolTip("End time (HH:MM:SS or seconds)")
        time_input_layout.addWidget(self.end_time_input)
        
        # Set from current position buttons
        self.set_start_btn = QPushButton("Set Start")
        self.set_start_btn.setToolTip("Set start from current position")
        self.set_start_btn.clicked.connect(self._set_start_from_current)
        time_input_layout.addWidget(self.set_start_btn)
        
        self.set_end_btn = QPushButton("Set End")
        self.set_end_btn.setToolTip("Set end from current position")
        self.set_end_btn.clicked.connect(self._set_end_from_current)
        time_input_layout.addWidget(self.set_end_btn)
        
        time_input_layout.addStretch()
        
        clip_layout.addLayout(time_input_layout)
        
        # Duration display and Process button
        process_layout = QHBoxLayout()
        
        self.duration_label = QLabel("Duration: 00:00:00")
        self.duration_label.setObjectName("timeLabel")
        process_layout.addWidget(self.duration_label)
        
        process_layout.addStretch()
        
        # Process button
        self.process_btn = QPushButton("Process")
        self.process_btn.setObjectName("primaryButton")
        self.process_btn.setMinimumWidth(120)
        self.process_btn.setMinimumHeight(40)
        self.process_btn.setToolTip("Process the clip with FFmpeg (-c copy for lossless)")
        self.process_btn.clicked.connect(self._on_process_clicked)
        process_layout.addWidget(self.process_btn)
        
        clip_layout.addLayout(process_layout)
        
        layout.addWidget(clip_group)
        
        self.setObjectName("previewContainer")
    
    def _setup_media_player(self):
        """Setup QMediaPlayer and QAudioOutput."""
        # Create audio output
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(1.0)
        
        # Create media player
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self.video_widget)
        
        # Connect media player signals
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.positionChanged.connect(self._on_media_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)
    
    def load_video(self, file_path: str, name: str, duration: float):
        """Load a video file into the media player.
        
        Args:
            file_path: Path to the video file
            name: Media name for display
            duration: Duration in seconds
        """
        self._current_file_path = file_path
        self._duration = duration
        self._current_position = 0.0
        self._clip_start = 0.0
        self._clip_end = duration
        
        # Stop any current playback
        self._media_player.stop()
        
        # Load the media
        url = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(url)
        
        # Update UI
        self.media_label.setText(name)
        self.placeholder_label.hide()
        self.video_widget.show()
        
        # Update time inputs
        self.start_time_input.setText(self._format_time(0.0))
        self.end_time_input.setText(self._format_time(duration))
        self._update_duration_label()
        self._update_time_display()
        self._update_play_button()
    
    def set_media(self, name: str, duration: float):
        """Set the current media for preview (without loading file).
        
        Args:
            name: Media name
            duration: Duration in seconds
        """
        self._duration = duration
        self._current_position = 0.0
        self._is_playing = False
        self._clip_start = 0.0
        self._clip_end = duration
        
        self.media_label.setText(name)
        
        # Update time inputs
        self.start_time_input.setText(self._format_time(0.0))
        self.end_time_input.setText(self._format_time(duration))
        self._update_duration_label()
        
        self._update_time_display()
        self._update_play_button()
    
    def clear_media(self):
        """Clear the current media."""
        self._media_player.stop()
        self._media_player.setSource(QUrl())
        
        self._duration = 0.0
        self._current_position = 0.0
        self._is_playing = False
        self._current_file_path = None
        
        self.media_label.setText("No media selected")
        self.placeholder_label.setText("No video loaded\n\nSelect a media file from the pool")
        self.placeholder_label.show()
        self.video_widget.hide()
        
        self.start_time_input.setText("00:00:00")
        self.end_time_input.setText("00:00:00")
        self._update_duration_label()
        
        self._update_time_display()
        self._update_play_button()
    
    def set_position(self, position: float):
        """Set the current playback position.
        
        Args:
            position: Position in seconds
        """
        self._current_position = max(0, min(position, self._duration))
        
        # Update slider
        if self._duration > 0:
            slider_value = int((self._current_position / self._duration) * 1000)
            self.position_slider.setValue(slider_value)
        
        self._update_time_display()
    
    def set_frame(self, image: QImage):
        """Display a video frame.
        
        Args:
            image: QImage to display
        """
        if image and not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self.image_label.setPixmap(pixmap)
            self.image_label.show()
            self.placeholder_label.hide()
    
    def set_playing(self, playing: bool):
        """Set the playback state.
        
        Args:
            playing: True if playing, False if paused
        """
        self._is_playing = playing
        self._update_play_button()
    
    def set_processing(self, processing: bool):
        """Set processing state (disable controls during processing).
        
        Args:
            processing: True if processing, False otherwise
        """
        self.process_btn.setEnabled(not processing)
        self.process_btn.setText("Processing..." if processing else "Process")
    
    def get_start_time(self) -> float:
        """Get start time from input field in seconds."""
        return self._parse_time(self.start_time_input.text())
    
    def get_end_time(self) -> float:
        """Get end time from input field in seconds."""
        return self._parse_time(self.end_time_input.text())
    
    def set_start_time(self, seconds: float):
        """Set start time input."""
        self._clip_start = seconds
        self.start_time_input.setText(self._format_time(seconds))
        self._update_duration_label()
    
    def set_end_time(self, seconds: float):
        """Set end time input."""
        self._clip_end = seconds
        self.end_time_input.setText(self._format_time(seconds))
        self._update_duration_label()
    
    def _set_start_from_current(self):
        """Set start time from current position."""
        self.set_start_time(self._current_position)
    
    def _set_end_from_current(self):
        """Set end time from current position."""
        self.set_end_time(self._current_position)
    
    def _update_duration_label(self):
        """Update duration label based on start/end times."""
        start = self._parse_time(self.start_time_input.text())
        end = self._parse_time(self.end_time_input.text())
        duration = max(0, end - start)
        self.duration_label.setText(f"Duration: {self._format_time(duration)}")
    
    def _update_play_button(self):
        """Update play button state."""
        if self._is_playing:
            self.play_btn.setText("⏸")
            self.play_btn.setToolTip("Pause")
        else:
            self.play_btn.setText("▶")
            self.play_btn.setToolTip("Play")
    
    def _update_time_display(self):
        """Update the time display label."""
        current = self._format_time(self._current_position)
        total = self._format_time(self._duration)
        self.time_display.setText(f"{current} / {total}")
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def _parse_time(self, time_str: str) -> float:
        """Parse time string to seconds."""
        time_str = time_str.strip()
        parts = time_str.split(':')
        
        try:
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
            elif len(parts) == 2:
                minutes, seconds = parts
                return float(minutes) * 60 + float(seconds)
            else:
                return float(time_str)
        except ValueError:
            return 0.0
    
    def _on_play_clicked(self):
        """Handle play/pause button click."""
        if self._current_file_path is None:
            return
        
        if self._is_playing:
            self._media_player.pause()
            self.pause_clicked.emit()
        else:
            self._media_player.play()
            self.play_clicked.emit()
    
    def _on_stop_clicked(self):
        """Handle stop button click."""
        self._media_player.stop()
        self.stop_clicked.emit()
        self.set_position(0)
    
    def _on_slider_pressed(self):
        """Handle slider press - start dragging."""
        self._slider_is_dragging = True
    
    def _on_slider_released(self):
        """Handle slider release - finish dragging and seek."""
        self._slider_is_dragging = False
        if self._duration > 0:
            position = (self.position_slider.value() / 1000) * self._duration
            self._media_player.setPosition(int(position * 1000))  # Convert to milliseconds
    
    def _on_slider_moved(self, value: int):
        """Handle position slider movement during drag."""
        if self._duration > 0:
            position = (value / 1000) * self._duration
            self._current_position = position
            self._update_time_display()
            self.position_changed.emit(position)
    
    def _on_slider_value_changed(self, value: int):
        """Handle slider value change (only when not dragging)."""
        if not self._slider_is_dragging:
            pass  # Slider updates are handled by media player position changes
    
    def _step_position(self, seconds: float):
        """Step the position by specified seconds."""
        if self._current_file_path is None:
            return
        
        new_position = self._current_position + seconds
        new_position = max(0, min(new_position, self._duration))
        
        # Seek the media player
        self._media_player.setPosition(int(new_position * 1000))
        self._current_position = new_position
        self._update_time_display()
        self.position_changed.emit(new_position)
    
    def _on_playback_state_changed(self, state):
        """Handle media player playback state changes."""
        from PyQt6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._is_playing = True
        else:
            self._is_playing = False
            # In timeline mode, check if we need to move to next clip
            if self._timeline_mode and not self._slider_is_dragging:
                self._check_timeline_advance()
        self._update_play_button()
    
    def _check_timeline_advance(self):
        """Check if we need to advance to next clip in timeline mode."""
        if not self._timeline_mode or self._current_clip_index < 0:
            return
        
        current_clip = self._timeline_clips[self._current_clip_index]
        clip_end_in_timeline = current_clip.timeline_start + current_clip.duration
        
        # Check if we've reached the end of current clip
        if self._current_position >= current_clip.duration - 0.1:  # Small tolerance
            self._advance_to_next_clip()
    
    def _advance_to_next_clip(self):
        """Advance playback to next clip in timeline."""
        self._current_clip_index += 1
        
        if self._current_clip_index >= len(self._timeline_clips):
            # End of timeline
            self.stop_timeline_playback()
            return
        
        next_clip = self._timeline_clips[self._current_clip_index]
        prev_clip = self._timeline_clips[self._current_clip_index - 1]
        prev_end = prev_clip.timeline_start + prev_clip.duration
        
        # Check for gap
        gap_duration = next_clip.timeline_start - prev_end
        
        if gap_duration > 0.1:  # Gap exists
            self._show_black_screen(gap_duration)
        else:
            self._load_and_play_clip(next_clip)
    
    def _show_black_screen(self, duration: float):
        """Show black screen for gap duration."""
        self._media_player.pause()
        self.video_widget.hide()
        self._black_screen.show()
        
        # Use timer to advance after gap
        if self._gap_timer is None:
            self._gap_timer = QTimer(self)
            self._gap_timer.setSingleShot(True)
            self._gap_timer.timeout.connect(self._on_gap_finished)
        
        self._gap_timer.start(int(duration * 1000))
    
    def _on_gap_finished(self):
        """Called when gap timer finishes."""
        self._black_screen.hide()
        if self._current_clip_index < len(self._timeline_clips):
            self._load_and_play_clip(self._timeline_clips[self._current_clip_index])
    
    def _load_and_play_clip(self, clip):
        """Load and play a specific clip."""
        from PyQt6.QtCore import QUrl
        
        self._black_screen.hide()
        self.video_widget.show()
        
        # Load the media file
        media_path = clip.file_path if hasattr(clip, 'file_path') and clip.file_path else ""
        if not media_path:
            # Try to get from media_file attribute if it exists
            if hasattr(clip, 'media_file') and clip.media_file:
                media_path = clip.media_file.file_path
        self._current_file_path = str(media_path)
        
        if not self._current_file_path or not os.path.exists(self._current_file_path):
            # Skip this clip if file doesn't exist
            self._advance_to_next_clip()
            return
        
        url = QUrl.fromLocalFile(self._current_file_path)
        self._media_player.setSource(url)
        
        # Seek to clip start position
        start_ms = int(clip.start_time * 1000) if hasattr(clip, 'start_time') else 0
        self._media_player.setPosition(start_ms)
        
        # Update UI
        self.media_label.setText(clip.name)
        self.placeholder_label.hide()
        
        # Start playback
        self._media_player.play()
    
    def start_timeline_playback(self, clips: List, start_position: float = 0):
        """Start playing the timeline from a specific position.
        
        Args:
            clips: List of TimelineClip objects sorted by timeline_start
            start_position: Timeline position to start from (seconds)
        """
        if not clips:
            return
        
        self._timeline_mode = True
        self._timeline_clips = sorted(clips, key=lambda c: c.timeline_start)
        self._timeline_start_position = start_position
        
        # Find which clip contains the start position
        self._current_clip_index = -1
        for i, clip in enumerate(self._timeline_clips):
            clip_end = clip.timeline_start + clip.duration
            if clip.timeline_start <= start_position < clip_end:
                self._current_clip_index = i
                break
            elif start_position < clip.timeline_start:
                # Start position is in a gap before this clip
                self._current_clip_index = i
                gap_duration = clip.timeline_start - start_position
                self._show_black_screen(gap_duration)
                return
        
        if self._current_clip_index < 0:
            # Start position is after all clips
            self._current_clip_index = len(self._timeline_clips) - 1
        
        # Load and play the starting clip
        start_clip = self._timeline_clips[self._current_clip_index]
        offset_in_clip = start_position - start_clip.timeline_start
        
        self._load_and_play_clip(start_clip)
        
        # Seek to correct position within clip
        if offset_in_clip > 0:
            seek_pos = int((start_clip.start_time + offset_in_clip) * 1000) if hasattr(start_clip, 'start_time') else int(offset_in_clip * 1000)
            self._media_player.setPosition(seek_pos)
    
    def stop_timeline_playback(self):
        """Stop timeline playback and return to normal mode."""
        self._timeline_mode = False
        self._timeline_clips = []
        self._current_clip_index = -1
        
        if self._gap_timer and self._gap_timer.isActive():
            self._gap_timer.stop()
        
        self._black_screen.hide()
        self._media_player.stop()
        self._on_stop_clicked()
    
    def is_timeline_mode(self) -> bool:
        """Check if currently in timeline playback mode."""
        return self._timeline_mode
    
    def _on_media_position_changed(self, position_ms: int):
        """Handle media player position changes (position in milliseconds)."""
        if self._slider_is_dragging:
            return  # Don't update while user is dragging
        
        position = position_ms / 1000.0  # Convert to seconds
        self._current_position = position
        
        # Update slider
        if self._duration > 0:
            slider_value = int((position / self._duration) * 1000)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(slider_value)
            self.position_slider.blockSignals(False)
        
        self._update_time_display()
        
        # Emit position change for timeline sync
        self.position_changed.emit(position)
    
    def _on_duration_changed(self, duration_ms: int):
        """Handle media player duration changes (duration in milliseconds)."""
        duration = duration_ms / 1000.0  # Convert to seconds
        if duration > 0:
            self._duration = duration
            self._clip_end = duration
            self.end_time_input.setText(self._format_time(duration))
            self._update_time_display()
    
    def _on_media_error(self, error, error_string):
        """Handle media player errors."""
        from PyQt6.QtMultimedia import QMediaPlayer
        if error != QMediaPlayer.Error.NoError:
            self.placeholder_label.setText(f"Error loading video:\n{error_string}")
            self.placeholder_label.show()
            self.video_widget.hide()
    
    def _on_set_range_clicked(self):
        """Handle set range button click."""
        self.time_input_requested.emit()
    
    def _on_process_clicked(self):
        """Handle process button click."""
        self.process_clicked.emit()
    
    def get_current_position(self) -> float:
        """Get current playback position."""
        return self._current_position
    
    def get_duration(self) -> float:
        """Get current media duration."""
        return self._duration
    
    def set_volume(self, volume: float):
        """Set audio volume (0.0 to 1.0)."""
        self._audio_output.setVolume(max(0.0, min(1.0, volume)))
