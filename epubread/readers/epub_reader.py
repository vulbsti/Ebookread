import os
import logging
import traceback
import ebooklib
from ebooklib import epub
from PIL import Image
from io import BytesIO
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QByteArray
from epubread.models.book import Book

logger = logging.getLogger("epubread.epub_reader")

class EpubBook(Book):
    def __init__(self, file_path):
        super().__init__(file_path)
        self.book = None
        self.chapters = []
        self.chapter_content = {}
        self.load_book()
    
    def load_book(self):
        try:
            logger.info(f"Loading EPUB file: {self.file_path}")
            self.book = epub.read_epub(self.file_path)
            logger.debug("EPUB file loaded successfully")
            
            logger.debug("Parsing metadata")
            self._parse_metadata()
            
            logger.debug("Parsing table of contents")
            self._parse_toc()
            
            logger.debug("Extracting chapters")
            self._extract_chapters()
            
            logger.info(f"Book loaded successfully: {self.get_title()}")
        except Exception as e:
            error_msg = f"Error loading EPUB file: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            raise Exception(f"Failed to load EPUB: {str(e)}")
    
    def _parse_metadata(self):
        if self.book is None:
            return
        
        # Extract title
        self.title = self.book.get_metadata('DC', 'title')
        if self.title:
            self.title = self.title[0][0]
        else:
            self.title = super().get_title()
        
        # Extract author
        self.author = self.book.get_metadata('DC', 'creator')
        if self.author:
            self.author = self.author[0][0]
        else:
            self.author = super().get_author()
    
    def _parse_toc(self):
        if self.book is None:
            logger.warning("Cannot parse TOC: no book loaded")
            return
        
        # Initialize TOC with document items
        self.toc = []
        
        # First, try to get the detailed TOC from EPUB's navigation
        try:
            nav_points = self.book.toc
            if nav_points:
                logger.debug("Using book.toc for navigation points")
                self._process_nav_points(nav_points)
                # If we successfully got a TOC from navigation, return
                if self.toc:
                    logger.debug(f"Successfully parsed TOC with {len(self.toc)} items")
                    return
            else:
                logger.debug("No TOC navigation points found")
        except Exception as e:
            logger.error(f"Error processing TOC navigation: {e}")
        
        # If we don't have a TOC yet, try to parse one from NCX if available
        try:
            # Look for NCX file
            ncx_item = None
            for item in self.book.get_items():
                if item.get_type() == ebooklib.ITEM_NAVIGATION:
                    ncx_item = item
                    break
            
            if ncx_item:
                logger.debug("Found NCX navigation item, attempting to parse")
                # We could parse NCX here but it's complex
                # We leave it as an enhancement for a future version
            else:
                logger.debug("No NCX navigation item found")
        except Exception as e:
            logger.error(f"Error looking for NCX: {e}")
        
        # If we still don't have a TOC, build one from the document items
        if not self.toc:
            logger.debug("Building TOC from document items")
            # Create TOC from documents in spine order if possible
            ordered_items = []
            
            # First try to use the spine for ordering
            try:
                if hasattr(self.book, 'spine') and self.book.spine:
                    logger.debug("Using book spine for ordering")
                    # Create a lookup by ID
                    items_by_id = {item.id: item for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
                    
                    # Get items in spine order
                    for item_id in self.book.spine:
                        if item_id in items_by_id:
                            ordered_items.append(items_by_id[item_id])
                    
                    # Add any document items not in spine
                    for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                        if item not in ordered_items:
                            ordered_items.append(item)
            except Exception as e:
                logger.error(f"Error using spine for ordering: {e}")
            
            # If spine didn't work, just use all document items
            if not ordered_items:
                logger.debug("Using all document items for TOC")
                ordered_items = list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
            
            # Look for chapter titles inside document contents where possible
            for item in ordered_items:
                title = item.get_name()
                
                # Try to extract a title from the content
                try:
                    content = item.get_content().decode('utf-8')
                    
                    # Import regex here to avoid repetition
                    import re
                    
                    # First look for title tag - often contains the real chapter title
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
                    if title_match:
                        extracted_title = title_match.group(1).strip()
                        if extracted_title:
                            # Clean up title (remove "Chapter X" prefix if present)
                            clean_title = re.sub(r'^Chapter\s+\d+[\s:\-–—]*', '', extracted_title, flags=re.IGNORECASE)
                            # If we didn't strip anything, or what's left is too short, use the original
                            if clean_title and len(clean_title) > 3:
                                title = clean_title.strip()
                            else:
                                title = extracted_title
                    
                    # Look for the header structure
                    # Try h1 first
                    if title == item.get_name():
                        heading_match = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE | re.DOTALL)
                        if heading_match:
                            extracted_title = heading_match.group(1).strip()
                            # Remove any HTML tags from the heading
                            extracted_title = re.sub(r'<[^>]*>', '', extracted_title)
                            if extracted_title:
                                # Clean up title (remove "Chapter X" prefix if present)
                                clean_title = re.sub(r'^Chapter\s+\d+[\s:\-–—]*', '', extracted_title, flags=re.IGNORECASE)
                                # If we didn't strip anything, or what's left is too short, use the original
                                if clean_title and len(clean_title) > 3:
                                    title = clean_title.strip()
                                else:
                                    title = extracted_title
                    
                    # If we still have the filename, look for strong or b tags that might contain the title
                    if title == item.get_name():
                        # Look for text in a strong tag
                        strong_match = re.search(r'<strong[^>]*>(.*?)</strong>', content, re.IGNORECASE | re.DOTALL)
                        if strong_match:
                            extracted_title = strong_match.group(1).strip()
                            # Remove any HTML tags
                            extracted_title = re.sub(r'<[^>]*>', '', extracted_title)
                            if extracted_title and len(extracted_title) < 100:  # Avoid grabbing large blocks
                                title = extracted_title
                    
                    # If we still have the filename, look for more patterns
                    if title == item.get_name():
                        # Look for text that appears to be a chapter title
                        # Based on common patterns in EPUB files
                        patterns = [
                            # Chapter title in a header with a class
                            r'<h[1-3][^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h[1-3]>',
                            # Section title in a div with title class
                            r'<div[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</div>',
                            # Look for any h2 tag
                            r'<h2[^>]*>(.*?)</h2>',
                            # Look for any h3 tag
                            r'<h3[^>]*>(.*?)</h3>',
                            # Look for a paragraph with title class
                            r'<p[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</p>',
                            # Look for chapter identification
                            r'<p[^>]*class="[^"]*chapter[^"]*"[^>]*>(.*?)</p>'
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                            if match:
                                extracted_title = match.group(1).strip()
                                # Remove any HTML tags
                                extracted_title = re.sub(r'<[^>]*>', '', extracted_title)
                                if extracted_title and len(extracted_title) < 100:  # Avoid grabbing large blocks
                                    title = extracted_title
                                    break  # Found a title, stop looking
                    
                    # If the filename implies this is a chapter but we don't have a good title,
                    # try to infer chapter number and provide a better title
                    if title == item.get_name() and ('chapter' in item.file_name.lower() or '/ch' in item.file_name.lower()):
                        chapter_num_match = re.search(r'chapter[_\s-]*(\d+)|ch(\d+)', item.file_name.lower())
                        if chapter_num_match:
                            chapter_num = chapter_num_match.group(1) or chapter_num_match.group(2)
                            title = f"Chapter {chapter_num}"
                    
                    # Clean up the title
                    title = title.strip()
                    # Remove any excessive whitespace
                    title = re.sub(r'\s+', ' ', title)
                    # Remove any EPUB markers or other oddities
                    title = re.sub(r'^\s*CHAPTER\s+\d+\s*$', '', title, flags=re.IGNORECASE)
                    
                    # If we still ended up with nothing useful, use some fallbacks
                    if not title or title == item.get_name():
                        # Try to infer from filename
                        basename = os.path.basename(item.file_name)
                        name_without_ext = os.path.splitext(basename)[0]
                        
                        # For files like chapter_1.html or ch01.html
                        if 'chapter' in name_without_ext.lower() or name_without_ext.lower().startswith('ch'):
                            chapter_num_match = re.search(r'(?:chapter|ch)[_\s-]*(\d+)', name_without_ext.lower())
                            if chapter_num_match:
                                title = f"Chapter {chapter_num_match.group(1)}"
                        # For part files
                        elif 'part' in name_without_ext.lower():
                            part_num_match = re.search(r'part[_\s-]*(\d+)', name_without_ext.lower())
                            if part_num_match:
                                title = f"Part {part_num_match.group(1)}"
                        # For section files
                        elif 'section' in name_without_ext.lower():
                            section_num_match = re.search(r'section[_\s-]*(\d+)', name_without_ext.lower())
                            if section_num_match:
                                title = f"Section {section_num_match.group(1)}"
                                
                except Exception as e:
                    logger.debug(f"Error extracting title from content: {e}")
                
                self.toc.append({
                    'id': item.id,
                    'href': item.file_name,
                    'title': title,
                    'level': 0  # Default level
                })
            
            logger.debug(f"Built TOC with {len(self.toc)} items")
    
    def _extract_heading_from_target(self, href):
        """Extract a heading from the content that the link points to"""
        try:
            # Find the chapter by href
            target_chapter = None
            for chapter in self.chapters:
                if href == chapter.file_name or href == chapter.id:
                    target_chapter = chapter
                    break
                    
                # Handle fragment identifiers (e.g., chapter.html#section1)
                if '#' in href and href.split('#')[0] == chapter.file_name:
                    target_chapter = chapter
                    break
            
            if target_chapter:
                # Get the content
                content_bytes = target_chapter.get_content()
                if not content_bytes:
                    return None
                
                content = content_bytes.decode('utf-8')
                
                # Process the content to find the best heading
                import re
                
                # Extract the fragment if there is one
                fragment_id = None
                if '#' in href:
                    fragment_id = href.split('#')[1]
                
                # If we have a fragment ID, try to find the heading at that location
                if fragment_id:
                    # Look for the element with that ID
                    id_pattern = f'id=["\']?{fragment_id}["\']?'
                    id_match = re.search(id_pattern, content, re.IGNORECASE)
                    
                    if id_match:
                        # Get some content around the ID
                        id_pos = id_match.start()
                        context_before = content[max(0, id_pos-500):id_pos]
                        context_after = content[id_pos:min(len(content), id_pos+500)]
                        
                        # Look for headings near this ID
                        heading_patterns = [
                            r'<h1[^>]*>(.*?)</h1>',
                            r'<h2[^>]*>(.*?)</h2>',
                            r'<h3[^>]*>(.*?)</h3>',
                            r'<h4[^>]*>(.*?)</h4>',
                            r'<b[^>]*>(.*?)</b>',
                            r'<strong[^>]*>(.*?)</strong>'
                        ]
                        
                        # First try context after (more likely to be a heading)
                        for pattern in heading_patterns:
                            match = re.search(pattern, context_after, re.IGNORECASE | re.DOTALL)
                            if match:
                                heading = match.group(1).strip()
                                # Remove any HTML tags
                                heading = re.sub(r'<[^>]*>', '', heading)
                                if heading and len(heading) < 100:  # Reasonable heading length
                                    return heading
                        
                        # Then try context before
                        for pattern in heading_patterns:
                            match = re.search(pattern, context_before, re.IGNORECASE | re.DOTALL)
                            if match:
                                heading = match.group(1).strip()
                                # Remove any HTML tags
                                heading = re.sub(r'<[^>]*>', '', heading)
                                if heading and len(heading) < 100:  # Reasonable heading length
                                    return heading
                
                # If we didn't find a specific heading or don't have a fragment,
                # look for the first heading in the content
                heading_patterns = [
                    r'<h1[^>]*>(.*?)</h1>',
                    r'<title[^>]*>(.*?)</title>',
                    r'<h2[^>]*>(.*?)</h2>',
                    r'<h3[^>]*>(.*?)</h3>'
                ]
                
                for pattern in heading_patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                    if match:
                        heading = match.group(1).strip()
                        # Remove any HTML tags
                        heading = re.sub(r'<[^>]*>', '', heading)
                        # Clean up the heading
                        heading = re.sub(r'\s+', ' ', heading).strip()
                        if heading and len(heading) < 100:  # Reasonable heading length
                            return heading
                
                # If we still don't have a good heading, look for patterns in the content
                # that might indicate chapter titles
                title_patterns = [
                    # Class-based patterns
                    r'<[^>]*class=["\']?[^"\']*title[^"\']*["\']?[^>]*>(.*?)</[^>]*>',
                    r'<[^>]*class=["\']?[^"\']*chapter[^"\']*["\']?[^>]*>(.*?)</[^>]*>',
                    r'<[^>]*class=["\']?[^"\']*heading[^"\']*["\']?[^>]*>(.*?)</[^>]*>',
                    
                    # Chapter number patterns
                    r'<p[^>]*>\s*Chapter\s+\d+\s*[:.]\s*(.*?)</p>',
                    r'<p[^>]*>\s*CHAPTER\s+\d+\s*[:.]\s*(.*?)</p>',
                    r'<p[^>]*>\s*Chapter\s+\d+\s*(.*?)</p>',
                    r'<p[^>]*>\s*CHAPTER\s+\d+\s*(.*?)</p>'
                ]
                
                for pattern in title_patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                    if match:
                        heading = match.group(1).strip()
                        # Remove any HTML tags
                        heading = re.sub(r'<[^>]*>', '', heading)
                        # Clean up the heading
                        heading = re.sub(r'\s+', ' ', heading).strip()
                        if heading and len(heading) < 100:  # Reasonable heading length
                            return heading
                
                # Just extract the first paragraph as a fallback
                para_match = re.search(r'<p[^>]*>(.*?)</p>', content, re.IGNORECASE | re.DOTALL)
                if para_match:
                    para = para_match.group(1).strip()
                    # Remove any HTML tags
                    para = re.sub(r'<[^>]*>', '', para)
                    # Clean up and truncate if needed
                    para = re.sub(r'\s+', ' ', para).strip()
                    if para and len(para) > 5:  # Ensure it's not just whitespace
                        # Truncate to a reasonable length for a title
                        if len(para) > 50:
                            para = para[:47] + "..."
                        return para
                        
        except Exception as e:
            logger.debug(f"Error extracting heading from target content: {e}")
        
        return None

    def _process_nav_points(self, nav_points, level=0):
        result = []
        for nav_point in nav_points:
            if isinstance(nav_point, tuple) and len(nav_point) >= 2:
                title, href = nav_point[0], nav_point[1]
                if href:
                    # Store basic info
                    section = {
                        'id': href,
                        'href': href,
                        'title': title,
                        'level': level
                    }
                    
                    # Extract better title from the actual content the link points to
                    better_title = self._extract_heading_from_target(href)
                    if better_title:
                        section['title'] = better_title
                        
                    result.append(section)
            
            # Process children
            if len(nav_point) > 2 and nav_point[2]:
                children = self._process_nav_points(nav_point[2], level + 1)
                result.extend(children)
        
        if level == 0:
            self.toc = result
        return result
    
    def _extract_chapters(self):
        if self.book is None:
            logger.warning("No book object available")
            return
        
        # Extract chapters
        self.chapters = []
        documents = list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        logger.debug(f"Found {len(documents)} document items")
        
        for item in documents:
            logger.debug(f"Processing document: id={item.id}, file_name={item.file_name}")
            self.chapters.append(item)
            try:
                content_bytes = item.get_content()
                if not content_bytes:
                    logger.warning(f"Empty content for chapter {item.file_name}")
                    continue
                    
                logger.debug(f"Raw content size: {len(content_bytes)} bytes")
                content = content_bytes.decode('utf-8')
                logger.debug(f"Decoded content size: {len(content)} characters")
                self.chapter_content[item.file_name] = content
            except Exception as e:
                error_msg = f"Error decoding chapter {item.file_name}: {str(e)}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
        
        logger.info(f"Extracted {len(self.chapters)} chapters")
    
    def get_title(self):
        return self.title
    
    def get_author(self):
        return self.author
    
    def get_cover_image(self):
        if self.book is None:
            return None
        
        try:
            # Try to find cover image item
            cover_item = None
            for item in self.book.get_items_of_type(ebooklib.ITEM_COVER):
                cover_item = item
                break
            
            if cover_item is None:
                # Try to find image item with 'cover' in id or href
                for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    if 'cover' in item.id.lower() or 'cover' in item.file_name.lower():
                        cover_item = item
                        break
            
            if cover_item is None:
                # Just use the first image
                for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    cover_item = item
                    break
            
            if cover_item:
                image_data = cover_item.get_content()
                qimg = QImage()
                qimg.loadFromData(QByteArray(image_data))
                return QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"Error extracting cover image: {e}")
        
        return None
    
    def get_chapter_content(self, chapter_index):
        try:
            logger.debug(f"Requested content for chapter index: {chapter_index}")
            
            if not self.chapters:
                logger.warning("No chapters available")
                return "No chapters available in this book"
                
            if chapter_index < 0 or chapter_index >= len(self.chapters):
                logger.warning(f"Chapter index out of range: {chapter_index}, max: {len(self.chapters)-1}")
                return f"Chapter index out of range (0-{len(self.chapters)-1})"
            
            chapter = self.chapters[chapter_index]
            logger.debug(f"Getting content for chapter: {chapter.file_name}")
            
            # Load chapter content if not already cached
            if chapter.file_name not in self.chapter_content:
                logger.warning(f"No content stored for chapter: {chapter.file_name}")
                
                # Try to load it now
                try:
                    logger.debug("Attempting to load chapter content now")
                    content_bytes = chapter.get_content()
                    if content_bytes:
                        content = content_bytes.decode('utf-8')
                        self.chapter_content[chapter.file_name] = content
                        logger.debug(f"Successfully loaded chapter content: {len(content)} characters")
                    else:
                        logger.warning("Got empty content bytes")
                        return "Chapter appears to be empty"
                except Exception as e:
                    error_msg = f"Error loading chapter content: {str(e)}"
                    logger.error(error_msg)
                    logger.error(traceback.format_exc())
                    return f"Error loading chapter: {str(e)}"
            
            # Get the content from cache
            content = self.chapter_content.get(chapter.file_name, "")
            logger.debug(f"Returning chapter content, length: {len(content)}")
            
            # Process content to fix image paths
            content = self._process_chapter_images(chapter, content)
            
            return content
        except Exception as e:
            error_msg = f"Error in get_chapter_content: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return f"Error retrieving chapter content: {str(e)}"
    
    def _process_chapter_images(self, chapter, content):
        """Process the chapter content to handle image references correctly 
        and clean up caption formatting."""
        try:
            import re
            from base64 import b64encode
            
            # Find all image tags in the content
            img_tags = re.findall(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', content)
            
            # First, process all image references
            for img_src in img_tags:
                # Handle both absolute and relative paths
                img_path = img_src
                if img_src.startswith('/'):
                    img_path = img_src[1:]  # Remove leading slash
                
                # Try to find the image in the book's items
                img_item = None
                
                # First check if the path matches directly
                for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                    if item.file_name == img_path:
                        img_item = item
                        break
                
                # If not found, try to match the end of the path (common in EPUB files)
                if img_item is None:
                    for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                        if img_path.endswith(item.file_name) or item.file_name.endswith(img_path):
                            img_item = item
                            break
                
                # If still not found, check if the image is in the same directory as the chapter
                if img_item is None and '/' in chapter.file_name:
                    chapter_dir = '/'.join(chapter.file_name.split('/')[:-1]) + '/'
                    chapter_relative_path = chapter_dir + img_path
                    
                    for item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
                        if item.file_name == chapter_relative_path:
                            img_item = item
                            break
                
                # If image found, replace the src with data URL
                if img_item:
                    try:
                        img_data = img_item.get_content()
                        if img_data:
                            # Determine mime type from file extension
                            mime_type = 'image/jpeg'  # Default
                            if img_item.file_name.lower().endswith('.png'):
                                mime_type = 'image/png'
                            elif img_item.file_name.lower().endswith('.gif'):
                                mime_type = 'image/gif'
                            elif img_item.file_name.lower().endswith('.svg'):
                                mime_type = 'image/svg+xml'
                            
                            # Create data URL
                            b64_data = b64encode(img_data).decode('utf-8')
                            data_url = f'data:{mime_type};base64,{b64_data}'
                            
                            # Replace the image source in the content
                            content = content.replace(f'src="{img_src}"', f'src="{data_url}"')
                            content = content.replace(f"src='{img_src}'", f'src="{data_url}"')
                    except Exception as e:
                        logger.warning(f"Error embedding image {img_path}: {str(e)}")
            
            # Now fix common caption issues in EPUB files
            
            # Fix spacing in figure and figcaption elements
            content = re.sub(
                r'(<figure[^>]*>)\s*(<img[^>]*>)\s*(<figcaption[^>]*>)',
                r'\1\2\3',
                content
            )
            
            # Add caption class to paragraphs that appear to be captions
            content = re.sub(
                r'(<img[^>]*>)\s*(<p[^>]*>)([^<]{1,150})(</p>)',
                r'\1\2<span class="caption">\3</span>\4',
                content
            )
            
            # Remove excessive whitespace between images and captions
            content = re.sub(
                r'(<img[^>]*>)\s*(<figcaption)',
                r'\1\2',
                content
            )
            
            # Remove empty paragraphs after images (common in some EPUBs)
            content = re.sub(
                r'(<img[^>]*>)\s*(<p[^>]*>)\s*(</p>)',
                r'\1',
                content
            )
            
            # If image is followed by a div with class containing 'caption', add proper styling
            content = re.sub(
                r'(<img[^>]*>)\s*(<div[^>]*class=["\'][^"\']*caption[^"\']*["\'][^>]*>)',
                r'\1\2',
                content
            )
            
            # Fix common pattern: image followed by <br> then caption text
            content = re.sub(
                r'(<img[^>]*>)\s*(<br[^>]*>)\s*([^<]{5,100})',
                r'\1<p class="caption">\3</p>',
                content
            )
            
            # Add caption class to any small text that follows images
            content = re.sub(
                r'(<img[^>]*>)\s*(<small[^>]*>)([^<]+)(</small>)',
                r'\1<small class="caption">\3</small>',
                content
            )
            
            return content
        except Exception as e:
            logger.warning(f"Error processing chapter images: {str(e)}")
            return content
    
    def get_chapter_count(self):
        return len(self.chapters)
    
    def get_chapter_by_id(self, chapter_id):
        for i, chapter in enumerate(self.chapters):
            if chapter.id == chapter_id or chapter.file_name == chapter_id:
                return i
        return 0