import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QListWidgetItem, QLabel, QPushButton, QFileDialog,
                             QDialogButtonBox, QAbstractItemView)
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt, QSize

from epubread.readers.reader_factory import ReaderFactory

class LibraryView(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.selected_book = None
        
        self.setWindowTitle("Library")
        self.resize(600, 400)
        
        self.init_ui()
        self.load_library()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Book list
        self.book_list = QListWidget()
        self.book_list.setIconSize(QSize(64, 64))
        self.book_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.book_list.itemDoubleClicked.connect(self.handle_book_selected)
        layout.addWidget(self.book_list)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Add book button
        self.add_btn = QPushButton("Add Book")
        self.add_btn.clicked.connect(self.add_book)
        button_layout.addWidget(self.add_btn)
        
        # Remove book button
        self.remove_btn = QPushButton("Remove from List")
        self.remove_btn.clicked.connect(self.remove_book)
        button_layout.addWidget(self.remove_btn)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        self.button_box.button(QDialogButtonBox.Open).clicked.connect(self.open_selected)
        self.button_box.rejected.connect(self.reject)
        button_layout.addWidget(self.button_box)
        
        layout.addLayout(button_layout)
    
    def load_library(self):
        self.book_list.clear()
        
        # Get recent books from config
        recent_books = self.config.get_recent_books()
        
        for book_path in recent_books:
            if os.path.exists(book_path):
                try:
                    # Try to load basic book info
                    book = ReaderFactory.get_reader(book_path)
                    
                    # Create item for the book
                    item = QListWidgetItem()
                    item.setText(f"{book.get_title()} - {book.get_author()}")
                    item.setData(Qt.UserRole, book_path)
                    
                    # Try to get cover
                    cover = book.get_cover_image()
                    if cover:
                        item.setIcon(QIcon(cover))
                    
                    self.book_list.addItem(item)
                    
                except Exception as e:
                    print(f"Error loading book {book_path}: {e}")
    
    def handle_book_selected(self, item):
        book_path = item.data(Qt.UserRole)
        if book_path and os.path.exists(book_path):
            self.selected_book = book_path
            self.accept()
    
    def open_selected(self):
        selected_items = self.book_list.selectedItems()
        if selected_items:
            item = selected_items[0]
            book_path = item.data(Qt.UserRole)
            if book_path and os.path.exists(book_path):
                self.selected_book = book_path
                self.accept()
    
    def add_book(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Add Book to Library", 
            "", 
            "eBook Files (*.epub *.pdf *.mobi *.fb2);;All Files (*)"
        )
        
        if file_path and os.path.exists(file_path):
            # Add to recent books
            if file_path not in self.config.get_recent_books():
                recent_books = self.config.get_recent_books()
                recent_books.append(file_path)
                self.config.set("recent_books", recent_books)
            
            # Reload library
            self.load_library()
    
    def remove_book(self):
        selected_items = self.book_list.selectedItems()
        if selected_items:
            item = selected_items[0]
            book_path = item.data(Qt.UserRole)
            
            # Remove from recent books
            recent_books = self.config.get_recent_books()
            if book_path in recent_books:
                recent_books.remove(book_path)
                self.config.set("recent_books", recent_books)
            
            # Remove from book states
            if "book_states" in self.config.config and book_path in self.config.config["book_states"]:
                del self.config.config["book_states"][book_path]
                self.config.save_config()
            
            # Reload library
            self.load_library()