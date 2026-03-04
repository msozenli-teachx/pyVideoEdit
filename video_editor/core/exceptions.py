"""Custom exceptions for the video editor application."""


class VideoEditorError(Exception):
    """Base exception for all video editor errors."""
    pass


class FFmpegError(VideoEditorError):
    """Exception raised for FFmpeg-related errors."""
    
    def __init__(self, message: str, command: str = "", return_code: int = 0, stderr: str = ""):
        super().__init__(message)
        self.command = command
        self.return_code = return_code
        self.stderr = stderr


class TaskError(VideoEditorError):
    """Exception raised for task management errors."""
    pass


class ValidationError(VideoEditorError):
    """Exception raised for input validation errors."""
    pass


class MediaError(VideoEditorError):
    """Exception raised for media file errors."""
    pass
