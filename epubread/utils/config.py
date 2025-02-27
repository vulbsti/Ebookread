import os
import json
from PyQt5.QtGui import QFont

class Config:
    def __init__(self):
        self.config_path = os.path.expanduser("~/.epubread/config.json")
        self.defaults = {
            "theme": "light",
            "font_family": "Arial",
            "font_size": 12,
            "line_spacing": 1.5,
            "contrast": 100,
            "color_temperature": 100,
            "recent_books": [],
            "book_states": {}
        }
        self.config = self.load_config()
    
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                return self.defaults.copy()
        else:
            return self.defaults.copy()
    
    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get(self, key):
        return self.config.get(key, self.defaults.get(key))
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()
    
    def update_book_state(self, book_path, position):
        if "book_states" not in self.config:
            self.config["book_states"] = {}
        
        self.config["book_states"][book_path] = {
            "position": position,
            "last_opened": os.path.getmtime(book_path) if os.path.exists(book_path) else 0
        }
        
        # Add to recent books if not already there
        if book_path not in self.config["recent_books"]:
            self.config["recent_books"].append(book_path)
        # Ensure the list stays at a reasonable size
        self.config["recent_books"] = self.config["recent_books"][-20:]
        
        self.save_config()
    
    def get_book_state(self, book_path):
        if "book_states" not in self.config:
            return {"position": 0}
        
        return self.config["book_states"].get(book_path, {"position": 0})
    
    def get_recent_books(self):
        # Filter out books that no longer exist
        books = [book for book in self.config.get("recent_books", []) if os.path.exists(book)]
        self.config["recent_books"] = books
        self.save_config()
        return books
    
    def get_font(self):
        font = QFont(self.get("font_family"), self.get("font_size"))
        return font