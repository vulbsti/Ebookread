import os
import logging
import traceback
from PyQt5.QtWidgets import (QMainWindow, QAction, QFileDialog, QToolBar, 
                            QDockWidget, QVBoxLayout, QWidget, QListWidget, 
                            QListWidgetItem, QLabel, QSplitter, QHBoxLayout,
                            QPushButton, QMenu, QDialog, QComboBox, QSlider,
                            QCheckBox, QGroupBox, QFormLayout, QSpinBox,
                            QTabWidget, QSizePolicy, QMessageBox)
from PyQt5.QtGui import QIcon, QFont, QColor, QPixmap
from PyQt5.QtCore import Qt, QSize

logger = logging.getLogger("epubread.main_window")

from epubread.ui.reader_view import ReaderView
from epubread.readers.reader_factory import ReaderFactory
from epubread.ui.settings_dialog import SettingsDialog
from epubread.ui.library_view import LibraryView


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.current_book = None
        self.reader_view = None
        
        self.setWindowTitle("EPUBRead")
        self.setMinimumSize(800, 600)
        
        self.init_ui()
        
        # Try to restore last open book if any
        recent_books = self.config.get_recent_books()
        if recent_books:
            try:
                self.open_book(recent_books[0])
            except Exception as e:
                print(f"Error opening last book: {e}")
    
    def init_ui(self):
        # Central widget with reader view
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_layout = QVBoxLayout(self.central_widget)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create navigation dock
        self.create_toc_dock()
        
        # Create reader view placeholder
        self.placeholder = QLabel("Open a book to start reading")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.central_layout.addWidget(self.placeholder)
        
        # Create menus
        self.create_menus()
        
        # Create toolbar
        self.create_toolbar()
        
        # Configure window
        self.apply_theme()
    
    def create_menus(self):
        # File menu
        file_menu = self.menuBar().addMenu("&File")
        
        open_action = QAction("&Open Book", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.show_open_dialog)
        file_menu.addAction(open_action)
        
        library_action = QAction("&Library", self)
        library_action.setShortcut("Ctrl+L")
        library_action.triggered.connect(self.show_library)
        file_menu.addAction(library_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("&Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = self.menuBar().addMenu("&View")
        
        theme_menu = QMenu("Theme", self)
        view_menu.addMenu(theme_menu)
        
        day_action = QAction("Day Mode", self)
        day_action.triggered.connect(lambda: self.change_theme("light"))
        theme_menu.addAction(day_action)
        
        night_action = QAction("Night Mode", self)
        night_action.triggered.connect(lambda: self.change_theme("dark"))
        theme_menu.addAction(night_action)
        
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings)
        view_menu.addAction(settings_action)
        
        # TOC menu item
        toc_action = QAction("Table of &Contents", self)
        toc_action.setCheckable(True)
        toc_action.setChecked(True)
        toc_action.triggered.connect(lambda checked: self.toc_dock.setVisible(checked))
        view_menu.addAction(toc_action)
        
        # Connect dock visibility to the checkbox state
        self.toc_dock.visibilityChanged.connect(lambda visible: toc_action.setChecked(visible))
    
    def create_toolbar(self):
        # Navigation toolbar
        self.toolbar = QToolBar("Navigation", self)
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        
        # Add navigation buttons
        self.prev_btn = QAction("Previous", self)
        self.prev_btn.triggered.connect(self.prev_page)
        self.toolbar.addAction(self.prev_btn)
        
        self.next_btn = QAction("Next", self)
        self.next_btn.triggered.connect(self.next_page)
        self.toolbar.addAction(self.next_btn)
        
        self.toolbar.addSeparator()
        
        # TOC button
        self.toc_btn = QAction("Table of Contents", self)
        self.toc_btn.setCheckable(True)
        self.toc_btn.setChecked(True)
        self.toc_btn.triggered.connect(lambda checked: self.toc_dock.setVisible(checked))
        self.toolbar.addAction(self.toc_btn)
        
        # Connect dock visibility to the button state
        self.toc_dock.visibilityChanged.connect(lambda visible: self.toc_btn.setChecked(visible))
        
        self.toolbar.addSeparator()
        
        # Theme toggle
        self.theme_btn = QAction("Toggle Theme", self)
        self.theme_btn.triggered.connect(self.toggle_theme)
        self.toolbar.addAction(self.theme_btn)
        
        # Settings button
        self.settings_btn = QAction("Settings", self)
        self.settings_btn.triggered.connect(self.show_settings)
        self.toolbar.addAction(self.settings_btn)
        
        # Library button
        self.library_btn = QAction("Library", self)
        self.library_btn.triggered.connect(self.show_library)
        self.toolbar.addAction(self.library_btn)
    
    def create_toc_dock(self):
        # Table of Contents dock widget
        self.toc_dock = QDockWidget("Table of Contents", self)
        self.toc_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.toc_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        
        # Create TOC widget
        self.toc_widget = QWidget()
        self.toc_layout = QVBoxLayout(self.toc_widget)
        
        self.toc_list = QListWidget()
        self.toc_list.itemClicked.connect(self.navigate_to_section)
        self.toc_layout.addWidget(self.toc_list)
        
        self.toc_dock.setWidget(self.toc_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.toc_dock)
    
    def show_open_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Open Book", 
            "", 
            "eBook Files (*.epub *.pdf *.mobi *.fb2);;All Files (*)"
        )
        
        if file_path:
            self.open_book(file_path)
    
    def open_book(self, file_path):
        try:
            logger.info(f"Opening book: {file_path}")
            
            if not os.path.exists(file_path):
                logger.error(f"File does not exist: {file_path}")
                QMessageBox.critical(self, "Error", f"File not found: {file_path}")
                return
            
            # Close current book if any
            if self.reader_view:
                logger.debug("Closing current book")
                # Save current position
                if self.current_book:
                    position = self.reader_view.get_position()
                    self.config.update_book_state(self.current_book.file_path, position)
                
                # Remove current reader
                self.central_layout.removeWidget(self.reader_view)
                self.reader_view.deleteLater()
                self.reader_view = None
                self.current_book = None
            
            # Hide placeholder if visible
            if self.placeholder.isVisible():
                self.placeholder.hide()
            
            # Load the book
            logger.debug(f"Creating reader for: {file_path}")
            self.current_book = ReaderFactory.get_reader(file_path)
            logger.debug(f"Book loaded. Title: {self.current_book.get_title()}")
            
            # Create reader view for this book
            logger.debug("Creating reader view")
            self.reader_view = ReaderView(self.current_book, self.config)
            self.central_layout.addWidget(self.reader_view)
            
            # Set window title
            self.setWindowTitle(f"{self.current_book.get_title()} - EPUBRead")
            
            # Update TOC
            logger.debug("Updating table of contents")
            self.update_toc()
            
            # Restore position
            state = self.config.get_book_state(file_path)
            if state and "position" in state:
                logger.debug(f"Restoring position: {state['position']}")
                self.reader_view.set_position(state["position"])
            
            # Enable navigation buttons
            self.prev_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
            
            logger.info(f"Book opened successfully: {file_path}")
            
        except Exception as e:
            error_msg = f"Error opening book: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "Error", f"Failed to open book:\n{str(e)}")
    
    def update_toc(self):
        self.toc_list.clear()
        
        if not self.current_book:
            return
        
        for section in self.current_book.get_toc():
            # Get the raw title
            raw_title = section.get('title', 'Untitled')
            level = section.get('level', 0)
            
            # Clean up the title for display
            display_title = self._clean_toc_title(raw_title, section.get('href', ''))
            
            # Indent based on level
            indent = '  ' * level
            item = QListWidgetItem(f"{indent}{display_title}")
            
            # Store section data
            item.setData(Qt.UserRole, section)
            
            self.toc_list.addItem(item)
    
    def _clean_toc_title(self, title, href):
        """Clean up the title for display in the TOC"""
        
        # First handle special case of empty or None titles
        if not title:
            return "Untitled Section"
            
        # If our enhanced extraction has already provided a good title
        # don't apply further transformations
        if not (title.startswith('text/') or '/' in title):
            # Remove any line breaks, extra spaces 
            import re
            title = re.sub(r'\s+', ' ', title).strip()
            
            # Clean up chapter titles that might have duplicated information
            chapter_match = re.match(r'^Chapter\s+\d+\s*[:.-]\s*(.*)', title, re.IGNORECASE)
            if chapter_match and chapter_match.group(1):
                # If the chapter has a subtitle, use that instead of the repetitive "Chapter X" prefix
                subtitle = chapter_match.group(1).strip()
                if subtitle and len(subtitle) > 3:  # Ensure it's a meaningful subtitle
                    return subtitle
            
            # If it's already a good title, return it directly
            if len(title) > 0 and len(title) < 100:
                return title
                
        # If title is a file path, extract a simpler name
        if title.startswith('text/') or '/' in title:
            # Try to extract a meaningful name from the filename
            filename = os.path.basename(title)
            
            # Handle common patterns
            if 'cover' in filename.lower():
                return "Cover"
            elif 'title' in filename.lower():
                return "Title Page"
            elif 'content' in filename.lower() or 'toc' in filename.lower():
                return "Table of Contents"
            elif 'chapter' in filename.lower():
                # Try to extract chapter number
                import re
                match = re.search(r'chapter[_\s-]*(\d+)', filename.lower())
                if match:
                    return f"Chapter {match.group(1)}"
            elif 'introduction' in filename.lower():
                return "Introduction"
            elif 'foreword' in filename.lower():
                return "Foreword"
            elif 'preface' in filename.lower():
                return "Preface"
            elif 'appendix' in filename.lower():
                return "Appendix"
            elif 'index' in filename.lower():
                return "Index"
            elif 'glossary' in filename.lower():
                return "Glossary"
            elif 'dedication' in filename.lower():
                return "Dedication"
            elif 'acknowledgment' in filename.lower():
                return "Acknowledgments" 
            elif 'footnote' in filename.lower():
                return "Footnotes"
            elif 'part' in filename.lower():
                # Try to extract part number
                match = re.search(r'part[_\s-]*(\d+)', filename.lower())
                if match:
                    return f"Part {match.group(1)}"
            elif 'conclusion' in filename.lower():
                return "Conclusion"
        
        # If we couldn't clean it up with the above rules, 
        # try one more approach for chapter filenames
        if title.startswith('text/'):
            parts = title.split('_')
            if len(parts) > 1:
                # Try to make a cleaner title from the parts
                clean_parts = []
                for part in parts:
                    # Skip the path prefix
                    if part.startswith('text/'):
                        continue
                    # Skip part numbers
                    if part.startswith('part') and len(part) <= 6:
                        continue
                    # Skip "split" indicators
                    if part.startswith('split'):
                        continue
                    # Extract sensible names
                    part = part.replace('.html', '').replace('.xhtml', '')
                    if part:
                        clean_parts.append(part.capitalize())
                
                if clean_parts:
                    return " ".join(clean_parts)
        
        return title
    
    def navigate_to_section(self, item):
        section = item.data(Qt.UserRole)
        if section and self.reader_view:
            self.reader_view.navigate_to_section(section)
    
    def prev_page(self):
        if self.reader_view:
            self.reader_view.prev_page()
    
    def next_page(self):
        if self.reader_view:
            self.reader_view.next_page()
    
    def change_theme(self, theme):
        self.config.set("theme", theme)
        self.apply_theme()
    
    def toggle_theme(self):
        current_theme = self.config.get("theme")
        new_theme = "dark" if current_theme == "light" else "light"
        self.change_theme(new_theme)
    
    def apply_theme(self):
        theme = self.config.get("theme")
        
        if theme == "dark":
            # Dark theme
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #1e1e1e; color: #e0e0e0; }
                QMenuBar, QMenu { background-color: #2d2d2d; color: #e0e0e0; }
                QMenuBar::item:selected, QMenu::item:selected { background-color: #3d3d3d; }
                QToolBar { background-color: #2d2d2d; border: none; }
                QToolButton { background-color: #2d2d2d; color: #e0e0e0; }
                QDockWidget { background-color: #2d2d2d; color: #e0e0e0; }
                QDockWidget::title { background-color: #3d3d3d; padding-left: 5px; }
                QListWidget { background-color: #2d2d2d; color: #e0e0e0; border: 1px solid #3d3d3d; }
                QListWidget::item:selected { background-color: #3d3d3d; }
                QStatusBar { background-color: #2d2d2d; color: #e0e0e0; }
            """)
        else:
            # Light theme
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #f5f5f5; color: #212121; }
                QMenuBar, QMenu { background-color: #e5e5e5; color: #212121; }
                QMenuBar::item:selected, QMenu::item:selected { background-color: #d5d5d5; }
                QToolBar { background-color: #e5e5e5; border: none; }
                QToolButton { background-color: #e5e5e5; color: #212121; }
                QDockWidget { background-color: #e5e5e5; color: #212121; }
                QDockWidget::title { background-color: #d5d5d5; padding-left: 5px; }
                QListWidget { background-color: #ffffff; color: #212121; border: 1px solid #d5d5d5; }
                QListWidget::item:selected { background-color: #d5d5d5; }
                QStatusBar { background-color: #e5e5e5; color: #212121; }
            """)
    
    def show_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_() == QDialog.Accepted:
            # Apply settings to current reader view if any
            if self.reader_view:
                self.reader_view.apply_settings()
            
            # Apply theme
            self.apply_theme()
    
    def show_library(self):
        dialog = LibraryView(self.config, self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_book:
            self.open_book(dialog.selected_book)
    
    def closeEvent(self, event):
        # Save current position
        if self.current_book and self.reader_view:
            position = self.reader_view.get_position()
            self.config.update_book_state(self.current_book.file_path, position)
        
        super().closeEvent(event)