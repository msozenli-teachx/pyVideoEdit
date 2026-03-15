"""Backend service layer for the video editor.

This module provides a clean API between the UI and core processing logic,
enabling proper separation of concerns and making the UI easily testable.
"""

from pathlib import Path
from typing import Callable, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from video_editor.core.ffmpeg_engine import FFmpegEngine, ProgressInfo
from video_editor.core.media_processor import MediaProcessor, TimeRange
from video_editor.tasks.task_manager import FFmpegTaskManager
from video_editor.tasks.task_types import Task, TaskType, TaskPriority, TaskStatus, TaskResult
from video_editor.models.media import MediaFile, MediaType, MediaStatus, Clip
from video_editor.utils.logging_config import get_logger
from video_editor.config.settings import get_settings


logger = get_logger("editor_service")


@dataclass
class MediaInfo:
    """Simplified media info for UI consumption."""
    media_id: str
    name: str
    file_path: str
    duration: float
    duration_formatted: str
    resolution: str
    codec: str
    file_size_formatted: str
    thumbnail_path: Optional[str] = None


@dataclass
class TimelineClip:
    """Clip data for timeline display."""
    clip_id: str
    media_id: str
    name: str
    start_time: float  # Source start time (can be trimmed)
    end_time: float    # Source end time (can be trimmed)
    timeline_start: float
    duration: float
    color: str = "#00bcd4"
    file_path: str = ""  # Source file path for playback
    source_media_start: float = 0.0  # Original source media start (immutable)
    source_media_end: float = 0.0    # Original source media end (immutable)
    track_id: int = 0
    volume: float = 1.0
    muted: bool = False
    clip_type: str = "video"  # "video", "audio", "detached_audio"
    linked_clip_id: Optional[str] = None
    has_detached_audio: bool = False
    
    def __post_init__(self):
        """Initialize source media bounds if not set."""
        if self.source_media_start == 0.0 and self.source_media_end == 0.0:
            # First creation - set the original bounds
            self.source_media_start = self.start_time
            self.source_media_end = self.end_time

    @property
    def is_audio_only(self) -> bool:
        """Check if this clip is audio-only on the timeline."""
        return self.clip_type in ("audio", "detached_audio")

    def get_effective_volume(self) -> float:
        """Effective volume (mute-aware)."""
        return 0.0 if self.muted else self.volume


@dataclass
class TaskInfo:
    """Task information for UI display."""
    task_id: str
    name: str
    status: str
    progress: float
    message: str


@dataclass
class ProcessingProgress:
    """Real-time processing progress info."""
    process_id: str
    progress: float  # 0.0 to 1.0
    current_time: float  # seconds
    duration: float  # seconds
    bitrate: str
    speed: str
    time_formatted: str  # HH:MM:SS
    duration_formatted: str  # HH:MM:SS


class EditorService(QObject):
    """Main service class that bridges UI and backend processing.
    
    Signals:
        media_imported: Emitted when a media file is imported
        task_progress: Emitted when task progress updates
        task_completed: Emitted when a task completes
        timeline_updated: Emitted when timeline changes
        processing_progress: Emitted during FFmpeg processing with detailed info
    """
    
    # Signals for UI updates
    media_imported = pyqtSignal(object)  # MediaInfo
    media_removed = pyqtSignal(str)      # media_id
    task_progress = pyqtSignal(object)   # TaskInfo
    task_completed = pyqtSignal(object)  # TaskInfo
    timeline_updated = pyqtSignal()
    preview_frame_ready = pyqtSignal(object)  # QImage or frame data
    processing_progress = pyqtSignal(object)  # ProcessingProgress
    
    def __init__(self):
        super().__init__()
        
        self.settings = get_settings()
        
        # Initialize core components
        self._ffmpeg_engine = FFmpegEngine(max_workers=self.settings.max_concurrent_processes)
        self._media_processor = MediaProcessor(self._ffmpeg_engine)
        self._task_manager = FFmpegTaskManager(self._ffmpeg_engine, max_workers=4)
        
        # Media storage
        self._media_pool: dict[str, MediaFile] = {}
        self._timeline_clips: List[TimelineClip] = []
        self._current_project_path: Optional[Path] = None
        
        # Start task manager
        self._task_manager.start()
        self._setup_task_callbacks()
        
        logger.info("EditorService initialized")
    
    def _setup_task_callbacks(self):
        """Setup callbacks for task manager events."""
        self._task_manager.on_progress(self._on_task_progress)
        self._task_manager.on_complete(self._on_task_complete)
    
    def _on_task_progress(self, task: Task):
        """Handle task progress updates."""
        task_info = TaskInfo(
            task_id=task.task_id,
            name=task.name,
            status=task.status.name,
            progress=task.progress.percent,
            message=task.progress.message
        )
        self.task_progress.emit(task_info)
    
    def _on_task_complete(self, task: Task):
        """Handle task completion."""
        task_info = TaskInfo(
            task_id=task.task_id,
            name=task.name,
            status=task.status.name,
            progress=1.0 if task.result and task.result.success else 0.0,
            message=task.result.error_message if task.result and not task.result.success else "Completed"
        )
        self.task_completed.emit(task_info)
        
        # Update media status if applicable
        if task.result and task.result.success:
            for media in self._media_pool.values():
                if media.status == MediaStatus.PROCESSING:
                    media.status = MediaStatus.READY
    
    # Media Pool Operations
    def import_media(self, file_path: str) -> Optional[MediaInfo]:
        """Import a media file into the pool.
        
        Args:
            file_path: Path to the media file
            
        Returns:
            MediaInfo if successful, None otherwise
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        try:
            # Get media info
            info = self._media_processor.get_video_info(path)
            
            # Determine media type
            media_type = MediaType.VIDEO
            if path.suffix.lower() in ['.mp3', '.aac', '.wav', '.flac', '.m4a']:
                media_type = MediaType.AUDIO
            elif path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']:
                media_type = MediaType.IMAGE
            
            # Create media file object
            media_file = MediaFile(
                file_path=path,
                media_type=media_type,
                duration=info.get('duration', 0),
                width=info.get('streams', [{}])[0].get('width', 0) if info.get('streams') else 0,
                height=info.get('streams', [{}])[0].get('height', 0) if info.get('streams') else 0,
                fps=info.get('streams', [{}])[0].get('fps', 0) if info.get('streams') else 0,
                codec=info.get('streams', [{}])[0].get('codec_name', '') if info.get('streams') else '',
                bitrate=info.get('bitrate', 0),
                file_size=info.get('size', path.stat().st_size),
                status=MediaStatus.READY
            )
            
            self._media_pool[media_file.media_id] = media_file
            
            # Convert to MediaInfo for UI
            media_info = self._to_media_info(media_file)
            self.media_imported.emit(media_info)
            
            logger.info(f"Imported media: {media_file.name}")
            return media_info
            
        except Exception as e:
            logger.exception(f"Failed to import media: {file_path}")
            return None
    
    def remove_media(self, media_id: str) -> bool:
        """Remove a media file from the pool.
        
        Args:
            media_id: ID of the media to remove
            
        Returns:
            True if removed successfully
        """
        if media_id in self._media_pool:
            del self._media_pool[media_id]
            # Remove associated timeline clips
            self._timeline_clips = [c for c in self._timeline_clips if c.media_id != media_id]
            self.media_removed.emit(media_id)
            self.timeline_updated.emit()
            return True
        return False
    
    def get_media_list(self) -> List[MediaInfo]:
        """Get list of all imported media."""
        return [self._to_media_info(m) for m in self._media_pool.values()]
    
    def get_media(self, media_id: str) -> Optional[MediaInfo]:
        """Get specific media info."""
        media = self._media_pool.get(media_id)
        return self._to_media_info(media) if media else None
    
    def _to_media_info(self, media: MediaFile) -> MediaInfo:
        """Convert MediaFile to MediaInfo."""
        return MediaInfo(
            media_id=media.media_id,
            name=media.name,
            file_path=str(media.file_path),
            duration=media.duration,
            duration_formatted=media.formatted_duration,
            resolution=media.resolution,
            codec=media.codec,
            file_size_formatted=media.formatted_file_size,
            thumbnail_path=str(media.thumbnail_path) if media.thumbnail_path else None
        )
    
    # Timeline Operations
    def add_clip_to_timeline(self, media_id: str, start_time: float, end_time: float,
                             timeline_start: float = 0, track_id: int = 0) -> Optional[TimelineClip]:
        """Add a clip to the timeline.
        
        Args:
            media_id: ID of the media to clip
            start_time: Start time in source media
            end_time: End time in source media
            timeline_start: Position on timeline
            
        Returns:
            TimelineClip if successful
        """
        media = self._media_pool.get(media_id)
        if not media:
            return None
        
        clip = TimelineClip(
            clip_id=str(uuid.uuid4())[:8],
            media_id=media_id,
            name=f"{media.name} [{start_time:.1f}s - {end_time:.1f}s]",
            start_time=start_time,
            end_time=end_time,
            timeline_start=timeline_start,
            duration=end_time - start_time,
            file_path=str(media.file_path),
            source_media_start=start_time,
            source_media_end=end_time,
            track_id=track_id,
            clip_type=("audio" if media.media_type == MediaType.AUDIO else "video")
        )
        
        self._timeline_clips.append(clip)
        self.timeline_updated.emit()
        return clip
    
    def remove_clip_from_timeline(self, clip_id: str) -> bool:
        """Remove a clip from the timeline."""
        initial_len = len(self._timeline_clips)
        self._timeline_clips = [c for c in self._timeline_clips if c.clip_id != clip_id]
        if len(self._timeline_clips) < initial_len:
            self.timeline_updated.emit()
            return True
        return False
    
    def get_timeline_clips(self) -> List[TimelineClip]:
        """Get all clips on the timeline."""
        return self._timeline_clips.copy()
    
    def get_track_end_time(self, track_id: int = 0) -> float:
        """Get the end time of the last clip on a track.
        
        Args:
            track_id: The track ID to check
            
        Returns:
            The end time in seconds of the last clip, or 0 if no clips
        """
        max_end = 0.0
        for clip in self._timeline_clips:
            end = clip.timeline_start + clip.duration
            if end > max_end:
                max_end = end
        return max_end
    
    def find_gap_for_clip(self, clip_duration: float, track_id: int = 0) -> Optional[float]:
        """Find a gap that can fit a clip of the given duration.
        
        Searches for gaps between existing clips where the new clip would fit.
        
        Args:
            clip_duration: Duration of the clip to place
            track_id: Target track ID
            
        Returns:
            Timeline start position for the clip, or None if no suitable gap found
        """
        if not self._timeline_clips:
            return 0.0
        
        # Sort clips by timeline position
        sorted_clips = sorted(self._timeline_clips, key=lambda c: c.timeline_start)
        
        # Check for gap at the beginning
        first_clip = sorted_clips[0]
        if first_clip.timeline_start >= clip_duration:
            return 0.0
        
        # Check for gaps between clips
        for i in range(len(sorted_clips) - 1):
            current_clip = sorted_clips[i]
            next_clip = sorted_clips[i + 1]
            
            gap_start = current_clip.timeline_start + current_clip.duration
            gap_end = next_clip.timeline_start
            gap_duration = gap_end - gap_start
            
            if gap_duration >= clip_duration:
                return gap_start
        
        # No suitable gap found, place at end
        return None
    
    def add_clip_to_timeline_auto(self, media_id: str, start_time: float, end_time: float,
                                  track_id: int = 0) -> Optional[TimelineClip]:
        """Add a clip to the timeline, automatically positioning it.
        
        First tries to find a gap that can fit the clip. If no gap is found,
        places it at the end of the timeline.
        
        Args:
            media_id: ID of the media to clip
            start_time: Start time in source media
            end_time: End time in source media
            track_id: Target track ID (used for future track-specific logic)
            
        Returns:
            TimelineClip if successful
        """
        clip_duration = end_time - start_time
        
        # Try to find a gap that fits the clip
        gap_position = self.find_gap_for_clip(clip_duration, track_id)
        
        if gap_position is not None:
            # Found a gap, place clip there
            return self.add_clip_to_timeline(media_id, start_time, end_time, gap_position, track_id)
        else:
            # No gap found, place at end
            timeline_start = self.get_track_end_time(track_id)
            return self.add_clip_to_timeline(media_id, start_time, end_time, timeline_start, track_id)
    
    def get_track_clips(self, track_id: int = 0) -> List[TimelineClip]:
        """Get all clips for a specific track.
        
        Note: Currently returns all clips as track-specific storage
        is not yet implemented. Clips are sorted by timeline position.
        
        Args:
            track_id: The track ID
            
        Returns:
            List of clips on the track, sorted by timeline_start
        """
        # For now, return all clips sorted by position
        # In the future, this would filter by track_id
        return sorted(self._timeline_clips, key=lambda c: c.timeline_start)
    
    def move_clip(self, clip_id: str, new_timeline_start: float) -> bool:
        """Move a clip to a new position on the timeline.
        
        Args:
            clip_id: ID of the clip to move
            new_timeline_start: New start position on timeline in seconds
            
        Returns:
            True if clip was moved successfully
        """
        for clip in self._timeline_clips:
            if clip.clip_id == clip_id:
                clip.timeline_start = new_timeline_start
                self.timeline_updated.emit()
                return True
        return False

    def get_clip_by_id(self, clip_id: str) -> Optional[TimelineClip]:
        """Get a timeline clip by ID."""
        for clip in self._timeline_clips:
            if clip.clip_id == clip_id:
                return clip
        return None

    def _is_direct_audio_control_allowed(self, clip: TimelineClip) -> bool:
        """Only detached/audio clip is controllable once audio is detached."""
        if clip.has_detached_audio and not clip.is_audio_only:
            return False
        return True

    def set_clip_volume(self, clip_id: str, volume: float) -> bool:
        """Set clip volume (0.0 to 2.0) if clip is eligible for direct control."""
        clip = self.get_clip_by_id(clip_id)
        if not clip or not self._is_direct_audio_control_allowed(clip):
            return False
        clip.volume = max(0.0, min(2.0, volume))
        self.timeline_updated.emit()
        return True

    def set_clip_muted(self, clip_id: str, muted: bool) -> bool:
        """Set clip mute state if clip is eligible for direct control."""
        clip = self.get_clip_by_id(clip_id)
        if not clip or not self._is_direct_audio_control_allowed(clip):
            return False
        clip.muted = muted
        self.timeline_updated.emit()
        return True

    def toggle_clip_mute(self, clip_id: str) -> Optional[bool]:
        """Toggle clip mute state if clip is eligible for direct control."""
        clip = self.get_clip_by_id(clip_id)
        if not clip or not self._is_direct_audio_control_allowed(clip):
            return None
        clip.muted = not clip.muted
        self.timeline_updated.emit()
        return clip.muted

    def detach_audio_from_clip(self, clip_id: str) -> Optional[TimelineClip]:
        """Detach audio from a single video clip by creating an audio-only clip."""
        video_clip = self.get_clip_by_id(clip_id)
        if not video_clip or video_clip.is_audio_only or video_clip.has_detached_audio:
            return None

        audio_clip = TimelineClip(
            clip_id=str(uuid.uuid4())[:8],
            media_id=video_clip.media_id,
            name=f"{video_clip.name} [Audio]",
            start_time=video_clip.start_time,
            end_time=video_clip.end_time,
            timeline_start=video_clip.timeline_start,
            duration=video_clip.duration,
            color="#ff9800",
            file_path=video_clip.file_path,
            source_media_start=video_clip.source_media_start,
            source_media_end=video_clip.source_media_end,
            track_id=1,
            volume=video_clip.volume,
            muted=video_clip.muted,
            clip_type="detached_audio",
            linked_clip_id=video_clip.clip_id,
        )

        video_clip.has_detached_audio = True
        video_clip.muted = True
        self._timeline_clips.append(audio_clip)
        self.timeline_updated.emit()
        return audio_clip

    def detach_all_audio(self) -> List[TimelineClip]:
        """Detach audio for all eligible video clips on timeline."""
        targets = [c.clip_id for c in self._timeline_clips if not c.is_audio_only and not c.has_detached_audio]
        created: List[TimelineClip] = []
        for clip_id in targets:
            c = self.detach_audio_from_clip(clip_id)
            if c:
                created.append(c)
        return created

    def split_clip_at_position(self, clip_id: str, timeline_position: float) -> Optional[list[TimelineClip]]:
        """Split a clip at the given timeline position.

        Args:
            clip_id: ID of the clip to split
            timeline_position: Timeline position in seconds

        Returns:
            List of new clips [left_clip, right_clip] if split, otherwise None
        """
        clip = self.get_clip_by_id(clip_id)
        if not clip:
            return None

        clip_start = clip.timeline_start
        clip_end = clip.timeline_start + clip.duration

        # Ensure split position is within clip bounds (not on edges)
        if timeline_position <= clip_start + 0.01 or timeline_position >= clip_end - 0.01:
            return None

        # Calculate split point in source media
        offset_in_clip = timeline_position - clip.timeline_start
        split_source_time = clip.start_time + offset_in_clip

        if split_source_time <= clip.start_time + 0.01 or split_source_time >= clip.end_time - 0.01:
            return None

        # Create left clip - inherits source bounds from original clip
        left_clip = TimelineClip(
            clip_id=str(uuid.uuid4())[:8],
            media_id=clip.media_id,
            name=f"{clip.name} [L]",
            start_time=clip.start_time,
            end_time=split_source_time,
            timeline_start=clip.timeline_start,
            duration=split_source_time - clip.start_time,
            color=clip.color,
            file_path=clip.file_path,
            source_media_start=clip.source_media_start,
            source_media_end=clip.source_media_end,
            track_id=clip.track_id,
            volume=clip.volume,
            muted=clip.muted,
            clip_type=clip.clip_type,
            linked_clip_id=clip.linked_clip_id,
            has_detached_audio=clip.has_detached_audio,
        )
        self._update_clip_name(left_clip)

        # Create right clip - inherits source bounds from original clip
        right_clip = TimelineClip(
            clip_id=str(uuid.uuid4())[:8],
            media_id=clip.media_id,
            name=f"{clip.name} [R]",
            start_time=split_source_time,
            end_time=clip.end_time,
            timeline_start=timeline_position,
            duration=clip.end_time - split_source_time,
            color=clip.color,
            file_path=clip.file_path,
            source_media_start=clip.source_media_start,
            source_media_end=clip.source_media_end,
            track_id=clip.track_id,
            volume=clip.volume,
            muted=clip.muted,
            clip_type=clip.clip_type,
            linked_clip_id=clip.linked_clip_id,
            has_detached_audio=clip.has_detached_audio,
        )
        self._update_clip_name(right_clip)

        # Replace the old clip with the new ones
        self._timeline_clips = [c for c in self._timeline_clips if c.clip_id != clip_id]
        self._timeline_clips.extend([left_clip, right_clip])
        self.timeline_updated.emit()
        return [left_clip, right_clip]

    def trim_clip(self, clip_id: str, new_timeline_start: float, new_timeline_end: float) -> bool:
        """Trim a clip by setting new timeline start/end positions.

        Enforces that trimming cannot extend beyond the original source media bounds.

        Args:
            clip_id: ID of the clip to trim
            new_timeline_start: New start position on the timeline
            new_timeline_end: New end position on the timeline

        Returns:
            True if trimmed successfully
        """
        clip = self.get_clip_by_id(clip_id)
        if not clip:
            return False

        min_duration = 0.1
        if new_timeline_end - new_timeline_start < min_duration:
            return False

        # Calculate new source times based on timeline trim
        left_trim_delta = new_timeline_start - clip.timeline_start
        new_source_start = clip.start_time + left_trim_delta
        new_source_end = clip.start_time + (new_timeline_end - clip.timeline_start)

        # Enforce source media bounds - cannot extend beyond original source range
        if new_source_start < clip.source_media_start:
            new_source_start = clip.source_media_start
            new_timeline_start = clip.timeline_start + (new_source_start - clip.start_time)

        if new_source_end > clip.source_media_end:
            new_source_end = clip.source_media_end
            new_timeline_end = clip.timeline_start + (new_source_end - clip.start_time)

        # Validate the result
        if new_source_end <= new_source_start + min_duration:
            return False

        if new_timeline_end <= new_timeline_start + min_duration:
            return False

        clip.timeline_start = new_timeline_start
        clip.start_time = new_source_start
        clip.end_time = new_source_end
        clip.duration = new_source_end - new_source_start
        self._update_clip_name(clip)

        self.timeline_updated.emit()
        return True

    def _update_clip_name(self, clip: TimelineClip):
        """Update clip name to match current in/out times."""
        clip.name = f"{clip.name.split(' [', 1)[0]} [{clip.start_time:.1f}s - {clip.end_time:.1f}s]"
    
    # Processing Operations
    def create_clip(self, media_id: str, start_time: float, end_time: float, 
                    output_path: str, progress_callback: Optional[Callable] = None) -> Optional[str]:
        """Create a video clip from media.
        
        Args:
            media_id: Source media ID
            start_time: Start time in seconds
            end_time: End time in seconds
            output_path: Output file path
            progress_callback: Optional progress callback
            
        Returns:
            Task ID if submitted successfully
        """
        media = self._media_pool.get(media_id)
        if not media:
            logger.error(f"Media not found: {media_id}")
            return None
        
        try:
            time_range = TimeRange.from_seconds(start_time, end_time)
            
            task = Task(
                task_type=TaskType.CLIP,
                name=f"Clip {media.name}",
                input_files=[media.file_path],
                output_files=[Path(output_path)],
                priority=TaskPriority.NORMAL,
                parameters={
                    'ffmpeg_args': [
                        '-ss', time_range.to_ffmpeg_format()[0],
                        '-to', time_range.to_ffmpeg_format()[1],
                        '-c:v', 'copy',
                        '-c:a', 'copy',
                        '-avoid_negative_ts', 'make_zero'
                    ]
                }
            )
            
            task_id = self._task_manager.submit(task)
            logger.info(f"Clip task submitted: {task_id}")
            return task_id
            
        except Exception as e:
            logger.exception("Failed to create clip task")
            return None
    
    def convert_media(self, media_id: str, output_path: str, 
                      video_codec: str = "libx264", audio_codec: str = "aac") -> Optional[str]:
        """Convert media to different format.
        
        Args:
            media_id: Source media ID
            output_path: Output file path
            video_codec: Video codec
            audio_codec: Audio codec
            
        Returns:
            Task ID if submitted successfully
        """
        media = self._media_pool.get(media_id)
        if not media:
            return None
        
        task = Task(
            task_type=TaskType.CONVERT,
            name=f"Convert {media.name}",
            input_files=[media.file_path],
            output_files=[Path(output_path)],
            parameters={
                'ffmpeg_args': [
                    '-c:v', video_codec,
                    '-preset', 'medium',
                    '-crf', '23',
                    '-c:a', audio_codec,
                    '-b:a', '192k'
                ]
            }
        )
        
        return self._task_manager.submit(task)
    
    def extract_audio(self, media_id: str, output_path: str) -> Optional[str]:
        """Extract audio from video.
        
        Args:
            media_id: Source media ID
            output_path: Output file path
            
        Returns:
            Task ID if submitted successfully
        """
        media = self._media_pool.get(media_id)
        if not media:
            return None
        
        task = Task(
            task_type=TaskType.EXTRACT_AUDIO,
            name=f"Extract audio from {media.name}",
            input_files=[media.file_path],
            output_files=[Path(output_path)],
            parameters={
                'ffmpeg_args': [
                    '-vn',
                    '-c:a', 'aac',
                    '-b:a', '192k'
                ]
            }
        )
        
        return self._task_manager.submit(task)
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        return self._task_manager.cancel_task(task_id)
    
    def get_active_tasks(self) -> List[TaskInfo]:
        """Get list of active tasks."""
        return [
            TaskInfo(
                task_id=t.task_id,
                name=t.name,
                status=t.status.name,
                progress=t.progress.percent,
                message=t.progress.message
            )
            for t in self._task_manager.get_active_tasks()
        ]
    
    def process_clip_sync(
        self,
        media_id: str,
        start_time: float,
        end_time: float,
        output_path: str
    ) -> bool:
        """Process a clip synchronously with real-time progress updates.
        
        This method runs FFmpeg directly and emits processing_progress signals
        for real-time UI updates.
        
        Args:
            media_id: Source media ID
            start_time: Start time in seconds
            end_time: End time in seconds
            output_path: Output file path
            
        Returns:
            True if successful, False otherwise
        """
        media = self._media_pool.get(media_id)
        if not media:
            logger.error(f"Media not found: {media_id}")
            return False
        
        try:
            time_range = TimeRange.from_seconds(start_time, end_time)
            
            # Build FFmpeg args for lossless clipping
            ffmpeg_args = [
                '-ss', time_range.to_ffmpeg_format()[0],
                '-to', time_range.to_ffmpeg_format()[1],
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-avoid_negative_ts', 'make_zero'
            ]
            
            process_id = f"clip_{media_id}"
            
            def on_progress(percent: float):
                """Simple progress callback."""
                pass
            
            def on_progress_info(info):
                """Detailed progress callback."""
                progress = ProcessingProgress(
                    process_id=process_id,
                    progress=info.progress,
                    current_time=info.current_time,
                    duration=info.duration,
                    bitrate=info.bitrate,
                    speed=info.speed,
                    time_formatted=self._format_time(info.current_time),
                    duration_formatted=self._format_time(info.duration)
                )
                self.processing_progress.emit(progress)
            
            result = self._ffmpeg_engine.execute(
                process_id=process_id,
                input_file=media.file_path,
                output_file=output_path,
                ffmpeg_args=ffmpeg_args,
                progress_callback=on_progress,
                progress_info_callback=on_progress_info
            )
            
            if result.success:
                logger.info(f"Clip created successfully: {output_path}")
                return True
            else:
                logger.error(f"Clip failed: {result.error_message}")
                return False
                
        except Exception as e:
            logger.exception("Failed to process clip")
            return False
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    # Preview Operations
    def get_preview_frame(self, media_id: str, time_position: float):
        """Get a frame for preview at specified time.
        
        Args:
            media_id: Media ID
            time_position: Time in seconds
            
        Returns:
            Frame data or None
        """
        # Placeholder for frame extraction
        # Would extract frame using FFmpeg and return QImage
        pass
    
    # Timeline Playback Operations
    def get_timeline_duration(self) -> float:
        """Get the total duration of the timeline.
        
        Returns:
            Duration in seconds
        """
        if not self._timeline_clips:
            return 0.0
        
        max_end = 0.0
        for clip in self._timeline_clips:
            end = clip.timeline_start + clip.duration
            if end > max_end:
                max_end = end
        
        return max_end
    
    def get_sorted_timeline_clips(self) -> List[TimelineClip]:
        """Get timeline clips sorted by timeline_start position.
        
        Returns:
            List of TimelineClip sorted by position
        """
        return sorted(self._timeline_clips, key=lambda c: c.timeline_start)
    
    def get_segment_at_position(self, position: float) -> Optional[dict]:
        """Get the segment (clip or gap) at a timeline position.
        
        Args:
            position: Timeline position in seconds
            
        Returns:
            Dict with 'type' ('clip' or 'gap'), 'clip' (if applicable), 
            and 'duration' (for gaps)
        """
        sorted_clips = self.get_sorted_timeline_clips()
        
        if not sorted_clips:
            return None
        
        # Check for clip at position
        for clip in sorted_clips:
            clip_end = clip.timeline_start + clip.duration
            if clip.timeline_start <= position < clip_end:
                return {
                    'type': 'clip',
                    'clip': clip,
                    'offset_in_clip': position - clip.timeline_start
                }
        
        # Check for gap
        current_time = 0.0
        for clip in sorted_clips:
            if position < clip.timeline_start:
                # Position is in a gap before this clip
                return {
                    'type': 'gap',
                    'duration': clip.timeline_start - position,
                    'next_clip': clip
                }
            current_time = clip.timeline_start + clip.duration
        
        # Position is after all clips
        return None
    
    def shutdown(self):
        """Shutdown the service and cleanup resources."""
        logger.info("Shutting down EditorService")
        self._task_manager.stop(wait=True, timeout=10)
        self._media_processor.shutdown()
