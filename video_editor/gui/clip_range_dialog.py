"""Dialog for setting clip time ranges.

Provides input fields for start and end times with validation.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt
from typing import Optional, Tuple


class ClipRangeDialog(QDialog):
    """Dialog for setting clip start and end times.
    
    Attributes:
        start_time: Selected start time in seconds
        end_time: Selected end time in seconds
    """
    
    def __init__(self, parent=None, media_duration: float = 0.0, 
                 current_start: float = 0.0, current_end: Optional[float] = None):
        super().__init__(parent)
        
        self._media_duration = media_duration
        self.start_time = current_start
        self.end_time = current_end or media_duration
        
        self.setWindowTitle("Set Clip Range")
        self.setMinimumWidth(350)
        
        self._setup_ui()
        self._update_preview()
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Info label
        info_label = QLabel(f"Media Duration: {self._format_time(self._media_duration)}")
        info_label.setObjectName("timeLabel")
        layout.addWidget(info_label)
        
        # Time input group
        time_group = QGroupBox("Time Range")
        time_layout = QVBoxLayout(time_group)
        
        # Start time
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start Time:"))
        
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("00:00:00")
        self.start_input.setText(self._format_time(self.start_time))
        self.start_input.textChanged.connect(self._on_start_changed)
        start_layout.addWidget(self.start_input)
        
        time_layout.addLayout(start_layout)
        
        # End time
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("End Time:"))
        
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("00:00:00")
        self.end_input.setText(self._format_time(self.end_time))
        self.end_input.textChanged.connect(self._on_end_changed)
        end_layout.addWidget(self.end_input)
        
        time_layout.addLayout(end_layout)
        
        # Duration preview
        self.duration_label = QLabel("Duration: 00:00:00")
        self.duration_label.setObjectName("timeLabel")
        time_layout.addWidget(self.duration_label)
        
        layout.addWidget(time_group)
        
        # Quick set buttons
        quick_group = QGroupBox("Quick Set")
        quick_layout = QHBoxLayout(quick_group)
        
        set_start_btn = QPushButton("Set Start to Current")
        set_start_btn.clicked.connect(self._set_start_to_current)
        quick_layout.addWidget(set_start_btn)
        
        set_end_btn = QPushButton("Set End to Current")
        set_end_btn.clicked.connect(self._set_end_to_current)
        quick_layout.addWidget(set_end_btn)
        
        layout.addWidget(quick_group)
        
        # Presets
        preset_group = QGroupBox("Presets")
        preset_layout = QHBoxLayout(preset_group)
        
        full_clip_btn = QPushButton("Full Clip")
        full_clip_btn.clicked.connect(self._set_full_clip)
        preset_layout.addWidget(full_clip_btn)
        
        first_min_btn = QPushButton("First Minute")
        first_min_btn.clicked.connect(self._set_first_minute)
        preset_layout.addWidget(first_min_btn)
        
        last_min_btn = QPushButton("Last Minute")
        last_min_btn.clicked.connect(self._set_last_minute)
        preset_layout.addWidget(last_min_btn)
        
        layout.addWidget(preset_group)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.ok_btn = QPushButton("Apply")
        self.ok_btn.setObjectName("primaryButton")
        self.ok_btn.clicked.connect(self._on_ok)
        button_layout.addWidget(self.ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _on_start_changed(self, text: str):
        """Handle start time input change."""
        try:
            self.start_time = self._parse_time(text)
            self._update_preview()
        except ValueError:
            pass
    
    def _on_end_changed(self, text: str):
        """Handle end time input change."""
        try:
            self.end_time = self._parse_time(text)
            self._update_preview()
        except ValueError:
            pass
    
    def _update_preview(self):
        """Update the duration preview."""
        duration = max(0, self.end_time - self.start_time)
        self.duration_label.setText(f"Duration: {self._format_time(duration)}")
    
    def _set_start_to_current(self):
        """Set start time to current position (placeholder)."""
        # Would get current position from preview
        pass
    
    def _set_end_to_current(self):
        """Set end time to current position (placeholder)."""
        # Would get current position from preview
        pass
    
    def _set_full_clip(self):
        """Set range to full clip."""
        self.start_time = 0.0
        self.end_time = self._media_duration
        self.start_input.setText(self._format_time(self.start_time))
        self.end_input.setText(self._format_time(self.end_time))
    
    def _set_first_minute(self):
        """Set range to first minute."""
        self.start_time = 0.0
        self.end_time = min(60.0, self._media_duration)
        self.start_input.setText(self._format_time(self.start_time))
        self.end_input.setText(self._format_time(self.end_time))
    
    def _set_last_minute(self):
        """Set range to last minute."""
        self.end_time = self._media_duration
        self.start_time = max(0.0, self._media_duration - 60.0)
        self.start_input.setText(self._format_time(self.start_time))
        self.end_input.setText(self._format_time(self.end_time))
    
    def _on_ok(self):
        """Validate and accept."""
        try:
            start = self._parse_time(self.start_input.text())
            end = self._parse_time(self.end_input.text())
            
            if start < 0:
                QMessageBox.warning(self, "Invalid Time", "Start time cannot be negative.")
                return
            
            if end > self._media_duration:
                QMessageBox.warning(self, "Invalid Time", 
                    f"End time cannot exceed media duration ({self._format_time(self._media_duration)}).")
                return
            
            if end <= start:
                QMessageBox.warning(self, "Invalid Range", "End time must be greater than start time.")
                return
            
            self.start_time = start
            self.end_time = end
            self.accept()
            
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Format", f"Could not parse time: {e}")
    
    def _parse_time(self, time_str: str) -> float:
        """Parse time string to seconds.
        
        Supports formats:
        - HH:MM:SS
        - MM:SS
        - SS (seconds)
        """
        time_str = time_str.strip()
        
        parts = time_str.split(':')
        
        if len(parts) == 3:
            # HH:MM:SS
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            # MM:SS
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 1:
            # Seconds
            return float(parts[0])
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def get_time_range(self) -> Tuple[float, float]:
        """Get the selected time range.
        
        Returns:
            Tuple of (start_time, end_time) in seconds
        """
        return (self.start_time, self.end_time)
