import os
import mimetypes
from datetime import datetime

class Book:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_type = self._get_file_type()
        self.last_modified = self._get_last_modified()
        self.toc = []
        self.current_position = 0
    
    def _get_file_type(self):
        extension = os.path.splitext(self.file_path)[1].lower()
        if extension == '.epub':
            return 'epub'
        elif extension == '.pdf':
            return 'pdf'
        elif extension == '.mobi':
            return 'mobi'
        elif extension == '.fb2':
            return 'fb2'
        else:
            return 'unknown'
    
    def _get_last_modified(self):
        if os.path.exists(self.file_path):
            timestamp = os.path.getmtime(self.file_path)
            return datetime.fromtimestamp(timestamp)
        return datetime.now()
    
    def get_title(self):
        # By default, use filename without extension
        return os.path.splitext(self.file_name)[0]
    
    def get_author(self):
        # Will be overridden by specific readers
        return "Unknown Author"
    
    def get_cover_image(self):
        # Will be overridden by specific readers
        return None
    
    def get_toc(self):
        return self.toc
    
    def set_position(self, position):
        self.current_position = position
    
    def get_position(self):
        return self.current_position