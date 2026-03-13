"""Timeline playback engine for master playback of the entire timeline.

This module provides a comprehensive playback system that treats the entire
timeline as a single sequence, handling clips, gaps, and smooth audio/video
transitions with optimized buffering.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Callable
from enum import Enum, auto
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import QWidget
import time

from video_editor.services.editor_service import TimelineClip
from video_editor.utils.logging_config import get_logger


logger = get_logger("timeline_playback")


class PlaybackState(Enum):
    """State of timeline playback."""
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()
    SEEKING = auto()


@dataclass
class PlaybackSegment:
    """Represents a segment in the timeline (clip or gap)."""
    timeline_start: float
    is_gap: bool = False
    clip: Optional[TimelineClip] = None
    _gap_duration: float = field(default=0.0)  # For gap segments
    _gap_end: float = field(default=0.0)  # For gap segments
    
    @property
    def timeline_end(self) -> float:
        """Dynamic timeline end - always reflects current clip duration if clip segment."""
        if self.is_gap:
            return self._gap_end
        else:
            # For clip segments, calculate from current clip duration (supports trim/split)
            return self.clip.timeline_start + self.clip.duration if self.clip else self.timeline_start
    
    @property
    def duration(self) -> float:
        """Dynamic duration - always reflects current clip duration if clip segment."""
        if self.is_gap:
            return self._gap_duration
        else:
            # For clip segments, use current clip duration (supports trim/split)
            return self.clip.duration if self.clip else 0.0
    
    def contains_position(self, position: float) -> bool:
        """Check if a timeline position falls within this segment."""
        # Use a small epsilon for floating point comparisons
        return self.timeline_start <= position + 1e-6 and position < self.timeline_end - 1e-6


class TimelinePlaybackEngine(QObject):
    """Engine for managing master timeline playback.
    
    This engine treats the entire timeline as a single sequence, managing:
    - A global timer that drives the playhead independently of media player
    - Sequential clip playback with proper source time mapping
    - Gap handling with black screen and silence
    - Playhead synchronization with timeline UI
    """
    
    # Signals
    state_changed = pyqtSignal(object)  # PlaybackState
    position_changed = pyqtSignal(float)  # Timeline position in seconds
    clip_changed = pyqtSignal(object)  # TimelineClip or None for gap
    gap_started = pyqtSignal(float)  # Gap duration
    gap_ended = pyqtSignal()
    playback_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)  # Error message
    
    # Constants
    TIMER_INTERVAL_MS = 16  # ~60fps for smooth playhead movement
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        # Playback state
        self._state: PlaybackState = PlaybackState.STOPPED
        self._position: float = 0.0  # Current timeline position
        self._duration: float = 0.0  # Total timeline duration
        self._playback_rate: float = 1.0
        
        # Timeline data
        self._clips: List[TimelineClip] = []
        self._segments: List[PlaybackSegment] = []
        self._current_segment_index: int = -1
        self._current_segment: Optional[PlaybackSegment] = None
        
        # Media player references (managed externally)
        self._media_player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._video_widget: Optional[QWidget] = None
        self._black_screen: Optional[QWidget] = None
        
        # Master timer - drives playhead independently
        self._master_timer = QTimer(self)
        self._master_timer.setInterval(self.TIMER_INTERVAL_MS)
        self._master_timer.timeout.connect(self._on_master_timer_tick)
        
        # Time tracking for accurate position updates
        self._last_tick_time: float = 0.0
        
        # Clip sync tracking
        self._last_loaded_clip_id: Optional[str] = None
        
        # Callbacks
        self._on_clip_load_callback: Optional[Callable] = None
        self._on_gap_display_callback: Optional[Callable] = None
        
        logger.info("TimelinePlaybackEngine initialized with master timer")
    
    def set_media_player(self, player: QMediaPlayer, audio_output: QAudioOutput,
                         video_widget: QWidget, black_screen: QWidget):
        """Set the media player components for playback.
        
        Args:
            player: QMediaPlayer instance
            audio_output: QAudioOutput instance
            video_widget: Widget for video display
            black_screen: Widget for gap display (black screen)
        """
        self._media_player = player
        self._audio_output = audio_output
        self._video_widget = video_widget
        self._black_screen = black_screen
        
        # Connect only to error signal - we use the global timer for clip boundary enforcement
        if self._media_player:
            self._media_player.errorOccurred.connect(self._on_media_error)
    
    def set_callbacks(self, on_clip_load: Optional[Callable] = None,
                     on_gap_display: Optional[Callable] = None):
        """Set callbacks for clip loading and gap display.
        
        Args:
            on_clip_load: Called when a clip needs to be loaded (clip: TimelineClip)
            on_gap_display: Called when gap should be displayed
        """
        self._on_clip_load_callback = on_clip_load
        self._on_gap_display_callback = on_gap_display
    
    def set_timeline_clips(self, clips: List[TimelineClip]):
        """Set the timeline clips and build playback segments.
        
        Args:
            clips: List of TimelineClip objects
        """
        self._clips = sorted(clips, key=lambda c: c.timeline_start)
        self._build_segments()
        self._calculate_duration()
        
        # CRITICAL: Reset segment tracking when clips change
        # This is crucial when trim/split happens during playback
        # Otherwise _current_segment points to stale segment data with old boundaries
        self._current_segment_index = -1
        self._current_segment = None
        self._last_loaded_clip_id = None
        
        logger.info(f"Timeline set with {len(self._clips)} clips, {len(self._segments)} segments, duration: {self._duration:.2f}s")
    
    def _build_segments(self):
        """Build playback segments from clips, including gaps."""
        self._segments.clear()
        
        if not self._clips:
            return
        
        current_time = 0.0
        
        for clip in self._clips:
            # Check for gap before this clip
            if clip.timeline_start > current_time + 0.001:  # Small tolerance for floating point
                gap_duration = clip.timeline_start - current_time
                gap_segment = PlaybackSegment(
                    timeline_start=current_time,
                    is_gap=True,
                    clip=None,
                    _gap_duration=gap_duration,
                    _gap_end=clip.timeline_start
                )
                self._segments.append(gap_segment)
                logger.debug(f"Gap segment: {current_time:.2f}s - {clip.timeline_start:.2f}s ({gap_duration:.2f}s)")
            
            # Add clip segment
            clip_segment = PlaybackSegment(
                timeline_start=clip.timeline_start,
                is_gap=False,
                clip=clip
            )
            self._segments.append(clip_segment)
            logger.debug(f"Clip segment: {clip.timeline_start:.2f}s - {clip.timeline_start + clip.duration:.2f}s ({clip.name})")
            
            current_time = clip.timeline_start + clip.duration
        
        # Check for gap after last clip (if we want to extend timeline)
        # For now, timeline ends at the last clip
    
    def _calculate_duration(self):
        """Calculate total timeline duration."""
        if self._segments:
            self._duration = self._segments[-1].timeline_end
        else:
            self._duration = 0.0
    
    def get_segment_at_position(self, position: float) -> Optional[PlaybackSegment]:
        """Get the segment at a given timeline position.
        
        Args:
            position: Timeline position in seconds
            
        Returns:
            PlaybackSegment or None if position is out of range
        """
        for segment in self._segments:
            if segment.contains_position(position):
                return segment
        return None
    
    def play(self, start_position: Optional[float] = None):
        """Start or resume playback from a position.
        
        Args:
            start_position: Position to start from (uses current position if None)
        """
        if not self._segments:
            logger.warning("No segments to play")
            return
        
        if self._state == PlaybackState.PLAYING:
            return
        
        if start_position is not None:
            # If start_position is very close to duration, reset to 0
            if start_position >= self._duration - 0.01:
                self._position = 0.0
            else:
                self._position = max(0, min(start_position, self._duration))
        
        self._set_state(PlaybackState.PLAYING)
        
        # Initialize time tracking
        self._last_tick_time = time.time()
        
        # Start the master timer
        self._master_timer.start()
        
        # Update segment and sync media player
        self._update_current_segment()
        
        logger.info(f"Playback started at position {self._position:.2f}s (duration: {self._duration:.2f}s)")
    
    def pause(self):
        """Pause playback.

        Stops video and audio immediately while keeping the playhead at the current position.
        The playhead stays in place so playback can continue from there.
        """
        if self._state != PlaybackState.PLAYING:
            return

        self._set_state(PlaybackState.PAUSED)

        # Stop the master timer immediately
        self._master_timer.stop()

        # Pause media player immediately to stop video and audio
        if self._media_player:
            self._media_player.pause()

        # Mute audio output to ensure no audio bleed
        if self._audio_output:
            self._audio_output.setVolume(0.0)

        # If we're in a clip segment, ensure we stay at the current position
        # by syncing the media player one last time
        if self._current_segment and not self._current_segment.is_gap:
            offset_in_clip = self._position - self._current_segment.timeline_start
            source_position = self._current_segment.clip.start_time + offset_in_clip
            if self._media_player:
                self._media_player.setPosition(int(source_position * 1000))

        logger.info(f"Playback paused at position {self._position:.2f}s")
    
    def resume(self):
        """Resume paused playback."""
        if self._state != PlaybackState.PAUSED:
            return

        self._set_state(PlaybackState.PLAYING)

        # Reinitialize time tracking
        self._last_tick_time = time.time()

        # Ensure current segment and media player are synced before resuming
        self._current_segment_index = -1
        self._current_segment = None
        self._update_current_segment()

        # Start the master timer
        self._master_timer.start()

        # Resume media player if we're in a clip
        if self._media_player and self._current_segment and not self._current_segment.is_gap:
            # Ensure audio volume is restored
            if self._audio_output:
                self._audio_output.setVolume(1.0)
            self._media_player.play()
        else:
            # If we're in a gap, keep audio muted
            if self._audio_output:
                self._audio_output.setVolume(0.0)

        logger.info(f"Playback resumed at position {self._position:.2f}s")
    
    def stop(self):
        """Stop playback and reset to beginning.

        Stops video and audio immediately, clears all buffers, and resets the playhead
        to the beginning of the timeline.
        """
        self._set_state(PlaybackState.STOPPED)

        # Stop the master timer immediately
        self._master_timer.stop()

        # Stop media player immediately and clear buffers
        if self._media_player:
            # Stop first to clear buffers
            self._media_player.stop()
            # Explicitly pause to ensure no async audio continues
            self._media_player.pause()

        # Mute audio output immediately
        if self._audio_output:
            self._audio_output.setVolume(0.0)

        # Clear the video output to avoid stale frames
        if self._video_widget:
            self._video_widget.hide()
        if self._black_screen:
            self._black_screen.show()

        # Reset position and state tracking
        self._position = 0.0
        self._current_segment_index = -1
        self._current_segment = None
        self._last_loaded_clip_id = None

        self.position_changed.emit(self._position)
        logger.info("Playback stopped, buffers cleared, and playhead reset to start")
    
    def seek(self, position: float):
        """Seek to a specific timeline position.

        Args:
            position: Target position in seconds
        """
        position = max(0, min(position, self._duration))

        was_playing = self._state == PlaybackState.PLAYING

        logger.info(f"Seek requested to {position:.2f}s, was_playing={was_playing}")

        # Update position
        self._position = position

        # Reinitialize time tracking
        self._last_tick_time = time.time()

        # Force segment update by resetting current segment
        # This ensures video/audio updates immediately when seeking
        self._current_segment_index = -1
        self._current_segment = None

        # Update segment and sync media player
        self._update_current_segment()

        # Restore correct state
        if was_playing:
            self._set_state(PlaybackState.PLAYING)
        else:
            self._set_state(PlaybackState.PAUSED)

        self.position_changed.emit(position)
        logger.info(f"Seeked to {position:.2f}s")

    def handle_manual_playhead_move(self, position: float):
        """Handle manual playhead movement (e.g., from timeline click or drag).

        This is called when the user manually moves the playhead, which should
        immediately update the preview to show the correct state (clip or gap).

        Args:
            position: New playhead position in seconds
        """
        position = max(0, min(position, self._duration))

        was_playing = self._state == PlaybackState.PLAYING

        # Update position
        self._position = position

        # Determine if we're in a gap so we can force gap display immediately
        segment = self.get_segment_at_position(position)

        # Stop media player when manually moving playhead to prevent audio/video bleed
        self._stop_media_player()

        if segment is None or segment.is_gap:
            # We're in a gap - show black screen and silence
            self._current_segment_index = -1
            self._current_segment = segment if segment else None
            self._last_loaded_clip_id = None  # Force reload when entering clip
            self._display_gap_state()
        else:
            # We're in a clip - force segment update to ensure media is synced immediately
            self._current_segment_index = -1
            self._current_segment = None
            self._last_loaded_clip_id = None  # Force reload for clean start
            self._update_current_segment()

        # Preserve playback state
        if was_playing:
            self._set_state(PlaybackState.PLAYING)
        else:
            self._set_state(PlaybackState.PAUSED)

        self.position_changed.emit(position)
        logger.info(f"Manual playhead move to {position:.2f}s")

    def _display_gap_state(self):
        """Display gap state: black screen and silent audio."""
        # Show black screen
        if self._video_widget:
            self._video_widget.hide()
        if self._black_screen:
            self._black_screen.show()

        # Stop media player and mute audio to ensure no video/audio continues
        self._stop_media_player()

        # Reset last loaded clip to force reload when entering a clip
        self._last_loaded_clip_id = None

        # Emit signals
        self.clip_changed.emit(None)
        self.gap_started.emit(0.0)
    
    def _on_master_timer_tick(self):
        """Master timer tick - drives the playhead independently."""
        if self._state != PlaybackState.PLAYING:
            return
        
        # Calculate elapsed time since last tick
        current_time = time.time()
        elapsed = (current_time - self._last_tick_time) * self._playback_rate
        self._last_tick_time = current_time
        
        # Update position
        self._position += elapsed
        
        # Check if we've reached the end of the timeline
        if self._position >= self._duration:
            self._position = self._duration
            self._on_timeline_finished()
            return
        
        # CRITICAL FIX: Check if we're in a clip and have exceeded its trimmed end time
        # This must happen BEFORE _update_current_segment to catch boundary violations early
        if self._current_segment and not self._current_segment.is_gap:
            segment_end = self._current_segment.timeline_end
            if self._position >= segment_end:
                # We've reached the end of this clip - stop media player immediately!
                logger.debug(f"TIMER ENFORCEMENT: Position {self._position:.3f}s >= segment end {segment_end:.3f}s")
                self._position = segment_end
                # Stop media player immediately
                if self._media_player:
                    self._media_player.pause()
                if self._audio_output:
                    self._audio_output.setVolume(0.0)
                # Transition to next segment
                self._transition_to_next_segment()
                # Emit position change
                self.position_changed.emit(self._position)
                return
        
        # Update current segment and sync media player
        self._update_current_segment()
        
        # Emit position change
        self.position_changed.emit(self._position)
    
    def _update_current_segment(self):
        """Update the current segment based on position and sync media player."""
        # Find the segment at current position
        segment = self.get_segment_at_position(self._position)
        
        if segment is None:
            # We might be in a gap before the first clip
            if self._segments and self._position < self._segments[0].timeline_start:
                segment = self._segments[0]
            else:
                # End of timeline or invalid position
                if self._position >= self._duration - 0.01:
                    self._on_timeline_finished()
                else:
                    # Trim/split can temporarily create a timeline range with no explicit segment
                    # (for example during interactive edits). Treat it as an implicit gap.
                    logger.debug(
                        f"No segment at position {self._position:.3f}s; handling as implicit gap"
                    )
                    self._current_segment_index = -1
                    self._current_segment = None
                    self._display_gap_state()
                return
        
        # Check if segment changed
        segment_index = self._segments.index(segment)
        segment_changed = (segment_index != self._current_segment_index)
        
        if segment_changed:
            logger.debug(f"Segment changed from {self._current_segment_index} to {segment_index}")
            self._current_segment_index = segment_index
        
        # Handle segment type
        if segment.is_gap:
            self._handle_gap_segment(segment, segment_changed)
        else:
            self._current_segment = segment
            self._handle_clip_segment(segment, segment_changed)

        # Ensure audio volume matches current state after segment updates
        if self._audio_output:
            if self._state == PlaybackState.PLAYING and not segment.is_gap:
                self._audio_output.setVolume(1.0)
            else:
                self._audio_output.setVolume(0.0)
    
    def _handle_gap_segment(self, segment: PlaybackSegment, segment_changed: bool = False):
        """Handle being in a gap segment.

        When in a gap:
        - Show black screen
        - Mute audio
        - Stop the media player to prevent any video/audio from continuing
        - Reset the last loaded clip to force reload when entering next clip
        """
        # Check if we're entering a new gap (for signal emission)
        entering_new_gap = segment_changed or (self._current_segment != segment)

        # Update current segment tracking
        self._current_segment = segment

        # Show black screen
        if self._video_widget:
            self._video_widget.hide()
        if self._black_screen:
            self._black_screen.show()

        # Stop media player and mute audio during gaps
        # This ensures no video or audio continues playing from previous clip
        self._stop_media_player()

        # Reset clip tracking to force reload when entering next clip
        # This ensures proper sync when transitioning from gap to clip
        self._last_loaded_clip_id = None

        # Emit signals only when entering a new gap
        if entering_new_gap:
            remaining = segment.timeline_end - self._position
            self.gap_started.emit(remaining)
            self.clip_changed.emit(None)

            if self._on_gap_display_callback:
                self._on_gap_display_callback()
    
    def _handle_clip_segment(self, segment: PlaybackSegment, segment_changed: bool):
        """Handle being in a clip segment."""
        if not segment.clip:
            logger.error("Clip segment has no clip data")
            return

        clip = segment.clip

        # Check if we've exceeded the clip's end time
        if self._position >= segment.timeline_end:
            # We've passed the end of this clip - transition to next segment
            self._transition_to_next_segment()
            return

        # Calculate source position
        offset_in_clip = self._position - segment.timeline_start
        source_position = clip.start_time + offset_in_clip

        # Calculate the maximum source position for this clip (respecting trim/split boundaries)
        max_source_pos = clip.end_time - 0.01  # Small buffer to avoid reading exactly at end

        # Check if we're approaching or have reached the end of the clip
        # This is critical for trimmed/split clips to stop at the correct point
        if source_position >= max_source_pos:
            # We've reached the end of this clip - transition to next segment
            logger.debug(f"Clip {clip.name} reached end at source position {source_position:.2f}s")
            self._position = segment.timeline_end  # Snap to segment end
            self._transition_to_next_segment()
            return

        # Clamp source position to clip bounds to prevent reading beyond clip end
        if source_position > max_source_pos:
            source_position = max_source_pos

        # Check if we need to load the clip
        clip_id = clip.clip_id
        need_reload = (clip_id != self._last_loaded_clip_id)

        if need_reload or segment_changed:
            logger.debug(f"Loading clip {clip.name} at source position {source_position:.2f}s")
            self._last_loaded_clip_id = clip_id

            # Show video widget
            if self._black_screen:
                self._black_screen.hide()
            if self._video_widget:
                self._video_widget.show()

            # Emit clip changed signal
            self.clip_changed.emit(clip)

            # Call clip load callback - this loads and positions the media
            if self._on_clip_load_callback:
                self._on_clip_load_callback(clip, source_position)
        else:
            # Same clip - always sync the media player position
            self._sync_media_player_position(source_position)

        # Handle audio volume based on state
        if self._audio_output:
            if self._state == PlaybackState.PLAYING:
                self._audio_output.setVolume(1.0)
            else:
                # Paused or stopped - mute audio
                self._audio_output.setVolume(0.0)

    def _transition_to_next_segment(self):
        """Transition from current clip to the next segment (gap or next clip).

        Ensures clean transitions by stopping media player when leaving a clip
        and properly initializing the next segment.
        """
        if self._current_segment_index < 0 or self._current_segment_index >= len(self._segments) - 1:
            # No more segments - we're at the end
            self._on_timeline_finished()
            return

        # Get current segment before transitioning
        current_segment = self._current_segment

        # Move to next segment
        next_index = self._current_segment_index + 1
        next_segment = self._segments[next_index]

        logger.debug(f"Transitioning from segment {self._current_segment_index} to {next_index}")

        # If we're leaving a clip, stop the media player to prevent audio/video bleed
        if current_segment and not current_segment.is_gap:
            self._stop_media_player()

        self._current_segment_index = next_index

        # Position at the start of the next segment
        self._position = next_segment.timeline_start

        # Handle the new segment
        if next_segment.is_gap:
            self._handle_gap_segment(next_segment, True)
        else:
            # Force segment reload for clean clip start
            self._current_segment = next_segment
            self._last_loaded_clip_id = None
            self._handle_clip_segment(next_segment, True)

        self.position_changed.emit(self._position)
    
    def _sync_media_player_position(self, source_position: float):
        """Sync the media player to the given source position."""
        if not self._media_player:
            return

        # Get current media player position
        current_media_pos = self._media_player.position() / 1000.0

        # Calculate the difference
        diff = abs(current_media_pos - source_position)

        # Always sync if difference is significant (> 0.05 seconds for better responsiveness)
        if diff > 0.05:
            logger.debug(f"Syncing media player: {current_media_pos:.2f}s -> {source_position:.2f}s")
            self._media_player.setPosition(int(source_position * 1000))

        # Handle media player state based on our state
        from PyQt6.QtMultimedia import QMediaPlayer

        if self._state == PlaybackState.PLAYING:
            # Ensure media player is playing
            if self._media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self._media_player.play()
        elif self._state == PlaybackState.PAUSED:
            # Ensure media player is paused
            if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._media_player.pause()
        elif self._state == PlaybackState.STOPPED:
            # Ensure media player is stopped
            if self._media_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
                self._media_player.stop()

    def _stop_media_player(self):
        """Stop the media player and clear any buffered content.
        
        Uses pause() instead of stop() for better responsiveness, but ensures
        volume is muted to prevent audio bleed.
        """
        if not self._media_player:
            return

        # Pause instead of stop to keep buffers ready but stop playback
        self._media_player.pause()

        # Mute audio output
        if self._audio_output:
            self._audio_output.setVolume(0.0)
    
    def _on_timeline_finished(self):
        """Called when playback reaches the end of the timeline."""
        logger.info("Timeline playback finished")

        # Stop the master timer
        self._master_timer.stop()

        # Stop media player completely
        if self._media_player:
            self._media_player.stop()

        # Mute audio
        if self._audio_output:
            self._audio_output.setVolume(0.0)

        # Update state
        self._set_state(PlaybackState.STOPPED)

        # Show black screen
        if self._video_widget:
            self._video_widget.hide()
        if self._black_screen:
            self._black_screen.show()

        # Reset tracking
        self._last_loaded_clip_id = None
        self._current_segment = None
        self._current_segment_index = -1

        # Emit finished signal
        self.playback_finished.emit()
    
    def _on_media_error(self, error, error_string):
        """Handle media player errors."""
        logger.error(f"Media player error: {error_string}")
        self.error_occurred.emit(error_string)
    
    def _set_state(self, state: PlaybackState):
        """Set the playback state and emit signal."""
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)
    
    # Properties
    @property
    def state(self) -> PlaybackState:
        """Get current playback state."""
        return self._state
    
    @property
    def position(self) -> float:
        """Get current timeline position."""
        return self._position
    
    @property
    def duration(self) -> float:
        """Get total timeline duration."""
        return self._duration
    
    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._state == PlaybackState.PLAYING
    
    @property
    def is_in_gap(self) -> bool:
        """Check if currently playing a gap."""
        if self._current_segment:
            return self._current_segment.is_gap
        return False
    
    @property
    def current_clip(self) -> Optional[TimelineClip]:
        """Get the currently playing clip, or None if in a gap."""
        if self._current_segment and not self._current_segment.is_gap:
            return self._current_segment.clip
        return None
    
    def set_playback_rate(self, rate: float):
        """Set the playback rate (1.0 = normal, 2.0 = double speed, etc.).
        
        Args:
            rate: Playback rate multiplier
        """
        self._playback_rate = max(0.25, min(4.0, rate))
        
        if self._media_player:
            self._media_player.setPlaybackRate(self._playback_rate)
        
        logger.info(f"Playback rate set to {self._playback_rate}x")
    
    def clear(self):
        """Clear all timeline data."""
        self.stop()
        self._clips.clear()
        self._segments.clear()
        self._duration = 0.0
        self._position = 0.0
        self._last_loaded_clip_id = None
        logger.info("Timeline cleared")