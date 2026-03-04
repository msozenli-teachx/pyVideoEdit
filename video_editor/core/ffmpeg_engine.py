"""FFmpeg engine for managing video processing operations.

This module provides a robust interface for executing FFmpeg commands
with support for concurrent operations, progress monitoring, and
proper process lifecycle management.
"""

import asyncio
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, Union
from concurrent.futures import ThreadPoolExecutor
import threading

from video_editor.core.exceptions import FFmpegError
from video_editor.utils.logging_config import get_logger


logger = get_logger("ffmpeg_engine")


class ProcessStatus(Enum):
    """Status of an FFmpeg process."""
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class FFmpegProcess:
    """Represents an FFmpeg process with its metadata and state."""
    process_id: str
    command: list[str]
    input_file: Path
    output_file: Path
    status: ProcessStatus = ProcessStatus.PENDING
    progress: float = 0.0
    duration_seconds: float = 0.0
    current_time: float = 0.0
    bitrate: str = ""
    speed: str = ""
    error_message: str = ""
    _subprocess: Optional[subprocess.Popen] = field(default=None, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    
    def cancel(self) -> None:
        """Request cancellation of this process."""
        self._cancel_event.set()
        if self._subprocess and self._subprocess.poll() is None:
            self._subprocess.terminate()
            logger.info(f"Process {self.process_id} cancellation requested")
    
    @property
    def is_cancelled(self) -> bool:
        """Check if process has been cancelled."""
        return self._cancel_event.is_set()


@dataclass
class ProgressInfo:
    """Real-time progress information from FFmpeg."""
    process_id: str
    progress: float  # 0.0 to 1.0
    current_time: float  # seconds
    duration: float  # seconds
    bitrate: str  # e.g., "2500kbits/s"
    speed: str  # e.g., "2.5x"
    frame: int = 0
    fps: float = 0.0


@dataclass
class FFmpegResult:
    """Result of an FFmpeg operation."""
    success: bool
    process_id: str
    output_file: Optional[Path] = None
    error_message: str = ""
    return_code: int = 0
    stderr: str = ""


class FFmpegEngine:
    """Core engine for managing FFmpeg processes.
    
    This class provides a scalable interface for executing FFmpeg commands
    with support for multiple concurrent processes, progress callbacks,
    and proper resource management.
    """
    
    # FFmpeg output patterns for progress parsing
    DURATION_PATTERN = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})")
    PROGRESS_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
    BITRATE_PATTERN = re.compile(r"bitrate=\s*([\d.]+[kM]?bits/s)")
    SPEED_PATTERN = re.compile(r"speed=\s*([\d.]+x)")
    FRAME_PATTERN = re.compile(r"frame=\s*(\d+)")
    FPS_PATTERN = re.compile(r"fps=\s*([\d.]+)")
    
    def __init__(self, max_workers: int = 4, ffmpeg_path: Optional[str] = None):
        """Initialize the FFmpeg engine.
        
        Args:
            max_workers: Maximum number of concurrent FFmpeg processes
            ffmpeg_path: Path to FFmpeg executable (auto-detected if None)
        """
        self._ffmpeg_path = ffmpeg_path or self._detect_ffmpeg()
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ffmpeg_")
        self._active_processes: dict[str, FFmpegProcess] = {}
        self._lock = threading.RLock()
        
        logger.info(f"FFmpegEngine initialized (max_workers={max_workers}, ffmpeg={self._ffmpeg_path})")
    
    def _detect_ffmpeg(self) -> str:
        """Detect FFmpeg installation."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise FFmpegError("FFmpeg not found. Please install FFmpeg and ensure it's in PATH.")
        return ffmpeg_path
    
    def _parse_duration(self, line: str) -> float:
        """Parse duration from FFmpeg output."""
        match = self.DURATION_PATTERN.search(line)
        if match:
            hours, minutes, seconds = match.groups()
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        return 0.0
    
    def _parse_progress(self, line: str) -> float:
        """Parse current time from FFmpeg output."""
        match = self.PROGRESS_PATTERN.search(line)
        if match:
            hours, minutes, seconds = match.groups()
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        return 0.0
    
    def _parse_bitrate(self, line: str) -> str:
        """Parse bitrate from FFmpeg output."""
        match = self.BITRATE_PATTERN.search(line)
        if match:
            return match.group(1)
        return ""
    
    def _parse_speed(self, line: str) -> str:
        """Parse speed from FFmpeg output."""
        match = self.SPEED_PATTERN.search(line)
        if match:
            return match.group(1)
        return ""
    
    def _parse_frame(self, line: str) -> int:
        """Parse frame number from FFmpeg output."""
        match = self.FRAME_PATTERN.search(line)
        if match:
            return int(match.group(1))
        return 0
    
    def _parse_fps(self, line: str) -> float:
        """Parse FPS from FFmpeg output."""
        match = self.FPS_PATTERN.search(line)
        if match:
            return float(match.group(1))
        return 0.0
    
    def _run_process(
        self,
        process: FFmpegProcess,
        progress_callback: Optional[Callable[[float], None]] = None,
        progress_info_callback: Optional[Callable[[ProgressInfo], None]] = None
    ) -> FFmpegResult:
        """Execute an FFmpeg process and monitor its progress.
        
        Args:
            process: The FFmpegProcess to execute
            progress_callback: Optional callback for progress updates (0.0 - 1.0)
            progress_info_callback: Optional callback for detailed progress info
            
        Returns:
            FFmpegResult with operation outcome
        """
        process_id = process.process_id
        
        try:
            with self._lock:
                self._active_processes[process_id] = process
            
            process.status = ProcessStatus.RUNNING
            logger.info(f"Starting FFmpeg process {process_id}: {' '.join(process.command)}")
            
            # Start subprocess
            process._subprocess = subprocess.Popen(
                process.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # Monitor stderr for progress
            stderr_lines = []
            if process._subprocess.stderr:
                for line in process._subprocess.stderr:
                    if process.is_cancelled:
                        break
                        
                    stderr_lines.append(line)
                    
                    # Parse duration on first occurrence
                    if process.duration_seconds == 0:
                        process.duration_seconds = self._parse_duration(line)
                    
                    # Parse progress information
                    if process.duration_seconds > 0:
                        process.current_time = self._parse_progress(line)
                        process.progress = min(process.current_time / process.duration_seconds, 1.0)
                    
                    # Parse bitrate and speed
                    bitrate = self._parse_bitrate(line)
                    if bitrate:
                        process.bitrate = bitrate
                    
                    speed = self._parse_speed(line)
                    if speed:
                        process.speed = speed
                    
                    # Call progress callbacks
                    if progress_callback:
                        try:
                            progress_callback(process.progress)
                        except Exception as e:
                            logger.warning(f"Progress callback error: {e}")
                    
                    if progress_info_callback and process.duration_seconds > 0:
                        try:
                            info = ProgressInfo(
                                process_id=process_id,
                                progress=process.progress,
                                current_time=process.current_time,
                                duration=process.duration_seconds,
                                bitrate=process.bitrate,
                                speed=process.speed,
                                frame=self._parse_frame(line),
                                fps=self._parse_fps(line)
                            )
                            progress_info_callback(info)
                        except Exception as e:
                            logger.warning(f"Progress info callback error: {e}")
            
            # Wait for completion or cancellation
            if process.is_cancelled:
                process._subprocess.kill()
                process.status = ProcessStatus.CANCELLED
                logger.info(f"Process {process_id} was cancelled")
                return FFmpegResult(
                    success=False,
                    process_id=process_id,
                    error_message="Process was cancelled"
                )
            
            return_code = process._subprocess.wait()
            stderr_output = "".join(stderr_lines)
            
            if return_code == 0:
                process.status = ProcessStatus.COMPLETED
                process.progress = 1.0
                logger.info(f"Process {process_id} completed successfully")
                return FFmpegResult(
                    success=True,
                    process_id=process_id,
                    output_file=process.output_file
                )
            else:
                process.status = ProcessStatus.FAILED
                process.error_message = stderr_output[-1000:]  # Last 1000 chars
                logger.error(f"Process {process_id} failed with code {return_code}")
                return FFmpegResult(
                    success=False,
                    process_id=process_id,
                    error_message=f"FFmpeg exited with code {return_code}",
                    return_code=return_code,
                    stderr=stderr_output
                )
                
        except Exception as e:
            process.status = ProcessStatus.FAILED
            logger.exception(f"Process {process_id} encountered an error")
            return FFmpegResult(
                success=False,
                process_id=process_id,
                error_message=str(e)
            )
        finally:
            with self._lock:
                if process_id in self._active_processes:
                    del self._active_processes[process_id]
    
    def execute(
        self,
        process_id: str,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        ffmpeg_args: list[str],
        progress_callback: Optional[Callable[[float], None]] = None,
        progress_info_callback: Optional[Callable[['ProgressInfo'], None]] = None
    ) -> FFmpegResult:
        """Execute an FFmpeg command synchronously.
        
        Args:
            process_id: Unique identifier for this process
            input_file: Input media file path
            output_file: Output media file path
            ffmpeg_args: Additional FFmpeg arguments
            progress_callback: Optional progress callback (0.0 - 1.0)
            progress_info_callback: Optional callback for detailed progress info
            
        Returns:
            FFmpegResult with operation outcome
        """
        input_path = Path(input_file)
        output_path = Path(output_file)
        
        if not input_path.exists():
            raise FFmpegError(f"Input file not found: {input_path}")
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build command
        command = [self._ffmpeg_path, "-y", "-i", str(input_path)]
        command.extend(ffmpeg_args)
        command.append(str(output_path))
        
        process = FFmpegProcess(
            process_id=process_id,
            command=command,
            input_file=input_path,
            output_file=output_path
        )
        
        return self._run_process(process, progress_callback, progress_info_callback)
    
    def execute_async(
        self,
        process_id: str,
        input_file: Union[str, Path],
        output_file: Union[str, Path],
        ffmpeg_args: list[str],
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> asyncio.Future:
        """Execute an FFmpeg command asynchronously.
        
        Args:
            process_id: Unique identifier for this process
            input_file: Input media file path
            output_file: Output media file path
            ffmpeg_args: Additional FFmpeg arguments
            progress_callback: Optional progress callback
            
        Returns:
            Future that resolves to FFmpegResult
        """
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(
            self._executor,
            self.execute,
            process_id,
            input_file,
            output_file,
            ffmpeg_args,
            progress_callback
        )
    
    def cancel_process(self, process_id: str) -> bool:
        """Cancel a running process.
        
        Args:
            process_id: ID of the process to cancel
            
        Returns:
            True if process was found and cancelled, False otherwise
        """
        with self._lock:
            if process_id in self._active_processes:
                self._active_processes[process_id].cancel()
                return True
        return False
    
    def get_active_processes(self) -> list[FFmpegProcess]:
        """Get list of currently active processes."""
        with self._lock:
            return list(self._active_processes.values())
    
    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the engine and clean up resources.
        
        Args:
            wait: Whether to wait for active processes to complete
        """
        logger.info("Shutting down FFmpegEngine")
        
        # Cancel all active processes
        with self._lock:
            for process in self._active_processes.values():
                process.cancel()
        
        self._executor.shutdown(wait=wait)
        logger.info("FFmpegEngine shutdown complete")
