"""Main application window using PyQt6 with modern dark theme.

Three-section layout:
- Left: Media Pool
- Center: Preview Area
- Bottom: Multi-track Timeline
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFileDialog, QMessageBox, QStatusBar, QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QCoreApplication
from pathlib import Path
from typing import Optional

from video_editor.services.editor_service import EditorService, MediaInfo, TaskInfo, ProcessingProgress
from video_editor.gui.styles import get_dark_theme
from video_editor.gui.media_pool_widget import MediaPoolWidget
from video_editor.gui.preview_widget import PreviewWidget
from video_editor.gui.timeline_widget import TimelineWidget
from video_editor.gui.clip_range_dialog import ClipRangeDialog
from video_editor.utils.logging_config import get_logger
from video_editor.config.settings import get_settings


logger = get_logger("gui.main_window")


class ProcessWorker(QThread):
    """Worker thread for processing clips."""
    
    finished = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(object)  # ProcessingProgress
    
    def __init__(self, editor_service: EditorService, media_id: str, 
                 start_time: float, end_time: float, output_path: str):
        super().__init__()
        self.editor_service = editor_service
        self.media_id = media_id
        self.start_time = start_time
        self.end_time = end_time
        self.output_path = output_path
    
    def run(self):
        """Run the processing in background thread."""
        try:
            # Connect progress signal
            self.editor_service.processing_progress.connect(self._on_progress)
            
            success = self.editor_service.process_clip_sync(
                self.media_id,
                self.start_time,
                self.end_time,
                self.output_path
            )
            
            if success:
                self.finished.emit(True, f"Clip saved to: {self.output_path}")
            else:
                self.finished.emit(False, "Processing failed. Check logs for details.")
                
        except Exception as e:
            logger.exception("Processing error")
            self.finished.emit(False, str(e))
    
    def _on_progress(self, progress: ProcessingProgress):
        """Forward progress updates."""
        self.progress.emit(progress)


class MainWindow(QMainWindow):
    """Main application window with three-section layout."""
    
    def __init__(self):
        super().__init__()
        
        self.settings = get_settings()
        self._editor_service = EditorService()
        
        # Current state
        self._current_media: Optional[MediaInfo] = None
        self._clip_start_time: float = 0.0
        self._clip_end_time: float = 0.0
        self._is_processing: bool = False
        self._process_worker: Optional[ProcessWorker] = None
        
        # Setup UI
        self.setWindowTitle(f"{self.settings.app_name} v{self.settings.app_version}")
        self.setGeometry(100, 100, 
                        self.settings.default_window_width, 
                        self.settings.default_window_height)
        
        self._setup_ui()
        self._connect_signals()
        self._apply_styles()
        
        logger.info("MainWindow initialized")
    
    def _setup_ui(self):
        """Setup the user interface."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main splitter (vertical: top area + timeline)
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(main_splitter)
        
        # Top area (horizontal: media pool + preview)
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        
        # Left: Media Pool
        self.media_pool = MediaPoolWidget()
        self.media_pool.setMinimumWidth(250)
        self.media_pool.setMaximumWidth(400)
        top_layout.addWidget(self.media_pool)
        
        # Center: Preview
        self.preview = PreviewWidget()
        top_layout.addWidget(self.preview, stretch=1)
        
        main_splitter.addWidget(top_widget)
        
        # Bottom: Timeline
        self.timeline = TimelineWidget()
        self.timeline.setMinimumHeight(200)
        self.timeline.setMaximumHeight(400)
        main_splitter.addWidget(self.timeline)
        
        # Set splitter proportions
        main_splitter.setSizes([600, 250])
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Progress info label
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("timeLabel")
        self.status_bar.addWidget(self.progress_label)
        
        # Progress bar in status bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        self.status_bar.showMessage("Ready")
    
    def _connect_signals(self):
        """Connect UI signals to slots."""
        # Media pool signals
        self.media_pool.import_requested.connect(self._on_import_media)
        self.media_pool.media_selected.connect(self._on_media_selected)
        self.media_pool.media_double_clicked.connect(self._on_media_double_clicked)
        self.media_pool.remove_requested.connect(self._on_remove_media)
        
        # Preview signals
        self.preview.time_input_requested.connect(self._on_set_clip_range)
        self.preview.position_changed.connect(self._on_preview_position_changed)
        self.preview.process_clicked.connect(self._on_process_clip)
        
        # Editor service signals
        self._editor_service.media_imported.connect(self._on_media_imported)
        self._editor_service.media_removed.connect(self._on_media_removed)
        self._editor_service.task_progress.connect(self._on_task_progress)
        self._editor_service.task_completed.connect(self._on_task_completed)
        self._editor_service.timeline_updated.connect(self._on_timeline_updated)
    
    def _apply_styles(self):
        """Apply dark theme stylesheet."""
        self.setStyleSheet(get_dark_theme())
    
    # Slot handlers
    def _on_import_media(self):
        """Handle import media request."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media Files",
            str(Path.home()),
            "Media Files (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.mp3 *.aac *.wav *.m4a);;All Files (*)"
        )
        
        for file_path in file_paths:
            media_info = self._editor_service.import_media(file_path)
            if media_info:
                self.status_bar.showMessage(f"Imported: {media_info.name}", 3000)
    
    def _on_media_imported(self, media_info: MediaInfo):
        """Handle media imported signal."""
        self.media_pool.add_media(media_info)
    
    def _on_media_selected(self, media_id: str):
        """Handle media selection."""
        media_info = self._editor_service.get_media(media_id)
        if media_info:
            self._current_media = media_info
            # Load the video into the player
            self.preview.load_video(
                media_info.file_path,
                media_info.name,
                media_info.duration
            )
            self._clip_start_time = 0.0
            self._clip_end_time = media_info.duration
            self.status_bar.showMessage(f"Selected: {media_info.name} ({media_info.resolution})")
    
    def _on_media_double_clicked(self, media_id: str):
        """Handle media double click."""
        self._on_media_selected(media_id)
        # Could auto-play or add to timeline
    
    def _on_remove_media(self, media_id: str):
        """Handle media removal."""
        if self._editor_service.remove_media(media_id):
            self.media_pool.remove_media(media_id)
            if self._current_media and self._current_media.media_id == media_id:
                self._current_media = None
                self.preview.clear_media()
    
    def _on_media_removed(self, media_id: str):
        """Handle media removed signal."""
        # Already handled in _on_remove_media
        pass
    
    def _on_set_clip_range(self):
        """Open dialog to set clip range."""
        if not self._current_media:
            QMessageBox.information(self, "No Media", "Please select a media file first.")
            return
        
        dialog = ClipRangeDialog(
            self,
            media_duration=self._current_media.duration,
            current_start=self._clip_start_time,
            current_end=self._clip_end_time
        )
        
        if dialog.exec() == ClipRangeDialog.DialogCode.Accepted:
            self._clip_start_time, self._clip_end_time = dialog.get_time_range()
            self.preview.set_start_time(self._clip_start_time)
            self.preview.set_end_time(self._clip_end_time)
            self.status_bar.showMessage(
                f"Clip range set: {self._format_time(self._clip_start_time)} - {self._format_time(self._clip_end_time)}",
                5000
            )
            
            # Add clip to timeline
            self._add_clip_to_timeline()
    
    def _on_process_clip(self):
        """Handle process clip button click."""
        if not self._current_media:
            QMessageBox.warning(self, "No Media", "Please select a media file first.")
            return
        
        if self._is_processing:
            QMessageBox.warning(self, "Processing", "A clip is already being processed.")
            return
        
        # Get times from preview widget
        start_time = self.preview.get_start_time()
        end_time = self.preview.get_end_time()
        
        # Validate times
        if start_time >= end_time:
            QMessageBox.warning(self, "Invalid Range", "Start time must be less than end time.")
            return
        
        if end_time > self._current_media.duration:
            QMessageBox.warning(self, "Invalid Range", 
                f"End time cannot exceed media duration ({self._format_time(self._current_media.duration)}).")
            return
        
        # Get output file
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Clip",
            str(Path(self._current_media.file_path).parent / 
                f"{Path(self._current_media.file_path).stem}_clip.mp4"),
            "MP4 Files (*.mp4);;All Files (*)"
        )
        
        if not output_path:
            return
        
        # Start processing
        self._start_processing(start_time, end_time, output_path)
    
    def _start_processing(self, start_time: float, end_time: float, output_path: str):
        """Start processing the clip."""
        self._is_processing = True
        self.preview.set_processing(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Initializing...")
        self.status_bar.showMessage("Processing clip...")
        
        # Create worker thread
        self._process_worker = ProcessWorker(
            self._editor_service,
            self._current_media.media_id,
            start_time,
            end_time,
            output_path
        )
        
        # Connect signals
        self._process_worker.progress.connect(self._on_processing_progress)
        self._process_worker.finished.connect(self._on_processing_finished)
        
        # Start processing
        self._process_worker.start()
    
    def _on_processing_progress(self, progress: ProcessingProgress):
        """Handle processing progress updates."""
        self.progress_bar.setValue(int(progress.progress * 100))
        self.progress_label.setText(
            f"{progress.time_formatted} / {progress.duration_formatted} | "
            f"Bitrate: {progress.bitrate} | Speed: {progress.speed}"
        )
    
    def _on_processing_finished(self, success: bool, message: str):
        """Handle processing completion."""
        self._is_processing = False
        self.preview.set_processing(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        
        if success:
            self.status_bar.showMessage("Clip created successfully!", 5000)
            QMessageBox.information(self, "Success", message)
        else:
            self.status_bar.showMessage("Processing failed.", 5000)
            QMessageBox.warning(self, "Error", f"Processing failed:\n{message}")
        
        # Clean up worker
        if self._process_worker:
            self._process_worker.deleteLater()
            self._process_worker = None
    
    def _add_clip_to_timeline(self):
        """Add current clip selection to timeline."""
        if not self._current_media:
            return
        
        clip = self._editor_service.add_clip_to_timeline(
            self._current_media.media_id,
            self._clip_start_time,
            self._clip_end_time,
            timeline_start=0  # Could calculate based on existing clips
        )
        
        if clip:
            self.timeline.add_clip_to_track(0, clip)
            self.status_bar.showMessage(f"Added clip to timeline: {clip.name}")
    
    def _on_preview_position_changed(self, position: float):
        """Handle preview position change."""
        self.timeline.set_playhead_position(position)
    
    def _on_timeline_updated(self):
        """Handle timeline updates."""
        # Refresh timeline display
        pass
    
    def _on_task_progress(self, task_info: TaskInfo):
        """Handle task progress updates."""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(int(task_info.progress * 100))
        self.status_bar.showMessage(f"{task_info.name}: {task_info.progress*100:.0f}%")
    
    def _on_task_completed(self, task_info: TaskInfo):
        """Handle task completion."""
        self.progress_bar.setVisible(False)
        
        if task_info.progress >= 1.0:
            self.status_bar.showMessage(f"Task completed: {task_info.name}", 5000)
            QMessageBox.information(self, "Success", f"Operation completed successfully!\n\n{task_info.name}")
        else:
            self.status_bar.showMessage(f"Task failed: {task_info.name}", 5000)
            QMessageBox.warning(self, "Failed", f"Operation failed:\n{task_info.message}")
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def closeEvent(self, event):
        """Handle window close event."""
        logger.info("MainWindow closing")
        
        # Wait for processing to complete
        if self._is_processing and self._process_worker:
            self._process_worker.wait(5000)  # Wait up to 5 seconds
        
        self._editor_service.shutdown()
        event.accept()
