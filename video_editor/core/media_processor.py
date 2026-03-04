"""Media processor for video editing operations.

This module provides high-level video editing operations built on top
of the FFmpeg engine, including clipping, format conversion, and
other common editing tasks.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from video_editor.core.ffmpeg_engine import FFmpegEngine, FFmpegResult
from video_editor.core.exceptions import MediaError, ValidationError
from video_editor.utils.logging_config import get_logger


logger = get_logger("media_processor")


@dataclass
class TimeRange:
    """Represents a time range for video operations."""
    start: float  # seconds
    end: float    # seconds
    
    @classmethod
    def from_string(cls, time_str: str) -> 'TimeRange':
        """Parse time range from string formats like '00:01:30-00:02:45' or '90-165'."""
        if '-' in time_str:
            parts = time_str.split('-', 1)
            start = cls._parse_time(parts[0].strip())
            end = cls._parse_time(parts[1].strip())
            return cls(start=start, end=end)
        raise ValidationError(f"Invalid time range format: {time_str}")
    
    @classmethod
    def from_seconds(cls, start: float, end: float) -> 'TimeRange':
        """Create TimeRange from seconds."""
        return cls(start=start, end=end)
    
    @staticmethod
    def _parse_time(time_str: str) -> float:
        """Parse time string to seconds."""
        time_str = time_str.strip()
        
        # Try HH:MM:SS.ms format
        hms_match = re.match(r'(\d+):(\d{2}):(\d{2}(?:\.\d+)?)', time_str)
        if hms_match:
            hours, minutes, seconds = hms_match.groups()
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        
        # Try MM:SS.ms format
        ms_match = re.match(r'(\d+):(\d{2}(?:\.\d+)?)', time_str)
        if ms_match:
            minutes, seconds = ms_match.groups()
            return float(minutes) * 60 + float(seconds)
        
        # Try plain seconds
        try:
            return float(time_str)
        except ValueError:
            raise ValidationError(f"Invalid time format: {time_str}")
    
    def to_ffmpeg_format(self) -> tuple[str, str]:
        """Convert to FFmpeg -ss and -to format strings."""
        return (
            self._seconds_to_ffmpeg_time(self.start),
            self._seconds_to_ffmpeg_time(self.end)
        )
    
    @staticmethod
    def _seconds_to_ffmpeg_time(seconds: float) -> str:
        """Convert seconds to FFmpeg time format (HH:MM:SS.ms)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    
    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        return self.end - self.start
    
    def __post_init__(self):
        if self.start < 0:
            raise ValidationError("Start time cannot be negative")
        if self.end <= self.start:
            raise ValidationError("End time must be greater than start time")


@dataclass
class ClipOptions:
    """Options for video clipping operation."""
    time_range: TimeRange
    video_codec: str = "copy"  # "copy" or specific codec like "libx264"
    audio_codec: str = "copy"  # "copy" or specific codec like "aac"
    video_bitrate: Optional[str] = None
    audio_bitrate: Optional[str] = None
    fps: Optional[float] = None
    resolution: Optional[tuple[int, int]] = None  # (width, height)
    fast_seek: bool = True  # Use fast seek (less accurate but faster)


class MediaProcessor:
    """High-level media processing interface.
    
    Provides convenient methods for common video editing operations
    while abstracting FFmpeg command details.
    """
    
    def __init__(self, ffmpeg_engine: Optional[FFmpegEngine] = None):
        """Initialize media processor.
        
        Args:
            ffmpeg_engine: FFmpegEngine instance (creates default if None)
        """
        self._engine = ffmpeg_engine or FFmpegEngine()
        logger.info("MediaProcessor initialized")
    
    def clip_video(
        self,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        time_range: Union[TimeRange, str],
        options: Optional[ClipOptions] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> FFmpegResult:
        """Extract a clip from a video file.
        
        Args:
            input_file: Source video file
            output_file: Output clip file
            time_range: Time range to extract (TimeRange or string like "00:01:30-00:02:45")
            options: Clip options (uses defaults if None)
            progress_callback: Optional progress callback
            
        Returns:
            FFmpegResult with operation outcome
        """
        input_path = Path(input_file)
        output_path = Path(output_file)
        
        if not input_path.exists():
            raise MediaError(f"Input file not found: {input_path}")
        
        # Parse time range
        if isinstance(time_range, str):
            time_range = TimeRange.from_string(time_range)
        
        if options is None:
            options = ClipOptions(time_range=time_range)
        else:
            options.time_range = time_range
        
        # Build FFmpeg arguments
        ffmpeg_args = self._build_clip_args(options)
        
        process_id = f"clip_{input_path.stem}_{time_range.start:.1f}"
        
        logger.info(f"Clipping video: {input_path} [{time_range.start:.2f}s - {time_range.end:.2f}s]")
        
        return self._engine.execute(
            process_id=process_id,
            input_file=input_path,
            output_file=output_path,
            ffmpeg_args=ffmpeg_args,
            progress_callback=progress_callback
        )
    
    def _build_clip_args(self, options: ClipOptions) -> list[str]:
        """Build FFmpeg arguments for clipping."""
        args = []
        start_str, end_str = options.time_range.to_ffmpeg_format()
        
        # Seeking strategy: fast seek before input, accurate seek after
        if options.fast_seek:
            args.extend(["-ss", start_str])
        
        # Codecs
        args.extend(["-c:v", options.video_codec])
        args.extend(["-c:a", options.audio_codec])
        
        # Video options
        if options.video_bitrate:
            args.extend(["-b:v", options.video_bitrate])
        
        if options.fps:
            args.extend(["-r", str(options.fps)])
        
        if options.resolution:
            width, height = options.resolution
            args.extend(["-s", f"{width}x{height}"])
        
        # Audio options
        if options.audio_bitrate:
            args.extend(["-b:a", options.audio_bitrate])
        
        # Accurate seek position (after input)
        if not options.fast_seek:
            args.extend(["-ss", start_str])
        
        # End time
        args.extend(["-to", end_str])
        
        # Avoid re-encoding when possible for speed
        if options.video_codec == "copy" and options.audio_codec == "copy":
            args.extend(["-avoid_negative_ts", "make_zero"])
        
        return args
    
    def convert_format(
        self,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        video_bitrate: Optional[str] = None,
        audio_bitrate: Optional[str] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> FFmpegResult:
        """Convert video to a different format/codec.
        
        Args:
            input_file: Source video file
            output_file: Output file
            video_codec: Video codec to use
            audio_codec: Audio codec to use
            video_bitrate: Optional video bitrate (e.g., "5M")
            audio_bitrate: Optional audio bitrate (e.g., "192k")
            progress_callback: Optional progress callback
            
        Returns:
            FFmpegResult with operation outcome
        """
        input_path = Path(input_file)
        output_path = Path(output_file)
        
        if not input_path.exists():
            raise MediaError(f"Input file not found: {input_path}")
        
        args = ["-c:v", video_codec, "-c:a", audio_codec]
        
        if video_bitrate:
            args.extend(["-b:v", video_bitrate])
        if audio_bitrate:
            args.extend(["-b:a", audio_bitrate])
        
        # Common optimization flags for H.264
        if video_codec == "libx264":
            args.extend(["-preset", "medium", "-crf", "23"])
        
        process_id = f"convert_{input_path.stem}"
        
        logger.info(f"Converting video: {input_path} -> {output_path}")
        
        return self._engine.execute(
            process_id=process_id,
            input_file=input_path,
            output_file=output_path,
            ffmpeg_args=args,
            progress_callback=progress_callback
        )
    
    def extract_audio(
        self,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> FFmpegResult:
        """Extract audio track from video.
        
        Args:
            input_file: Source video file
            output_file: Output audio file
            audio_codec: Audio codec
            audio_bitrate: Audio bitrate
            progress_callback: Optional progress callback
            
        Returns:
            FFmpegResult with operation outcome
        """
        input_path = Path(input_file)
        
        if not input_path.exists():
            raise MediaError(f"Input file not found: {input_path}")
        
        args = ["-vn", "-c:a", audio_codec, "-b:a", audio_bitrate]
        
        process_id = f"extract_audio_{input_path.stem}"
        
        logger.info(f"Extracting audio: {input_path}")
        
        return self._engine.execute(
            process_id=process_id,
            input_file=input_path,
            output_file=output_file,
            ffmpeg_args=args,
            progress_callback=progress_callback
        )
    
    def get_video_info(self, input_file: Union[str, Path]) -> dict:
        """Get information about a video file using FFprobe.
        
        Args:
            input_file: Video file to analyze
            
        Returns:
            Dictionary with video metadata
        """
        import subprocess
        import json
        
        input_path = Path(input_file)
        if not input_path.exists():
            raise MediaError(f"Input file not found: {input_path}")
        
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_format",
                    "-show_streams",
                    "-of", "json",
                    str(input_path)
                ],
                capture_output=True,
                text=True,
                check=True
            )
            
            data = json.loads(result.stdout)
            
            # Extract key information
            info = {
                'filename': input_path.name,
                'format': data.get('format', {}).get('format_name', 'unknown'),
                'duration': float(data.get('format', {}).get('duration', 0)),
                'bitrate': int(data.get('format', {}).get('bit_rate', 0)),
                'size': int(data.get('format', {}).get('size', 0)),
                'streams': []
            }
            
            for stream in data.get('streams', []):
                stream_info = {
                    'index': stream.get('index'),
                    'codec_type': stream.get('codec_type'),
                    'codec_name': stream.get('codec_name'),
                }
                
                if stream.get('codec_type') == 'video':
                    stream_info.update({
                        'width': stream.get('width'),
                        'height': stream.get('height'),
                        'fps': eval(stream.get('r_frame_rate', '0/1')),  # e.g., "30000/1001"
                        'pixel_format': stream.get('pix_fmt')
                    })
                elif stream.get('codec_type') == 'audio':
                    stream_info.update({
                        'sample_rate': stream.get('sample_rate'),
                        'channels': stream.get('channels'),
                        'channel_layout': stream.get('channel_layout')
                    })
                
                info['streams'].append(stream_info)
            
            return info
            
        except subprocess.CalledProcessError as e:
            raise MediaError(f"FFprobe failed: {e.stderr}")
        except json.JSONDecodeError:
            raise MediaError("Failed to parse FFprobe output")
    
    def shutdown(self) -> None:
        """Shutdown the media processor and release resources."""
        logger.info("Shutting down MediaProcessor")
        self._engine.shutdown()
