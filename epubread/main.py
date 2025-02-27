#!/usr/bin/env python3
import sys
import os
import logging
from PyQt5.QtWidgets import QApplication
from epubread.ui.main_window import MainWindow
from epubread.utils.config import Config

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser("~/.epubread/debug.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("epubread")

def main():
    try:
        # Create application directory if it doesn't exist
        app_dir = os.path.expanduser("~/.epubread")
        if not os.path.exists(app_dir):
            os.makedirs(app_dir)
            os.makedirs(os.path.join(app_dir, "library"))
        
        logger.info("Starting EPUBRead application")
        
        # Initialize configuration
        config = Config()
        
        # Start the application
        app = QApplication(sys.argv)
        app.setApplicationName("EPUBRead")
        window = MainWindow(config)
        window.show()
        
        logger.info("Application UI loaded successfully")
        
        return app.exec_()
    except Exception as e:
        logger.exception("Error in main function: %s", str(e))
        return 1

if __name__ == "__main__":
    sys.exit(main())