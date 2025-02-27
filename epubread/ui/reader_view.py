import os
import logging
import traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTextBrowser, QScrollBar,
                            QHBoxLayout, QLabel, QSlider, QPushButton, QFrame,
                            QMessageBox)
from PyQt5.QtGui import QFont, QTextDocument, QTextOption, QColor, QPalette
from PyQt5.QtCore import Qt, QUrl, QSize

logger = logging.getLogger("epubread.reader_view")

class ReaderView(QWidget):
    def __init__(self, book, config):
        super().__init__()
        self.book = book
        self.config = config
        self.current_chapter = 0
        self.current_position = 0
        
        self.init_ui()
        self.load_content()
        
    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Text browser for content
        self.content_view = QTextBrowser()
        self.content_view.setOpenExternalLinks(False)
        self.content_view.setOpenLinks(False)
        self.content_view.anchorClicked.connect(self.handle_link_clicked)
        
        # Enhanced configuration for better image display
        self.content_view.setWordWrapMode(QTextOption.WordWrap)
        
        # Allow proper image display with correct sizing
        self.content_view.setTextInteractionFlags(
            Qt.TextSelectableByMouse | 
            Qt.TextSelectableByKeyboard | 
            Qt.LinksAccessibleByMouse | 
            Qt.LinksAccessibleByKeyboard
        )
        
        # Set document to handle resources (images) better
        doc = self.content_view.document()
        doc.setDefaultStyleSheet("")  # Will be set in process_html_content
        
        self.layout.addWidget(self.content_view)
        
        # Control bar at the bottom
        self.control_bar = QFrame()
        self.control_layout = QHBoxLayout(self.control_bar)
        
        # Chapter info
        self.chapter_label = QLabel()
        self.control_layout.addWidget(self.chapter_label)
        
        # Position slider
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setMinimum(0)
        self.position_slider.setMaximum(100)
        self.position_slider.valueChanged.connect(self.slider_value_changed)
        self.control_layout.addWidget(self.position_slider, 1)  # Stretch factor 1
        
        # Position label
        self.position_label = QLabel("0%")
        self.control_layout.addWidget(self.position_label)
        
        self.layout.addWidget(self.control_bar)
        
        # Apply font and other settings - do this AFTER creating UI elements
        self.apply_settings()
    
    def load_content(self):
        try:
            if not self.book:
                logger.warning("No book loaded")
                return
            
            logger.debug(f"Loading content for chapter {self.current_chapter}")
            
            # For EPUB, load the current chapter
            if hasattr(self.book, 'get_chapter_content'):
                logger.debug("Using book.get_chapter_content()")
                content = self.book.get_chapter_content(self.current_chapter)
                
                if not content:
                    logger.warning(f"Empty content for chapter {self.current_chapter}")
                    self.content_view.setPlainText("Chapter content appears to be empty")
                    return
                    
                logger.debug(f"Chapter content length: {len(content)}")
                
                # Process the HTML content
                processed_content = self.process_html_content(content)
                
                # Set the content
                self.content_view.setHtml(processed_content)
                
                # Update chapter info
                chapter_count = self.book.get_chapter_count()
                self.chapter_label.setText(f"Chapter {self.current_chapter + 1}/{chapter_count}")
                logger.debug(f"Loaded chapter {self.current_chapter + 1} of {chapter_count}")
                
            # For other formats, just display the title for now
            else:
                logger.debug("Not an EPUB book, displaying title only")
                self.content_view.setPlainText(f"Viewing: {self.book.get_title()}")
                
        except Exception as e:
            error_msg = f"Error loading content: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            self.content_view.setPlainText(f"Error loading content: {str(e)}")
    
    def process_html_content(self, html_content):
        """Process the HTML content to match our styling and features."""
        # Apply CSS based on current theme and settings
        theme = self.config.get("theme")
        font_family = self.config.get("font_family")
        font_size = self.config.get("font_size")
        line_spacing = self.config.get("line_spacing")
        contrast = self.config.get("contrast")
        color_temp = self.config.get("color_temperature")
        
        # Calculate colors based on theme and settings
        if theme == "dark":
            bg_color = f"rgb({20 + (100 - contrast) / 4}, {20 + (100 - contrast) / 4}, {20 + (100 - contrast) / 4})"
            text_color = f"rgb({220 + (contrast - 100) / 4}, {220 + (contrast - 100) / 4}, {220 + (contrast - 100) / 4})"
            link_color = "#6495ED"  # Light blue
        else:
            bg_color = f"rgb({255 - (100 - contrast) / 4}, {255 - (100 - contrast) / 4}, {255 - (100 - contrast) / 4})"
            text_color = f"rgb({20 - (contrast - 100) / 4}, {20 - (contrast - 100) / 4}, {20 - (contrast - 100) / 4})"
            link_color = "#0000EE"  # Standard blue
        
        # Apply color temperature (adjust red/blue balance)
        if color_temp < 100:
            # More blue (cooler)
            bg_color = bg_color.replace("rgb(", "rgb(").replace(")", f", {100 - color_temp})")
        elif color_temp > 100:
            # More yellow/red (warmer)
            text_color = text_color.replace("rgb(", f"rgb({min(255, int(color_temp - 100))}, ")
        
        # Create styles for the content
        style = f"""
        <style>
            body {{
                font-family: '{font_family}', sans-serif;
                font-size: {font_size}pt;
                line-height: {line_spacing};
                color: {text_color};
                background-color: {bg_color};
                margin: 2em;
                text-align: justify;
            }}
            
            a {{
                color: {link_color};
                text-decoration: none;
            }}
            
            a:hover {{
                text-decoration: underline;
            }}
            
            /* Image styling */
            img {{
                max-width: 100%;
                height: auto;
                display: block;
                margin: 1em auto 0.3em auto;
                border-radius: 4px;
            }}
            
            /* Figure containers */
            figure {{
                margin: 1em auto;
                text-align: center;
                display: block;
                page-break-inside: avoid;
            }}
            
            figcaption {{
                font-size: 0.85em;
                font-style: italic;
                margin-top: 0.2em;
                margin-bottom: 0.7em;
                color: {text_color};
                opacity: 0.8;
                text-align: center;
                padding: 0 10%;
                line-height: 1.3;
                display: block;
                max-width: 90%;
                margin-left: auto;
                margin-right: auto;
            }}
            
            /* Caption classes that might be used in various EPUB formats */
            .caption, .image-caption, .img-caption, .pic-caption {{
                font-size: 0.85em;
                font-style: italic;
                margin-top: 0.2em;
                text-align: center;
                color: {text_color};
                opacity: 0.8;
                display: block;
                max-width: 90%;
                margin-left: auto;
                margin-right: auto;
                line-height: 1.3;
            }}
            
            /* Image alignment classes */
            .image-left {{
                float: left;
                margin: 0.5em 1em 0.5em 0;
                max-width: 40%;
            }}
            
            .image-right {{
                float: right;
                margin: 0.5em 0 0.5em 1em;
                max-width: 40%;
            }}
            
            .image-center {{
                margin: 1em auto;
                display: block;
            }}
            
            /* Force clear after floating images */
            .clear {{
                clear: both;
            }}
            
            /* Image wrapper for alignment */
            div.image-wrapper {{
                text-align: center;
                margin: 1em 0;
            }}
            
            /* Handle images in divs with specific classes */
            div[class*="image"] img,
            div[class*="img"] img,
            div[class*="figure"] img {{
                display: block;
                margin: 0 auto;
            }}
            
            /* Fix for excess whitespace between image and captions */
            img + figcaption,
            img + .caption,
            img + .image-caption,
            img + .pic-caption,
            img + p.caption,
            img + p > .caption {{
                margin-top: 0.2em !important;
                padding-top: 0 !important;
            }}
            
            /* Handle tables with images and captions */
            table.image-table {{
                margin: 1em auto;
                border-collapse: collapse;
            }}
            
            table.image-table td {{
                text-align: center;
                vertical-align: top;
                padding: 0;
            }}
            
            /* Fix common EPUB issues with paragraphs near images */
            img + p:empty {{
                display: none;
                margin: 0;
                padding: 0;
            }}
        </style>
        """
        
        # Add the style to the HTML content
        if "<head>" in html_content:
            html_content = html_content.replace("<head>", f"<head>{style}")
        else:
            html_content = f"<html><head>{style}</head><body>{html_content}</body></html>"
        
        return html_content
    
    def handle_link_clicked(self, url):
        # Check if it's an internal link (e.g., chapter navigation)
        if url.isRelative():
            href = url.toString()
            
            # Look for chapter by ID or filename
            if hasattr(self.book, 'get_chapter_by_id'):
                chapter_index = self.book.get_chapter_by_id(href)
                if chapter_index != self.current_chapter:
                    self.set_position({"chapter": chapter_index, "position": 0})
        
        # External links could open in a browser if desired
        # QDesktopServices.openUrl(url)
    
    def navigate_to_section(self, section):
        if not self.book:
            return
        
        if 'href' in section:
            href = section['href']
            
            # Look for chapter by ID or filename
            if hasattr(self.book, 'get_chapter_by_id'):
                chapter_index = self.book.get_chapter_by_id(href)
                if chapter_index >= 0:
                    self.set_position({"chapter": chapter_index, "position": 0})
    
    def prev_page(self):
        # If at start of current chapter and not first chapter, go to previous chapter
        if self.content_view.verticalScrollBar().value() == 0 and self.current_chapter > 0:
            self.set_position({"chapter": self.current_chapter - 1, "position": 1.0})  # End of prev chapter
        else:
            # Scroll up by page height
            scrollbar = self.content_view.verticalScrollBar()
            page_step = scrollbar.pageStep()
            new_value = max(0, scrollbar.value() - page_step)
            scrollbar.setValue(new_value)
            
            # Update position tracking
            self.update_position()
    
    def next_page(self):
        scrollbar = self.content_view.verticalScrollBar()
        
        # If at end of current chapter and not last chapter, go to next chapter
        if scrollbar.value() >= scrollbar.maximum() and hasattr(self.book, 'get_chapter_count'):
            if self.current_chapter < self.book.get_chapter_count() - 1:
                self.set_position({"chapter": self.current_chapter + 1, "position": 0})  # Start of next chapter
        else:
            # Scroll down by page height
            page_step = scrollbar.pageStep()
            new_value = min(scrollbar.maximum(), scrollbar.value() + page_step)
            scrollbar.setValue(new_value)
            
            # Update position tracking
            self.update_position()
    
    def slider_value_changed(self, value):
        # Convert slider value (0-100) to scrollbar value
        scrollbar = self.content_view.verticalScrollBar()
        max_val = scrollbar.maximum()
        
        # Calculate position
        position = max_val * (value / 100.0)
        
        # Set scrollbar position
        scrollbar.setValue(int(position))
        
        # Update label
        self.position_label.setText(f"{value}%")
    
    def update_position(self):
        # Update the slider position based on scrollbar
        scrollbar = self.content_view.verticalScrollBar()
        if scrollbar.maximum() > 0:
            percent = int((scrollbar.value() / scrollbar.maximum()) * 100)
            
            # Update slider (without triggering valueChanged signal)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(percent)
            self.position_slider.blockSignals(False)
            
            # Update label
            self.position_label.setText(f"{percent}%")
    
    def get_position(self):
        """Get the current reading position as a dict."""
        return {
            "chapter": self.current_chapter,
            "position": self.content_view.verticalScrollBar().value() / max(1, self.content_view.verticalScrollBar().maximum())
        }
    
    def set_position(self, position):
        """Set the reading position from a position dict."""
        if isinstance(position, dict) and "chapter" in position:
            # Set chapter
            new_chapter = position["chapter"]
            if new_chapter != self.current_chapter:
                self.current_chapter = new_chapter
                self.load_content()
            
            # Set position within chapter
            if "position" in position:
                pos = position["position"]
                scrollbar = self.content_view.verticalScrollBar()
                
                if 0 <= pos <= 1:
                    # Position is a fraction (0.0 to 1.0)
                    scrollbar.setValue(int(scrollbar.maximum() * pos))
                else:
                    # Position is an absolute value
                    scrollbar.setValue(int(pos))
                
                # Update the slider
                self.update_position()
    
    def apply_settings(self):
        """Apply the current configuration settings to the reader view."""
        # Set font
        font = self.config.get_font()
        self.content_view.setFont(font)
        
        # Reload content to apply CSS styling
        self.load_content()
        
        # Apply theme colors to controls
        theme = self.config.get("theme")
        if theme == "dark":
            self.control_bar.setStyleSheet("""
                QFrame { background-color: #2d2d2d; }
                QLabel { color: #e0e0e0; }
                QSlider::groove:horizontal { 
                    background: #3d3d3d; 
                    height: 6px; 
                }
                QSlider::handle:horizontal { 
                    background: #5d5d5d; 
                    width: 12px; 
                    margin: -4px 0; 
                    border-radius: 6px; 
                }
            """)
        else:
            self.control_bar.setStyleSheet("""
                QFrame { background-color: #e5e5e5; }
                QLabel { color: #212121; }
                QSlider::groove:horizontal { 
                    background: #c5c5c5; 
                    height: 6px; 
                }
                QSlider::handle:horizontal { 
                    background: #9d9d9d; 
                    width: 12px; 
                    margin: -4px 0; 
                    border-radius: 6px; 
                }
            """)