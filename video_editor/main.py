"""Main entry point for the Video Editor application.

This module initializes the application, sets up logging,
and launches the PyQt6 GUI.
"""

import sys
import signal
from pathlib import Path

# Add the project root to path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from video_editor.gui.main_window import MainWindow
from video_editor.utils.logging_config import LoggingConfig
from video_editor.config.settings import get_settings


def setup_signal_handlers(app: QApplication):
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Main application entry point."""
    # Initialize settings
    settings = get_settings()
    
    # Setup logging
    logging_config = LoggingConfig(log_dir=settings.log_dir)
    logging_config.setup_logging(debug=False)
    
    import logging
    logger = logging.getLogger("main")
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    
    # Create Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    app.setApplicationVersion(settings.app_version)
    
    # Enable high DPI scaling
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # Setup signal handlers
    setup_signal_handlers(app)
    
    # Create and show main window
    try:
        window = MainWindow()
        window.show()
        logger.info("Main window displayed")
    except Exception as e:
        logger.exception("Failed to create main window")
        raise
    
    # Run application
    try:
        exit_code = app.exec()
    except Exception as e:
        logger.exception("Application error")
        exit_code = 1
    finally:
        logger.info(f"Application exiting with code {exit_code}")
        logging_config.shutdown()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
