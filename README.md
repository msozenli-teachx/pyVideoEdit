# Video Editor

A Python-based video editing application built with PyQt6 and FFmpeg.

## Architecture

This project follows a modular, layered architecture designed for scalability and extensibility:

```
video_editor/
├── core/                       # Core engine components
│   ├── ffmpeg_engine.py        # FFmpeg process management
│   ├── media_processor.py      # High-level media operations
│   └── exceptions.py           # Custom exceptions
├── tasks/                      # Task management system
│   ├── task_manager.py         # Centralized task queue
│   └── task_types.py           # Task definitions
├── utils/                      # Utilities
│   └── logging_config.py       # Logging configuration
├── models/                     # Data models
│   └── media.py                # Media file models
├── gui/                        # PyQt6 UI
│   └── main_window.py          # Main application window
├── config/                     # Configuration
│   └── settings.py             # App settings
└── main.py                     # Application entry point
```

## Features

### Core Engine
- **FFmpegEngine**: Manages FFmpeg subprocesses with support for:
  - Multiple concurrent processes
  - Progress monitoring via stderr parsing
  - Process cancellation
  - Both sync and async execution

### Task Management
- **TaskManager**: Centralized queue for media operations
  - Priority-based scheduling
  - Concurrent execution with configurable workers
  - Progress and completion callbacks
  - Task cancellation

### Media Processing
- **MediaProcessor**: High-level video operations
  - Video clipping with time range support
  - Format conversion
  - Audio extraction
  - Video information retrieval

### Logging
- Structured logging with rotation
- Separate log files for errors
- Colored console output
- Component-specific loggers

## Requirements

- Python 3.10+
- FFmpeg (must be installed and in PATH)
- PyQt6

## Installation

1. Install FFmpeg:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install ffmpeg

   # macOS
   brew install ffmpeg

   # Windows
   # Download from https://ffmpeg.org/download.html
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application:
```bash
python -m video_editor.main
```

Or directly:
```bash
python video_editor/main.py
```

## Extending the Application

### Adding New Task Types

1. Define a new task handler in `task_manager.py`:
```python
def my_custom_handler(task: Task) -> TaskResult:
    # Your processing logic
    return TaskResult(success=True, task_id=task.task_id)

# Register the handler
task_manager.register_handler(TaskType.CUSTOM, my_custom_handler)
```

### Adding New Media Operations

Extend `MediaProcessor` with new methods:
```python
def my_operation(self, input_file, output_file, **options):
    ffmpeg_args = [...]  # Build FFmpeg arguments
    return self._engine.execute(
        process_id="my_op",
        input_file=input_file,
        output_file=output_file,
        ffmpeg_args=ffmpeg_args
    )
```

## License

MIT License
