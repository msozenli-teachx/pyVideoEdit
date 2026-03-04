"""Data models for media files and projects."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional
import uuid


class MediaType(Enum):
    """Type of media file."""
    VIDEO = auto()
    AUDIO = auto()
    IMAGE = auto()


class MediaStatus(Enum):
    """Status of a media file in the project."""
    IMPORTED = auto()
    PROCESSING = auto()
    READY = auto()
    ERROR = auto()


@dataclass
class MediaFile:
    """Represents a media file in the project."""
    file_path: Path
    media_type: MediaType
    media_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    duration: float = 0.0  # seconds
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    bitrate: int = 0
    file_size: int = 0
    status: MediaStatus = MediaStatus.IMPORTED
    thumbnail_path: Optional[Path] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if not self.name:
            self.name = self.file_path.stem
    
    @property
    def resolution(self) -> str:
        """Get resolution as string (e.g., '1920x1080')."""
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "Unknown"
    
    @property
    def formatted_duration(self) -> str:
        """Get formatted duration string (HH:MM:SS)."""
        hours = int(self.duration // 3600)
        minutes = int((self.duration % 3600) // 60)
        seconds = int(self.duration % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    @property
    def formatted_file_size(self) -> str:
        """Get human-readable file size."""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


@dataclass
class Clip:
    """Represents a clip (segment) of a media file on the timeline."""
    media_file: MediaFile
    start_time: float  # Start time in source media (seconds)
    end_time: float    # End time in source media (seconds)
    timeline_start: float = 0.0  # Position on timeline (seconds)
    clip_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    
    def __post_init__(self):
        if not self.name:
            self.name = f"Clip {self.media_file.name}"
    
    @property
    def duration(self) -> float:
        """Get clip duration."""
        return self.end_time - self.start_time
    
    @property
    def timeline_end(self) -> float:
        """Get end position on timeline."""
        return self.timeline_start + self.duration
