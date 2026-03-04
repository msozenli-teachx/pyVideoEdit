"""Centralized task manager for concurrent media operations.

This module provides a robust task queue system with priority scheduling,
progress tracking, and proper resource management for video processing operations.
"""

import queue
import threading
import time
from collections import deque
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor, Future

from video_editor.tasks.task_types import (
    Task, TaskStatus, TaskPriority, TaskType, TaskResult
)
from video_editor.core.exceptions import TaskError
from video_editor.utils.logging_config import get_logger


logger = get_logger("task_manager")


class TaskManager:
    """Centralized manager for media processing tasks.
    
    Features:
    - Priority-based task scheduling
    - Concurrent task execution with configurable workers
    - Progress tracking and callbacks
    - Task cancellation and pause/resume
    - Event-driven architecture for UI integration
    """
    
    def __init__(self, max_workers: int = 4, queue_size: int = 100):
        """Initialize the task manager.
        
        Args:
            max_workers: Maximum number of concurrent tasks
            queue_size: Maximum size of the pending task queue
        """
        self._max_workers = max_workers
        self._queue_size = queue_size
        
        # Task storage
        self._task_queue: queue.PriorityQueue[tuple[int, Task]] = queue.PriorityQueue(maxsize=queue_size)
        self._active_tasks: dict[str, Task] = {}
        self._completed_tasks: deque[Task] = deque(maxlen=100)  # Keep last 100
        self._cancelled_tasks: set[str] = set()
        
        # Threading
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="task_worker_")
        self._lock = threading.RLock()
        self._shutdown_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._global_progress_callback: Optional[Callable[[Task], None]] = None
        self._global_complete_callback: Optional[Callable[[Task], None]] = None
        self._task_started_callback: Optional[Callable[[Task], None]] = None
        
        # Statistics
        self._stats = {
            'submitted': 0,
            'completed': 0,
            'failed': 0,
            'cancelled': 0
        }
        
        self._running = False
        
        logger.info(f"TaskManager initialized (max_workers={max_workers}, queue_size={queue_size})")
    
    def start(self) -> None:
        """Start the task manager scheduler."""
        if self._running:
            return
            
        self._running = True
        self._shutdown_event.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, name="task_scheduler")
        self._scheduler_thread.daemon = True
        self._scheduler_thread.start()
        
        logger.info("TaskManager scheduler started")
    
    def stop(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        """Stop the task manager.
        
        Args:
            wait: Whether to wait for active tasks to complete
            timeout: Maximum time to wait for shutdown
        """
        logger.info("Stopping TaskManager")
        self._running = False
        self._shutdown_event.set()
        
        # Cancel all queued tasks
        while not self._task_queue.empty():
            try:
                _, task = self._task_queue.get_nowait()
                task.status = TaskStatus.CANCELLED
                self._cancelled_tasks.add(task.task_id)
            except queue.Empty:
                break
        
        # Cancel active tasks
        with self._lock:
            for task in self._active_tasks.values():
                self._cancel_task_internal(task)
        
        if wait and self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=timeout)
        
        self._executor.shutdown(wait=wait)
        logger.info("TaskManager stopped")
    
    def _scheduler_loop(self) -> None:
        """Main scheduler loop that dispatches tasks to workers."""
        logger.debug("Scheduler loop started")
        
        while self._running and not self._shutdown_event.is_set():
            try:
                # Get next task with timeout to allow checking shutdown
                priority_tuple = self._task_queue.get(timeout=0.5)
                _, task = priority_tuple
                
                # Check if task was cancelled while in queue
                if task.task_id in self._cancelled_tasks:
                    task.status = TaskStatus.CANCELLED
                    self._stats['cancelled'] += 1
                    continue
                
                # Execute task in thread pool
                with self._lock:
                    self._active_tasks[task.task_id] = task
                
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                
                if self._task_started_callback:
                    try:
                        self._task_started_callback(task)
                    except Exception as e:
                        logger.warning(f"Task started callback error: {e}")
                
                # Submit to executor
                future = self._executor.submit(self._execute_task, task)
                future.add_done_callback(lambda f, t=task: self._task_completed(t, f))
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("Scheduler loop error")
        
        logger.debug("Scheduler loop ended")
    
    def _execute_task(self, task: Task) -> TaskResult:
        """Execute a task (to be overridden by subclasses or handlers).
        
        This is a placeholder that should be replaced with actual task execution logic.
        Subclasses can override this method or register task handlers.
        """
        logger.warning(f"No handler registered for task type {task.task_type}")
        return TaskResult(
            success=False,
            task_id=task.task_id,
            error_message=f"No handler for task type {task.task_type}"
        )
    
    def _task_completed(self, task: Task, future: Future) -> None:
        """Handle task completion."""
        try:
            result = future.result()
        except Exception as e:
            logger.exception(f"Task {task.task_id} raised exception")
            result = TaskResult(
                success=False,
                task_id=task.task_id,
                error_message=str(e)
            )
        
        # Update task state
        task.complete(result)
        
        # Update statistics
        if result.success:
            self._stats['completed'] += 1
        else:
            self._stats['failed'] += 1
        
        # Move to completed queue
        with self._lock:
            if task.task_id in self._active_tasks:
                del self._active_tasks[task.task_id]
            self._completed_tasks.append(task)
        
        # Global callback
        if self._global_complete_callback:
            try:
                self._global_complete_callback(task)
            except Exception as e:
                logger.warning(f"Global complete callback error: {e}")
        
        logger.info(f"Task {task.task_id} completed: success={result.success}")
    
    def submit(self, task: Task) -> str:
        """Submit a task to the processing queue.
        
        Args:
            task: The task to submit
            
        Returns:
            Task ID
            
        Raises:
            TaskError: If queue is full or task manager not running
        """
        if not self._running:
            raise TaskError("TaskManager is not running")
        
        # Set up progress callback chaining
        original_progress_callback = task._progress_callback
        
        def chained_progress_callback(t: Task) -> None:
            if original_progress_callback:
                original_progress_callback(t)
            if self._global_progress_callback:
                self._global_progress_callback(t)
        
        task._progress_callback = chained_progress_callback
        
        try:
            # Priority queue uses lowest value first, so we negate priority
            priority = -task.priority.value
            self._task_queue.put((priority, task), block=False)
            task.status = TaskStatus.QUEUED
            self._stats['submitted'] += 1
            
            logger.info(f"Task {task.task_id} submitted: {task.name}")
            return task.task_id
            
        except queue.Full:
            raise TaskError("Task queue is full")
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or active task.
        
        Args:
            task_id: ID of the task to cancel
            
        Returns:
            True if task was found and cancelled
        """
        # Check active tasks
        with self._lock:
            if task_id in self._active_tasks:
                task = self._active_tasks[task_id]
                self._cancel_task_internal(task)
                return True
        
        # Mark for cancellation if in queue
        self._cancelled_tasks.add(task_id)
        return task_id in self._cancelled_tasks
    
    def _cancel_task_internal(self, task: Task) -> None:
        """Internal method to cancel a task."""
        task.status = TaskStatus.CANCELLED
        self._cancelled_tasks.add(task.task_id)
        self._stats['cancelled'] += 1
        logger.info(f"Task {task.task_id} cancelled")
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self._lock:
            if task_id in self._active_tasks:
                return self._active_tasks[task_id]
            for task in self._completed_tasks:
                if task.task_id == task_id:
                    return task
        return None
    
    def get_active_tasks(self) -> list[Task]:
        """Get list of currently active tasks."""
        with self._lock:
            return list(self._active_tasks.values())
    
    def get_completed_tasks(self, limit: int = 10) -> list[Task]:
        """Get recently completed tasks."""
        with self._lock:
            return list(self._completed_tasks)[-limit:]
    
    def get_queue_size(self) -> int:
        """Get number of tasks in queue."""
        return self._task_queue.qsize()
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        return self._stats.copy()
    
    def on_progress(self, callback: Callable[[Task], None]) -> None:
        """Register a global progress callback for all tasks."""
        self._global_progress_callback = callback
    
    def on_complete(self, callback: Callable[[Task], None]) -> None:
        """Register a global completion callback for all tasks."""
        self._global_complete_callback = callback
    
    def on_task_started(self, callback: Callable[[Task], None]) -> None:
        """Register a callback for when tasks start."""
        self._task_started_callback = callback
    
    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """Wait for all tasks to complete.
        
        Args:
            timeout: Maximum time to wait (None = forever)
            
        Returns:
            True if all tasks completed, False if timeout
        """
        start_time = time.time()
        while True:
            with self._lock:
                if not self._active_tasks and self._task_queue.empty():
                    return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            time.sleep(0.1)


class FFmpegTaskManager(TaskManager):
    """Task manager specialized for FFmpeg operations.
    
    Integrates with FFmpegEngine to execute media processing tasks.
    """
    
    def __init__(self, ffmpeg_engine, max_workers: int = 4, queue_size: int = 100):
        """Initialize FFmpeg task manager.
        
        Args:
            ffmpeg_engine: FFmpegEngine instance for executing commands
            max_workers: Maximum concurrent tasks
            queue_size: Maximum pending tasks
        """
        super().__init__(max_workers=max_workers, queue_size=queue_size)
        self._ffmpeg_engine = ffmpeg_engine
        
        # Task type to handler mapping
        self._handlers: dict[TaskType, Callable[[Task], TaskResult]] = {}
    
    def register_handler(self, task_type: TaskType, handler: Callable[[Task], TaskResult]) -> None:
        """Register a handler for a specific task type."""
        self._handlers[task_type] = handler
        logger.debug(f"Registered handler for {task_type}")
    
    def _execute_task(self, task: Task) -> TaskResult:
        """Execute task using registered handler or FFmpeg engine."""
        # Use specific handler if registered
        if task.task_type in self._handlers:
            try:
                return self._handlers[task.task_type](task)
            except Exception as e:
                logger.exception(f"Handler error for task {task.task_id}")
                return TaskResult(
                    success=False,
                    task_id=task.task_id,
                    error_message=str(e)
                )
        
        # Default: execute FFmpeg command from task parameters
        if 'ffmpeg_args' in task.parameters:
            try:
                input_file = task.input_files[0]
                output_file = task.output_files[0]
                ffmpeg_args = task.parameters['ffmpeg_args']
                
                def progress_callback(percent: float) -> None:
                    task.update_progress(percent)
                
                result = self._ffmpeg_engine.execute(
                    task.task_id,
                    input_file,
                    output_file,
                    ffmpeg_args,
                    progress_callback
                )
                
                return TaskResult(
                    success=result.success,
                    task_id=task.task_id,
                    output_files=[result.output_file] if result.output_file else [],
                    error_message=result.error_message,
                    metadata={'return_code': result.return_code}
                )
            except Exception as e:
                logger.exception(f"FFmpeg execution error for task {task.task_id}")
                return TaskResult(
                    success=False,
                    task_id=task.task_id,
                    error_message=str(e)
                )
        
        return super()._execute_task(task)
