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
    video_fade_changed = pyqtSignal(float)  # Fade percentage (0.0 = dark, 1.0 = normal)
    
    # Constants
    TIMER_INTERVAL_MS = 16  # ~60fps for smooth playhead movement
    PLAYING_RESYNC_THRESHOLD_S = 0.18
    PAUSED_RESYNC_THRESHOLD_S = 0.05
    RESYNC_COOLDOWN_S = 0.12

    def _should_play_clip_audio(self, clip: Optional[TimelineClip]) -> bool:
        """Return True when video player's own audio should be audible."""
        if clip is None:
            return False
        # If audio is detached from this video clip, keep the video player muted.
        return not bool(getattr(clip, "has_detached_audio", False))

    def _get_effective_clip_volume(self, clip: Optional[TimelineClip]) -> float:
        """Get mute-aware clip volume in QMediaPlayer range [0.0, 1.0]."""
        if clip is None:
            return 0.0
        if hasattr(clip, "get_effective_volume"):
            try:
                return max(0.0, min(1.0, float(clip.get_effective_volume())))
            except Exception:
                pass
        muted = bool(getattr(clip, "muted", False))
        base = float(getattr(clip, "volume", 1.0))
        return 0.0 if muted else max(0.0, min(1.0, base))

    def _get_effective_clip_volume_at_position(self, clip: Optional[TimelineClip], position_in_clip: float) -> float:
        """Get fade-aware clip volume at a specific position within the clip."""
        if clip is None:
            return 0.0

        duration = float(getattr(clip, "duration", 0.0))
        if duration <= 0:
            return 0.0

        position_in_clip = max(0.0, min(position_in_clip, duration))

        if hasattr(clip, "get_volume_at_position"):
            try:
                volume = float(clip.get_volume_at_position(position_in_clip))
                return max(0.0, min(1.0, volume))
            except Exception:
                pass

        return self._get_effective_clip_volume(clip)

    def _apply_current_fade_volume(self):
        """Apply fade-aware volume for the current timeline position."""
        if not self._audio_output:
            return

        if (
            self._state == PlaybackState.PLAYING
            and self._current_segment
            and not self._current_segment.is_gap
            and self._should_play_clip_audio(self._current_segment.clip)
        ):
            position_in_clip = self._position - self._current_segment.timeline_start
            volume = self._get_effective_clip_volume_at_position(self._current_segment.clip, position_in_clip)
            self._set_output_volume(self._audio_output, volume)
        else:
            self._set_output_volume(self._audio_output, 0.0)

    def _get_video_fade_percentage(self, clip: Optional[TimelineClip], position_in_clip: float) -> float:
        """Calculate video fade percentage based on clip fade settings.
        
        Returns:
            0.0 = fully dark, 1.0 = fully visible (normal)
        """
        if clip is None:
            return 1.0

        duration = float(getattr(clip, "duration", 0.0))
        if duration <= 0:
            return 1.0

        position_in_clip = max(0.0, min(position_in_clip, duration))

        fade_in = float(getattr(clip, "fade_in_duration", 0.0))
        fade_out = float(getattr(clip, "fade_out_duration", 0.0))

        # Check fade in zone
        if fade_in > 0 and position_in_clip < fade_in:
            # Linear fade in: 0% at start to 100% at fade_in_duration
            return position_in_clip / fade_in

        # Check fade out zone
        if fade_out > 0:
            fade_out_start = duration - fade_out
            if position_in_clip > fade_out_start:
                # Linear fade out: 100% at fade_out_start to 0% at end
                remaining = duration - position_in_clip
                return remaining / fade_out

        # Normal playback (not in fade zone)
        return 1.0

    def _apply_video_fade(self):
        """Apply video fade overlay based on current playhead position."""
        if not self._current_segment or self._current_segment.is_gap:
            self.video_fade_changed.emit(1.0)
            return

        clip = self._current_segment.clip
        if not clip:
            self.video_fade_changed.emit(1.0)
            return

        position_in_clip = self._position - self._current_segment.timeline_start
        fade_percentage = self._get_video_fade_percentage(clip, position_in_clip)
        self.video_fade_changed.emit(fade_percentage)

    def _set_output_volume(self, output: Optional[QAudioOutput], value: float):
        """Safely set volume on an audio output."""
        if output:
            output.setVolume(max(0.0, min(1.0, value)))

    def _mute_all_outputs(self):
        """Mute both primary and detached audio outputs."""
        self._set_output_volume(self._audio_output, 0.0)
        self._set_output_volume(self._detached_audio_output, 0.0)
    
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
        self._detached_audio_player: Optional[QMediaPlayer] = None
        self._detached_audio_output: Optional[QAudioOutput] = None
        self._video_widget: Optional[QWidget] = None
        self._black_screen: Optional[QWidget] = None
        
        # Master timer - drives playhead independently
        self._master_timer = QTimer(self)
        self._master_timer.setInterval(self.TIMER_INTERVAL_MS)
        self._master_timer.timeout.connect(self._on_master_timer_tick)
        
        # Time tracking for accurate position updates
        self._last_tick_time: float = 0.0
        self._last_media_resync_time: float = 0.0
        
        # Clip sync tracking
        self._last_loaded_clip_id: Optional[str] = None
        self._last_detached_audio_clip_id: Optional[str] = None
        
        # Callbacks
        self._on_clip_load_callback: Optional[Callable] = None
        self._on_gap_display_callback: Optional[Callable] = None
        
        logger.info("TimelinePlaybackEngine initialized with master timer")
    
    def set_media_player(
        self,
        player: QMediaPlayer,
        audio_output: QAudioOutput,
        video_widget: QWidget,
        black_screen: QWidget,
        detached_audio_player: Optional[QMediaPlayer] = None,
        detached_audio_output: Optional[QAudioOutput] = None,
    ):
        """Set the media player components for playback.
        
        Args:
            player: QMediaPlayer instance
            audio_output: QAudioOutput instance
            video_widget: Widget for video display
            black_screen: Widget for gap display (black screen)
            detached_audio_player: Optional player for detached audio clips
            detached_audio_output: Optional audio output for detached audio clips
        """
        self._media_player = player
        self._audio_output = audio_output
        self._detached_audio_player = detached_audio_player
        self._detached_audio_output = detached_audio_output
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
        self._last_detached_audio_clip_id = None
        
        logger.info(f"Timeline set with {len(self._clips)} clips, {len(self._segments)} segments, duration: {self._duration:.2f}s")
    
    def _build_segments(self):
        """Build playback segments from clips, including gaps."""
        self._segments.clear()

        # Audio-only clips are handled by detached audio sync and should not
        # influence video segment transitions.
        video_clips = [c for c in self._clips if not getattr(c, "is_audio_only", False)]

        if not video_clips:
            return
        
        current_time = 0.0

        for clip in video_clips:
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
        segment_duration = self._segments[-1].timeline_end if self._segments else 0.0
        clips_duration = 0.0
        if self._clips:
            clips_duration = max((c.timeline_start + c.duration) for c in self._clips)
        self._duration = max(segment_duration, clips_duration)
    
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
        if self._duration <= 0:
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
        try:
            self._update_current_segment()
            self._sync_detached_audio()
        except Exception as e:
            logger.exception("Playback start sync failed")
            self.error_occurred.emit(str(e))
            self.stop()
            return
        
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

        self._mute_all_outputs()

        # If we're in a clip segment, ensure we stay at the current position
        # by syncing the media player one last time
        if self._current_segment and not self._current_segment.is_gap:
            offset_in_clip = self._position - self._current_segment.timeline_start
            source_position = self._current_segment.clip.start_time + offset_in_clip
            if self._media_player:
                self._media_player.setPosition(int(source_position * 1000))

        if self._detached_audio_player:
            self._detached_audio_player.pause()
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
                if self._should_play_clip_audio(self._current_segment.clip):
                    self._audio_output.setVolume(self._get_effective_clip_volume_at_position(
                        self._current_segment.clip,
                        self._position - self._current_segment.timeline_start
                    ))
                else:
                    self._audio_output.setVolume(0.0)
            self._media_player.play()
        else:
            # If we're in a gap, keep audio muted
            self._set_output_volume(self._audio_output, 0.0)

        self._sync_detached_audio()

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

        self._stop_detached_audio_player()

        self._mute_all_outputs()

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
        self._last_detached_audio_clip_id = None

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
        self._sync_detached_audio()

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

        self._sync_detached_audio()

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

        try:
        
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
                    self._set_output_volume(self._audio_output, 0.0)
                    if self._detached_audio_player:
                        self._detached_audio_player.pause()
                    self._set_output_volume(self._detached_audio_output, 0.0)
                    # Transition to next segment
                    self._transition_to_next_segment()
                    # Emit position change
                    self.position_changed.emit(self._position)
                    return
        
            # Update current segment and sync media player
            self._update_current_segment()
            self._sync_detached_audio()
            self._apply_current_fade_volume()
            self._apply_video_fade()
        
            # Emit position change
            self.position_changed.emit(self._position)
        except Exception as e:
            logger.exception("Master timer tick failed")
            self.error_occurred.emit(str(e))
            self.stop()
    
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
                    self._sync_detached_audio()
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
        self._apply_current_fade_volume()
    
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
        self._apply_current_fade_volume()


    def _transition_to_next_segment(self):
        """Transition from current clip to the next segment (gap or next clip).

        Ensures clean transitions by stopping media player when leaving a clip
        and properly initializing the next segment.
        """
        if self._current_segment_index < 0 or self._current_segment_index >= len(self._segments) - 1:
            # No more video segments. If timeline duration is longer (e.g. detached
            # audio tail), continue in implicit-gap state until real timeline end.
            if self._position < self._duration - 0.01:
                self._current_segment = None
                self._current_segment_index = -1
                self._last_loaded_clip_id = None
                self._display_gap_state()
                self.position_changed.emit(self._position)
                return

            # No remaining media to play.
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

        self._sync_detached_audio()

        self.position_changed.emit(self._position)
    
    def _sync_media_player_position(self, source_position: float):
        """Sync the media player to the given source position."""
        if not self._media_player:
            return

        # Get current media player position
        current_media_pos = self._media_player.position() / 1000.0

        # Calculate the difference
        diff = abs(current_media_pos - source_position)

        # Avoid aggressive setPosition calls while playing; frequent hard seeks
        # can create visible micro-stutter on trimmed clips.
        now = time.time()
        threshold = (
            self.PLAYING_RESYNC_THRESHOLD_S
            if self._state == PlaybackState.PLAYING
            else self.PAUSED_RESYNC_THRESHOLD_S
        )
        can_resync_now = (now - self._last_media_resync_time) >= self.RESYNC_COOLDOWN_S

        if diff > threshold and can_resync_now:
            logger.debug(f"Syncing media player: {current_media_pos:.2f}s -> {source_position:.2f}s")
            self._media_player.setPosition(int(source_position * 1000))
            self._last_media_resync_time = now

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
        self._mute_all_outputs()

    def _stop_detached_audio_player(self):
        """Stop detached audio playback and mute output."""
        if self._detached_audio_player:
            self._detached_audio_player.stop()
            self._detached_audio_player.pause()
        if self._detached_audio_output:
            self._detached_audio_output.setVolume(0.0)

    def _get_detached_audio_clip_at_position(self) -> Optional[TimelineClip]:
        """Return detached/audio-only clip active at current timeline position."""
        epsilon = 1e-6
        for clip in self._clips:
            if not getattr(clip, "is_audio_only", False):
                continue
            clip_start = clip.timeline_start
            clip_end = clip.timeline_start + clip.duration
            if clip_start <= self._position + epsilon and self._position < clip_end - epsilon:
                return clip
        return None

    def _sync_detached_audio(self):
        """Synchronize detached audio player to timeline position."""
        if not self._detached_audio_player:
            return

        try:

            audio_clip = self._get_detached_audio_clip_at_position()
            if not audio_clip:
                self._last_detached_audio_clip_id = None
                if self._detached_audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._detached_audio_player.pause()
                if self._detached_audio_output:
                    self._detached_audio_output.setVolume(0.0)
                return

            media_path = getattr(audio_clip, "file_path", "")
            if not media_path:
                return

            from PyQt6.QtCore import QUrl

            source = QUrl.fromLocalFile(str(media_path))
            if self._detached_audio_player.source() != source:
                self._detached_audio_player.setSource(source)
                self._last_detached_audio_clip_id = audio_clip.clip_id

            offset_in_clip = self._position - audio_clip.timeline_start
            source_position = audio_clip.start_time + offset_in_clip
            source_position = max(audio_clip.start_time, min(source_position, max(audio_clip.start_time, audio_clip.end_time - 0.01)))
            target_ms = int(source_position * 1000)

            if abs(self._detached_audio_player.position() - target_ms) > 120:
                self._detached_audio_player.setPosition(target_ms)

            if self._state == PlaybackState.PLAYING:
                if self._detached_audio_output:
                    position_in_clip = self._position - audio_clip.timeline_start
                    self._detached_audio_output.setVolume(
                        self._get_effective_clip_volume_at_position(audio_clip, position_in_clip)
                    )
                if self._detached_audio_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self._detached_audio_player.play()
            else:
                if self._detached_audio_output:
                    self._detached_audio_output.setVolume(0.0)
                if self._detached_audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._detached_audio_player.pause()
        except Exception as e:
            logger.exception("Detached audio sync failed")
            self.error_occurred.emit(str(e))
            self._stop_detached_audio_player()

    def update_current_clip_volume(self):
        """Apply current clip and detached audio clip volume/mute values immediately."""
        if self._state == PlaybackState.STOPPED:
            return

        if self._current_segment and not self._current_segment.is_gap and self._audio_output:
            clip = self._current_segment.clip
            if self._state == PlaybackState.PLAYING and self._should_play_clip_audio(clip):
                position_in_clip = self._position - self._current_segment.timeline_start
                self._audio_output.setVolume(self._get_effective_clip_volume_at_position(clip, position_in_clip))
            else:
                self._audio_output.setVolume(0.0)

        # Detached path uses timeline-position lookup.
        self._sync_detached_audio()
    
    def _on_timeline_finished(self):
        """Called when playback reaches the end of the timeline."""
        logger.info("Timeline playback finished")

        # Stop the master timer
        self._master_timer.stop()

        # Stop media player completely
        if self._media_player:
            self._media_player.stop()

        self._stop_detached_audio_player()

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
        self._last_detached_audio_clip_id = None
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
        self._last_detached_audio_clip_id = None
        logger.info("Timeline cleared")