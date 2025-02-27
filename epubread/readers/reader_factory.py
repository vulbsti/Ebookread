import os
from epubread.models.book import Book
from epubread.readers.epub_reader import EpubBook

class ReaderFactory:
    @staticmethod
    def get_reader(file_path):
        """
        Factory method to get appropriate reader for the given file.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        extension = os.path.splitext(file_path)[1].lower()
        
        if extension == '.epub':
            return EpubBook(file_path)
        # Other formats would be implemented here
        # For now, we'll just return the base Book class for other formats
        else:
            return Book(file_path)