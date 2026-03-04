"""Dark theme stylesheet for the video editor application.

Modern dark theme with cyan/teal accents for a professional video editing look.
"""

DARK_THEME = """
/* Main Window */
QMainWindow {
    background-color: #1a1a1a;
    color: #e0e0e0;
}

/* Central Widget */
QWidget {
    background-color: #1a1a1a;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}

/* Buttons */
QPushButton {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 8px 16px;
    min-height: 28px;
}

QPushButton:hover {
    background-color: #3d3d3d;
    border-color: #00bcd4;
}

QPushButton:pressed {
    background-color: #00bcd4;
    color: #1a1a1a;
}

QPushButton:disabled {
    background-color: #252525;
    color: #666666;
    border-color: #333333;
}

QPushButton#primaryButton {
    background-color: #00bcd4;
    color: #1a1a1a;
    font-weight: bold;
    border: none;
}

QPushButton#primaryButton:hover {
    background-color: #00acc1;
}

QPushButton#primaryButton:pressed {
    background-color: #0097a7;
}

/* Line Edit */
QLineEdit {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: #00bcd4;
}

QLineEdit:focus {
    border-color: #00bcd4;
}

QLineEdit:disabled {
    background-color: #1f1f1f;
    color: #666666;
}

/* Text Edit */
QTextEdit {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px;
    selection-background-color: #00bcd4;
}

/* List Widget */
QListWidget {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    padding: 8px;
    border-radius: 3px;
    margin: 2px;
}

QListWidget::item:selected {
    background-color: #00bcd4;
    color: #1a1a1a;
}

QListWidget::item:hover {
    background-color: #3d3d3d;
}

QListWidget::item:selected:hover {
    background-color: #00acc1;
}

/* Tree Widget */
QTreeWidget {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px;
    outline: none;
}

QTreeWidget::item {
    padding: 6px;
    border-radius: 3px;
}

QTreeWidget::item:selected {
    background-color: #00bcd4;
    color: #1a1a1a;
}

QTreeWidget::item:hover {
    background-color: #3d3d3d;
}

QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #404040;
}

/* Progress Bar */
QProgressBar {
    background-color: #252525;
    border: 1px solid #404040;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
    height: 20px;
}

QProgressBar::chunk {
    background-color: #00bcd4;
    border-radius: 3px;
}

/* Slider */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #404040;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #00bcd4;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: #00acc1;
}

QSlider::sub-page:horizontal {
    background-color: #00bcd4;
    border-radius: 3px;
}

/* Labels */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

QLabel#sectionHeader {
    color: #00bcd4;
    font-weight: bold;
    font-size: 14px;
    padding: 8px 0;
}

QLabel#timeLabel {
    color: #888888;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12px;
}

/* Group Box */
QGroupBox {
    background-color: #252525;
    border: 1px solid #404040;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #00bcd4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
}

/* Splitter */
QSplitter::handle {
    background-color: #404040;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

QSplitter::handle:hover {
    background-color: #00bcd4;
}

/* Scroll Bar */
QScrollBar:vertical {
    background-color: #252525;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background-color: #404040;
    border-radius: 6px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #00bcd4;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #252525;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background-color: #404040;
    border-radius: 6px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #00bcd4;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Menu */
QMenuBar {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border-bottom: 1px solid #404040;
}

QMenuBar::item:selected {
    background-color: #00bcd4;
    color: #1a1a1a;
}

QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
}

QMenu::item:selected {
    background-color: #00bcd4;
    color: #1a1a1a;
}

/* Status Bar */
QStatusBar {
    background-color: #2d2d2d;
    color: #888888;
    border-top: 1px solid #404040;
}

/* Combo Box */
QComboBox {
    background-color: #252525;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px 10px;
    min-width: 80px;
}

QComboBox:hover {
    border-color: #00bcd4;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #e0e0e0;
}

QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    selection-background-color: #00bcd4;
}

/* Tab Widget */
QTabWidget::pane {
    background-color: #252525;
    border: 1px solid #404040;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #888888;
    padding: 10px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #00bcd4;
    color: #1a1a1a;
}

QTabBar::tab:hover:!selected {
    background-color: #3d3d3d;
    color: #e0e0e0;
}

/* Tool Button */
QToolButton {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px;
}

QToolButton:hover {
    background-color: #3d3d3d;
    border-color: #00bcd4;
}

QToolButton:pressed {
    background-color: #00bcd4;
    color: #1a1a1a;
}

/* Custom Widget Styles for Video Editor */

/* Preview Widget */
QWidget#previewWidget {
    background-color: #0d0d0d;
    border: 1px solid #404040;
    border-radius: 4px;
}

/* Timeline Widget */
QWidget#timelineWidget {
    background-color: #252525;
    border-top: 2px solid #404040;
}

/* Media Pool Widget */
QWidget#mediaPoolWidget {
    background-color: #252525;
    border-right: 2px solid #404040;
}

/* Transport Controls */
QWidget#transportControls {
    background-color: #2d2d2d;
    border-top: 1px solid #404040;
    padding: 8px;
}

/* Time Display */
QLCDNumber {
    background-color: #0d0d0d;
    color: #00bcd4;
    border: 1px solid #404040;
    border-radius: 4px;
}

/* Frame */
QFrame#separator {
    background-color: #404040;
}

QFrame#separator[orientation="horizontal"] {
    max-height: 2px;
}

QFrame#separator[orientation="vertical"] {
    max-width: 2px;
}
"""


def get_dark_theme() -> str:
    """Get the dark theme stylesheet."""
    return DARK_THEME
