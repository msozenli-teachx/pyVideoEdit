"""Logging configuration for the video editor application.

Provides structured logging with rotation, multiple handlers,
and component-specific loggers.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record: logging.LogRecord) -> str:
        # Add color to levelname for console output
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


class LoggingConfig:
    """Centralized logging configuration manager."""
    
    DEFAULT_FORMAT = "%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s"
    DETAILED_FORMAT = (
        "%(asctime)s | %(name)-20s | %(levelname)-8s | "
        "%(filename)s:%(lineno)d | %(funcName)s() | %(message)s"
    )
    
    _instance: Optional['LoggingConfig'] = None
    _initialized: bool = False
    _pending_log_dir: Optional[Path] = None
    _pending_level: int = logging.DEBUG
    
    def __new__(cls, log_dir: Optional[Path] = None, level: int = logging.DEBUG) -> 'LoggingConfig':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        # Store arguments for __init__
        cls._pending_log_dir = log_dir
        cls._pending_level = level
        return cls._instance
    
    def __init__(self, log_dir: Optional[Path] = None, level: int = logging.DEBUG):
        if LoggingConfig._initialized:
            return
            
        # Use stored arguments if they were passed via __new__
        actual_log_dir = self._pending_log_dir if self._pending_log_dir is not None else log_dir
        actual_level = self._pending_level if self.__class__._pending_log_dir is not None else level
        
        self.log_dir = actual_log_dir or Path.home() / ".video_editor" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = actual_level
        self._handlers: list[logging.Handler] = []
        
        LoggingConfig._initialized = True
    
    def setup_logging(self, debug: bool = False) -> None:
        """Configure root logging for the application."""
        format_str = self.DETAILED_FORMAT if debug else self.DEFAULT_FORMAT
        
        # Root logger configuration
        root_logger = logging.getLogger()
        root_logger.setLevel(self.level)
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        console_formatter = ColoredFormatter(format_str)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        self._handlers.append(console_handler)
        
        # File handler with rotation
        log_file = self.log_dir / f"video_editor_{datetime.now():%Y%m%d}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10_000_000,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(self.DETAILED_FORMAT)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        self._handlers.append(file_handler)
        
        # Error file handler (errors only)
        error_log_file = self.log_dir / f"errors_{datetime.now():%Y%m%d}.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=5_000_000,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        root_logger.addHandler(error_handler)
        self._handlers.append(error_handler)
        
        logging.info("Logging system initialized")
        logging.debug(f"Log directory: {self.log_dir}")
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger for a specific component."""
        return logging.getLogger(name)
    
    def shutdown(self) -> None:
        """Clean up logging handlers."""
        root_logger = logging.getLogger()
        for handler in self._handlers:
            handler.close()
            root_logger.removeHandler(handler)
        self._handlers.clear()
        logging.shutdown()


# Convenience function
def get_logger(name: str) -> logging.Logger:
    """Get a logger for the specified component name."""
    return logging.getLogger(name)
