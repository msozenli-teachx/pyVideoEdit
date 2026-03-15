"""Video preview widget for displaying video frames.

Provides a video preview area with transport controls and processing options.
Uses QMediaPlayer and QVideoWidget for real video playback.
Integrates with TimelinePlaybackEngine for master timeline playback.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QSizePolicy, QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoFrame
from PyQt6.QtMultimediaWidgets import QVideoWidget
from typing import Optional, List
import os

from video_editor.core.timeline_playback import TimelinePlaybackEngine, PlaybackState
from video_editor.services.editor_service import TimelineClip
from video_editor.utils.logging_config import get_logger


logger = get_logger("preview_widget")


class PreviewWidget(QWidget):
    """Widget for video preview and transport controls.
    
    Supports two modes:
    1. Single media playback - plays a single media file
    2. Timeline master playback - plays the entire timeline as a sequence
    
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
        
        # Timeline playback mode
        self._timeline_mode: bool = False
        self._timeline_playback_engine: Optional[TimelinePlaybackEngine] = None
        
        self._setup_ui()
        self._setup_media_player()
        self._setup_timeline_playback_engine()
    
    def _setup_timeline_playback_engine(self):
        """Initialize the timeline playback engine."""
        self._timeline_playback_engine = TimelinePlaybackEngine(self)
        
        # Connect engine signals
        self._timeline_playback_engine.state_changed.connect(self._on_playback_state_changed_engine)
        self._timeline_playback_engine.position_changed.connect(self._on_timeline_position_changed)
        self._timeline_playback_engine.clip_changed.connect(self._on_clip_changed)
        self._timeline_playback_engine.gap_started.connect(self._on_gap_started)
        self._timeline_playback_engine.gap_ended.connect(self._on_gap_ended)
        self._timeline_playback_engine.playback_finished.connect(self._on_timeline_finished)
        self._timeline_playback_engine.error_occurred.connect(self._on_playback_error)
        
        # Set callbacks
        self._timeline_playback_engine.set_callbacks(
            on_clip_load=self._load_and_play_clip_segment,
            on_gap_display=self._display_gap_screen
        )

        # Media player is created before engine initialization in __init__,
        # so wire player references here.
        self._timeline_playback_engine.set_media_player(
            self._media_player,
            self._audio_output,
            self.video_widget,
            self._black_screen,
            self._detached_audio_player,
            self._detached_audio_output,
        )
        
        logger.info("Timeline playback engine initialized")
    
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

        # Detached audio output/player (independent from video clip player)
        self._detached_audio_output = QAudioOutput()
        self._detached_audio_output.setVolume(1.0)
        self._detached_audio_player = QMediaPlayer()
        self._detached_audio_player.setAudioOutput(self._detached_audio_output)
        
        # Create media player
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self.video_widget)
        
        # Connect media player signals
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.positionChanged.connect(self._on_media_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)
        
        # Connect playback engine to media player
        if self._timeline_playback_engine:
            self._timeline_playback_engine.set_media_player(
                self._media_player,
                self._audio_output,
                self.video_widget,
                self._black_screen,
                self._detached_audio_player,
                self._detached_audio_output,
            )
    
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
        if self._duration > 0:
            self._current_position = max(0, min(position, self._duration))
        else:
            self._current_position = max(0, position)
        
        # Update slider
        if self._duration > 0:
            slider_value = int((self._current_position / self._duration) * 1000)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(slider_value)
            self.position_slider.blockSignals(False)
        
        self._update_time_display()

    def set_timeline_total_duration(self, duration: float):
        """Force preview total duration to timeline total (used during manual scrubbing)."""
        if duration <= 0:
            return

        self._duration = duration
        if self._current_position > self._duration:
            self._current_position = self._duration

        if self._duration > 0:
            slider_value = int((self._current_position / self._duration) * 1000)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(slider_value)
            self.position_slider.blockSignals(False)

        self._update_time_display()

    def _set_slider_from_position(self):
        """Update position slider using current position and duration."""
        if self._duration <= 0:
            return
        slider_value = int((self._current_position / self._duration) * 1000)
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(slider_value)
        self.position_slider.blockSignals(False)

    def _stop_players_and_mute(self, clear_source: bool = False):
        """Stop preview players and silence outputs."""
        self._media_player.stop()
        self._media_player.pause()

        if clear_source:
            current_source = self._media_player.source()
            self._media_player.setSource(QUrl())
            if current_source:
                self._media_player.setSource(current_source)
                self._media_player.pause()

        if self._detached_audio_player:
            self._detached_audio_player.stop()
            self._detached_audio_player.pause()

        if self._audio_output:
            self._audio_output.setVolume(0.0)
        if self._detached_audio_output:
            self._detached_audio_output.setVolume(0.0)

    def _reset_transport_ui(self, media_label: Optional[str] = None):
        """Reset transport/playhead UI state after a stop/finish action."""
        self._is_playing = False
        self._current_position = 0.0
        self._update_play_button()
        self._update_time_display()

        self.position_slider.blockSignals(True)
        self.position_slider.setValue(0)
        self.position_slider.blockSignals(False)

        self._black_screen.show()
        self.video_widget.hide()

        if media_label is not None:
            self.media_label.setText(media_label)
    
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
        try:
            if self._timeline_mode:
                # Use timeline playback engine
                if self._timeline_playback_engine:
                    if self._timeline_playback_engine.state == PlaybackState.PLAYING:
                        self._timeline_playback_engine.pause()
                        # Also pause media player and mute audio immediately
                        self._media_player.pause()
                        if self._audio_output:
                            self._audio_output.setVolume(0.0)
                        self.pause_clicked.emit()
                    elif self._timeline_playback_engine.state == PlaybackState.PAUSED:
                        self._timeline_playback_engine.resume()
                        self.play_clicked.emit()
                    else:
                        # STOPPED state - need to start playback
                        # Get current position from slider
                        if self._duration > 0:
                            start_pos = (self.position_slider.value() / 1000) * self._duration
                        else:
                            start_pos = 0
                        self._timeline_playback_engine.play(start_pos)
                        self.play_clicked.emit()
                return

            # Single media playback mode
            if self._current_file_path is None:
                return

            if self._is_playing:
                self._media_player.pause()
                if self._audio_output:
                    self._audio_output.setVolume(0.0)
                self.pause_clicked.emit()
            else:
                if self._audio_output:
                    self._audio_output.setVolume(1.0)
                self._media_player.play()
                self.play_clicked.emit()
        except Exception as e:
            logger.exception("Play click handling failed")
            self._is_playing = False
            self._update_play_button()
            self._display_gap_screen()
            self.placeholder_label.setText(f"Playback error:\n{e}")
            self.placeholder_label.show()
    
    def _on_stop_clicked(self):
        """Handle stop button click.

        Stops video and audio immediately, clears all buffers, and resets the playhead
        to the beginning of the timeline.
        """
        # Stop the engine if in timeline mode - this clears buffers and resets position
        if self._timeline_playback_engine:
            self._timeline_playback_engine.stop()

        self._timeline_mode = False
        self._stop_players_and_mute()
        self._reset_transport_ui(media_label="Stopped")

        self.stop_clicked.emit()
    
    def _on_slider_pressed(self):
        """Handle slider press - start dragging."""
        self._slider_is_dragging = True
    
    def _on_slider_released(self):
        """Handle slider release - finish dragging and seek."""
        self._slider_is_dragging = False
        if self._duration > 0:
            position = (self.position_slider.value() / 1000) * self._duration
            
            if self._timeline_mode and self._timeline_playback_engine:
                # Seek in timeline mode
                self._timeline_playback_engine.seek(position)
            else:
                # Seek in single media mode
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
        self._update_play_button()
    
    # Timeline playback engine signal handlers
    def _on_playback_state_changed_engine(self, state: PlaybackState):
        """Handle playback state changes from the engine."""
        self._is_playing = (state == PlaybackState.PLAYING)
        self._update_play_button()
        logger.debug(f"Engine state changed to: {state.name}")
    
    def _on_timeline_position_changed(self, position: float):
        """Handle timeline position changes from the engine.

        Updates the slider and time display to match the playhead position.
        """
        if self._slider_is_dragging:
            return

        self._current_position = position

        # Update slider to match playhead position
        self._set_slider_from_position()

        # Update time display
        self._update_time_display()

        # Always emit for external sync (timeline playhead)
        # The main window handles feedback loop prevention
        self.position_changed.emit(position)
    
    def _on_clip_changed(self, clip: Optional[TimelineClip]):
        """Handle clip change during timeline playback."""
        if clip:
            logger.debug(f"Now playing clip: {clip.name}")
            self.media_label.setText(clip.name)
        else:
            # In gap
            self.media_label.setText("Gap (black)")
    
    def _on_gap_started(self, duration: float):
        """Handle gap playback start."""
        logger.debug(f"Gap started, duration: {duration:.2f}s")
        # Gap display is already handled by engine callback to avoid duplicate stop calls.
    
    def _on_gap_ended(self):
        """Handle gap playback end."""
        logger.debug("Gap ended")
    
    def _on_timeline_finished(self):
        """Handle timeline playback finished."""
        logger.info("Timeline playback finished")

        self._stop_players_and_mute()
        self._timeline_mode = False
        self._reset_transport_ui()
    
    def _on_playback_error(self, error_message: str):
        """Handle playback error."""
        logger.error(f"Playback error: {error_message}")
        self.placeholder_label.setText(f"Playback error:\n{error_message}")
        self.placeholder_label.show()
        self.video_widget.hide()
    
    def _load_and_play_clip_segment(self, clip: TimelineClip, source_position: float):
        """Load and play a specific clip segment.
        
        This is a callback from the TimelinePlaybackEngine.
        
        Args:
            clip: The clip to play
            source_position: Position within the source media to start from
        """
        logger.debug(f"Loading clip segment: {clip.name} at {source_position:.2f}s")
        
        # Get file path from clip
        media_path = clip.file_path if hasattr(clip, 'file_path') and clip.file_path else ""
        
        if not media_path or not os.path.exists(media_path):
            logger.error(f"Media file not found: {media_path}")
            # The engine will handle moving to the next segment on the next timer tick
            return
        
        self._current_file_path = str(media_path)

        # Keep black screen until the new clip/frame is prepared to avoid old-frame flash.
        self.video_widget.hide()
        self._black_screen.show()

        def _is_engine_playing() -> bool:
            return bool(
                self._timeline_playback_engine
                and self._timeline_playback_engine.state == PlaybackState.PLAYING
            )

        def _activate_clip_view(is_playing_now: bool):
            self._black_screen.hide()
            self.video_widget.show()
            if self._audio_output:
                # Engine controls whether video-clip audio should be audible
                # (e.g. muted when clip audio is detached).
                self._audio_output.setVolume(0.0 if not is_playing_now else self._audio_output.volume())

        def _reveal_after_seek(target_ms: int, is_playing_now: bool):
            """Reveal video only after seek settles to avoid stale-frame flash."""
            done = False
            reached_target = False
            sink = self.video_widget.videoSink() if hasattr(self.video_widget, "videoSink") else None

            def _finish():
                nonlocal done
                if done:
                    return
                done = True
                try:
                    self._media_player.positionChanged.disconnect(_on_position_changed)
                except Exception:
                    pass
                if sink is not None:
                    try:
                        sink.videoFrameChanged.disconnect(_on_video_frame_changed)
                    except Exception:
                        pass
                _activate_clip_view(is_playing_now)

            def _on_video_frame_changed(frame):
                # Only reveal after seek target is reached and a fresh frame arrives.
                if done or not reached_target:
                    return
                if self._media_player.source() != new_source:
                    return
                try:
                    if frame is None or not frame.isValid():
                        return
                except Exception:
                    pass
                _finish()

            def _on_position_changed(pos_ms: int):
                nonlocal reached_target
                # Reveal once we're at/near target frame for the current source.
                if done:
                    return
                if self._media_player.source() != new_source:
                    return
                if pos_ms >= max(0, target_ms - 120):
                    reached_target = True
                    if sink is None:
                        _finish()

            self._media_player.positionChanged.connect(_on_position_changed)
            if sink is not None:
                sink.videoFrameChanged.connect(_on_video_frame_changed)

            # Short fallback to keep transitions snappy if backend signals are delayed.
            QTimer.singleShot(90, _finish)
        
        # Check if we need to load a new source or just seek
        current_source = self._media_player.source()
        new_source = QUrl.fromLocalFile(self._current_file_path)
        
        if current_source != new_source:
            # Need to load new source
            logger.debug(f"Loading new source: {self._current_file_path}")
            self._media_player.setSource(new_source)
            
            # We need to wait for the media to be loaded before seeking and playing
            # Use a lambda to seek and play once the media is ready
            def on_media_status_changed(status):
                from PyQt6.QtMultimedia import QMediaPlayer
                if status in (
                    QMediaPlayer.MediaStatus.LoadedMedia,
                    QMediaPlayer.MediaStatus.BufferedMedia,
                ):
                    self._media_player.mediaStatusChanged.disconnect(on_media_status_changed)
                    # Seek to the source position
                    seek_ms = int(source_position * 1000)
                    self._media_player.setPosition(seek_ms)

                    # Start playback only if engine is in PLAYING state
                    playing_now = _is_engine_playing()
                    if playing_now:
                        self._media_player.play()
                    else:
                        # Ensure paused state
                        self._media_player.pause()
                    _reveal_after_seek(seek_ms, playing_now)
                    logger.debug(f"Media loaded, seeked to {source_position:.2f}s, playing={playing_now}")
            
            self._media_player.mediaStatusChanged.connect(on_media_status_changed)

            # Fallback: if readiness signal ordering is odd on some backends,
            # enforce seek/play shortly after source assignment.
            def _enforce_clip_start():
                if self._media_player.source() != new_source:
                    return
                seek_ms = int(source_position * 1000)
                self._media_player.setPosition(seek_ms)
                playing_now = _is_engine_playing()
                if playing_now:
                    self._media_player.play()
                else:
                    self._media_player.pause()
                _reveal_after_seek(seek_ms, playing_now)

            QTimer.singleShot(150, _enforce_clip_start)
        else:
            # Same source, just seek
            logger.debug(f"Same source, seeking to {source_position:.2f}s")
            seek_ms = int(source_position * 1000)
            self._media_player.setPosition(seek_ms)

            # Start playback only if engine is in PLAYING state
            playing_now = _is_engine_playing()
            if playing_now:
                self._media_player.play()
            else:
                # Ensure paused state
                self._media_player.pause()

            _reveal_after_seek(seek_ms, playing_now)
        
        # Update UI
        self.media_label.setText(clip.name)
        self.placeholder_label.hide()
    
    def _display_gap_screen(self):
        """Display black screen for gap playback.

        This is called when the playhead is in a gap between clips.
        Shows black screen and ensures audio is silent.
        """
        logger.debug("Displaying gap screen (black)")

        # Avoid hard stop here; stop() causes decoder reset and visible micro-stutter
        # on next clip transitions. Pause is enough for gap silence/hold.
        self._media_player.pause()

        # Hide video widget and show black screen
        self.video_widget.hide()
        self._black_screen.show()

        # Clear any stale frame in sink so previous clip frame cannot flash on reveal.
        try:
            sink = self.video_widget.videoSink()
            if sink is not None:
                sink.setVideoFrame(QVideoFrame())
        except Exception:
            # Backend may not expose sink operations consistently; safe to ignore.
            pass

        # Mute audio to ensure no sound
        if self._audio_output:
            self._audio_output.setVolume(0.0)

        # Update media label
        self.media_label.setText("Gap (black)")
    
    def start_timeline_playback(self, clips: List[TimelineClip], start_position: float = 0):
        """Start playing the timeline from a specific position.
        
        This activates master playback mode where the entire timeline
        is treated as a single sequence.
        
        Args:
            clips: List of TimelineClip objects sorted by timeline_start
            start_position: Timeline position to start from (seconds)
        """
        if not clips:
            logger.warning("No clips to play")
            return

        self._timeline_mode = True
        
        # Set clips in the playback engine
        self._timeline_playback_engine.set_timeline_clips(clips)
        
        # Update duration to timeline duration
        self._duration = self._timeline_playback_engine.duration
        
        # Update time display
        self._update_time_display()
        
        # Hide placeholder, show video or black screen
        self.placeholder_label.hide()
        
        logger.info(f"Starting timeline playback at {start_position:.2f}s, duration: {self._duration:.2f}s")
        
        # Start playback
        self._timeline_playback_engine.play(start_position)
    
    def stop_timeline_playback(self):
        """Stop timeline playback and return to normal mode.

        Stops video and audio, clears buffers, and resets the playhead to the beginning.
        """
        if self._timeline_playback_engine:
            self._timeline_playback_engine.stop()

        self._stop_players_and_mute(clear_source=True)

        # Reset state
        self._timeline_mode = False
        self._reset_transport_ui()

        logger.info("Timeline playback stopped and reset")
    
    def set_timeline_clips(self, clips: List[TimelineClip]):
        """Set the timeline clips without starting playback.
        
        This is useful for updating the timeline state when clips change.
        
        Args:
            clips: List of TimelineClip objects
        """
        if self._timeline_playback_engine:
            self._timeline_playback_engine.set_timeline_clips(clips)
            self._duration = self._timeline_playback_engine.duration
            
            # If current position is beyond new duration, cap it
            if self._current_position > self._duration:
                self._current_position = self._duration
                
            self._update_time_display()

            self._set_slider_from_position()

    def update_current_clip_volume(self):
        """Apply updated clip volume/mute settings to active timeline playback."""
        if self._timeline_playback_engine:
            self._timeline_playback_engine.update_current_clip_volume()
    
    def seek_timeline(self, position: float):
        """Seek to a position in the timeline.

        Args:
            position: Timeline position in seconds
        """
        if self._timeline_mode and self._timeline_playback_engine:
            self._timeline_playback_engine.seek(position)
        elif self._current_file_path:
            # Single media mode
            self._media_player.setPosition(int(position * 1000))

    def sync_to_playhead(self, position: float, is_in_gap: bool = False):
        """Synchronize the preview to the current playhead position.

        This is called when the playhead is moved manually to ensure the preview
        shows the correct content (clip or gap).

        Args:
            position: Current playhead position in seconds
            is_in_gap: True if the playhead is in a gap between clips
        """
        self._current_position = position

        # Update slider
        self._set_slider_from_position()

        # Update time display
        self._update_time_display()

        # Handle gap or clip display
        if is_in_gap:
            # In a gap: stop media player, show black screen, mute audio
            self._display_gap_screen()
        else:
            # In a clip: show video widget, hide black screen
            self.video_widget.show()
            self._black_screen.hide()

            # Only restore audio volume if playing, otherwise keep muted
            if self._audio_output:
                if self._is_playing:
                    self._audio_output.setVolume(1.0)
                else:
                    self._audio_output.setVolume(0.0)
    
    def is_timeline_mode(self) -> bool:
        """Check if currently in timeline playback mode."""
        return self._timeline_mode
    
    def _on_media_position_changed(self, position_ms: int):
        """Handle media player position changes (position in milliseconds)."""
        # In timeline mode, the engine drives the position, not the media player
        if self._timeline_mode:
            return
        
        if self._slider_is_dragging:
            return  # Don't update while user is dragging
        
        position = position_ms / 1000.0  # Convert to seconds
        self._current_position = position

        self._set_slider_from_position()
        
        self._update_time_display()
        
        # Emit position change for timeline sync
        self.position_changed.emit(position)
    
    def _on_duration_changed(self, duration_ms: int):
        """Handle media player duration changes (duration in milliseconds)."""
        # In timeline mode, total duration must come from the timeline engine,
        # not from the currently loaded source clip.
        if self._timeline_mode:
            return

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
