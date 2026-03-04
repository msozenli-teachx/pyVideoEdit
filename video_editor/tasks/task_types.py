"""Task type definitions for the video editor task management system."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional
from datetime import datetime
import uuid


class TaskStatus(Enum):
    """Status of a task in the processing queue."""
    PENDING = auto()
    QUEUED = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TaskPriority(Enum):
    """Priority levels for task scheduling."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskType(Enum):
    """Types of media processing tasks."""
    CLIP = auto()
    CONVERT = auto()
    MERGE = auto()
    EXTRACT_AUDIO = auto()
    ADD_AUDIO = auto()
    RESIZE = auto()
    ROTATE = auto()
    CUSTOM = auto()


@dataclass
class TaskProgress:
    """Progress information for a task."""
    percent: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    current_time: float = 0.0  # seconds
    total_time: float = 0.0    # seconds
    message: str = ""
    
    @property
    def is_complete(self) -> bool:
        return self.percent >= 1.0


@dataclass
class TaskResult:
    """Result of a completed task."""
    success: bool
    task_id: str
    output_files: list[Path] = field(default_factory=list)
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0  # seconds


@dataclass
class Task:
    """Represents a media processing task.
    
    This is the core data structure for all operations in the task manager.
    """
    task_type: TaskType
    name: str
    input_files: list[Path]
    output_files: list[Path]
    priority: TaskPriority = TaskPriority.NORMAL
    parameters: dict[str, Any] = field(default_factory=dict)
    
    # Internal fields
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    progress: TaskProgress = field(default_factory=TaskProgress)
    result: Optional[TaskResult] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Callbacks
    _progress_callback: Optional[Callable[['Task'], None]] = field(default=None, repr=False)
    _completion_callback: Optional[Callable[['Task'], None]] = field(default=None, repr=False)
    
    def __post_init__(self):
        if isinstance(self.input_files, (str, Path)):
            self.input_files = [Path(self.input_files)]
        else:
            self.input_files = [Path(f) for f in self.input_files]
        
        if isinstance(self.output_files, (str, Path)):
            self.output_files = [Path(self.output_files)]
        else:
            self.output_files = [Path(f) for f in self.output_files]
    
    def update_progress(self, percent: float, message: str = "") -> None:
        """Update task progress and trigger callback."""
        self.progress.percent = min(max(percent, 0.0), 1.0)
        if message:
            self.progress.message = message
        
        if self._progress_callback:
            try:
                self._progress_callback(self)
            except Exception:
                pass
    
    def on_progress(self, callback: Callable[['Task'], None]) -> 'Task':
        """Register a progress callback."""
        self._progress_callback = callback
        return self
    
    def on_complete(self, callback: Callable[['Task'], None]) -> 'Task':
        """Register a completion callback."""
        self._completion_callback = callback
        return self
    
    def complete(self, result: TaskResult) -> None:
        """Mark task as complete with result."""
        self.result = result
        self.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
        self.completed_at = datetime.now()
        
        if self._completion_callback:
            try:
                self._completion_callback(self)
            except Exception:
                pass
    
    @property
    def processing_time(self) -> float:
        """Calculate processing time in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return 0.0
    
    def __lt__(self, other: 'Task') -> bool:
        """Compare tasks for priority queue ordering."""
        if not isinstance(other, Task):
            return NotImplemented
        # Higher priority value = higher priority in queue
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        # Earlier creation time = higher priority
        return self.created_at < other.created_at
    
    def __repr__(self) -> str:
        return f"Task({self.task_id}: {self.name} [{self.status.name}])"
