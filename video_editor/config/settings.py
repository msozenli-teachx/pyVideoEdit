"""Application settings and configuration."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AppSettings:
    """Application settings."""
    
    # Application info
    app_name: str = "Video Editor"
    app_version: str = "0.1.0"
    
    # Paths
    config_dir: Path = Path.home() / ".video_editor"
    log_dir: Path = Path.home() / ".video_editor" / "logs"
    temp_dir: Path = Path.home() / ".video_editor" / "temp"
    
    # FFmpeg settings
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None
    max_concurrent_processes: int = 4
    
    # Task manager settings
    max_queue_size: int = 100
    task_timeout: float = 3600.0  # 1 hour
    
    # UI settings
    default_window_width: int = 1400
    default_window_height: int = 900
    
    # Logging
    log_level: str = "INFO"
    log_to_file: bool = True
    log_rotation: bool = True
    
    def __post_init__(self):
        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Override from environment variables if set
        if os.getenv('FFMPEG_PATH'):
            self.ffmpeg_path = os.getenv('FFMPEG_PATH')
        if os.getenv('FFPROBE_PATH'):
            self.ffprobe_path = os.getenv('FFPROBE_PATH')
    
    @property
    def database_path(self) -> Path:
        """Get path to application database."""
        return self.config_dir / "projects.db"


# Global settings instance
_settings: Optional[AppSettings] = None


def get_settings() -> AppSettings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings


def set_settings(settings: AppSettings) -> None:
    """Set the global settings instance."""
    global _settings
    _settings = settings
