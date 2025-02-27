from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QFormLayout, QLabel, QComboBox, QSlider, 
                             QSpinBox, QDialogButtonBox, QFontComboBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Reader Settings")
        self.resize(400, 500)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Font Settings
        font_group = QGroupBox("Font Settings")
        font_layout = QFormLayout()
        
        # Font family
        self.font_combo = QFontComboBox()
        current_font = self.config.get("font_family")
        self.font_combo.setCurrentFont(QFont(current_font))
        font_layout.addRow("Font:", self.font_combo)
        
        # Font size
        self.size_spinner = QSpinBox()
        self.size_spinner.setRange(8, 36)
        self.size_spinner.setValue(self.config.get("font_size"))
        font_layout.addRow("Size:", self.size_spinner)
        
        # Line spacing
        self.line_spacing = QSlider(Qt.Horizontal)
        self.line_spacing.setRange(100, 300)
        self.line_spacing.setValue(int(self.config.get("line_spacing") * 100))
        self.line_spacing_label = QLabel(f"{self.config.get('line_spacing'):.1f}")
        self.line_spacing.valueChanged.connect(self.update_line_spacing_label)
        
        line_spacing_layout = QHBoxLayout()
        line_spacing_layout.addWidget(self.line_spacing)
        line_spacing_layout.addWidget(self.line_spacing_label)
        
        font_layout.addRow("Line Spacing:", line_spacing_layout)
        
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)
        
        # Theme Settings
        theme_group = QGroupBox("Display Settings")
        theme_layout = QFormLayout()
        
        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        
        current_theme = self.config.get("theme")
        self.theme_combo.setCurrentIndex(1 if current_theme == "dark" else 0)
        
        theme_layout.addRow("Theme:", self.theme_combo)
        
        # Contrast slider
        self.contrast_slider = QSlider(Qt.Horizontal)
        self.contrast_slider.setRange(50, 150)
        self.contrast_slider.setValue(self.config.get("contrast"))
        self.contrast_label = QLabel(f"{self.config.get('contrast')}%")
        self.contrast_slider.valueChanged.connect(self.update_contrast_label)
        
        contrast_layout = QHBoxLayout()
        contrast_layout.addWidget(self.contrast_slider)
        contrast_layout.addWidget(self.contrast_label)
        
        theme_layout.addRow("Contrast:", contrast_layout)
        
        # Color temperature slider
        self.color_temp_slider = QSlider(Qt.Horizontal)
        self.color_temp_slider.setRange(50, 150)
        self.color_temp_slider.setValue(self.config.get("color_temperature"))
        self.color_temp_label = QLabel(f"{self.config.get('color_temperature')}%")
        self.color_temp_slider.valueChanged.connect(self.update_color_temp_label)
        
        color_temp_layout = QHBoxLayout()
        color_temp_layout.addWidget(self.color_temp_slider)
        color_temp_layout.addWidget(self.color_temp_label)
        
        theme_layout.addRow("Color Temperature:", color_temp_layout)
        
        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
    
    def update_line_spacing_label(self, value):
        spacing = value / 100.0
        self.line_spacing_label.setText(f"{spacing:.1f}")
    
    def update_contrast_label(self, value):
        self.contrast_label.setText(f"{value}%")
    
    def update_color_temp_label(self, value):
        self.color_temp_label.setText(f"{value}%")
    
    def accept(self):
        # Save settings
        self.config.set("font_family", self.font_combo.currentFont().family())
        self.config.set("font_size", self.size_spinner.value())
        self.config.set("line_spacing", self.line_spacing.value() / 100.0)
        self.config.set("theme", self.theme_combo.currentData())
        self.config.set("contrast", self.contrast_slider.value())
        self.config.set("color_temperature", self.color_temp_slider.value())
        
        super().accept()