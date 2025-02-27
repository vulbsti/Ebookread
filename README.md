# EPUBRead

A lightweight e-book reader for Ubuntu/Debian systems that handles EPUB, PDF, MOBI, and FB2 formats.

## Features

- Support for multiple e-book formats (EPUB, PDF, MOBI, FB2)
- Customizable reading experience (font, size, line spacing)
- Day and night reading modes with contrast and color temperature controls
- Table of contents navigation
- Remembers your reading position for each book
- Library view for quick access to previously opened books
- Lightweight with minimal dependencies

## Installation

### One-Command Installation

Installing EPUBRead is simple with our automated installer script:

```bash
# Install system-wide with all dependencies
sudo ./install.sh
```

The installer will:
- Set up all required dependencies
- Create a virtual environment with all Python packages
- Install the application to /opt/epubread
- Create a desktop entry
- Add an application icon

After installation, you can launch EPUBRead from your applications menu or by running `epubread` in a terminal.

### Manual Installation

If you prefer to install manually or just want to try the application:

1. First, ensure you have Python 3.6+ and pip installed:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-pyqt5 python3-dev
```

2. Install dependencies and run directly:

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the application directly
./run.py
```

## Usage

Launch the application:

```bash
epubread
```

Or run directly with Python:

```bash
python3 src/main.py
```

## Key Shortcuts

- **Ctrl+O**: Open a new book
- **Ctrl+L**: Open library view
- **Ctrl+,**: Open settings
- **Ctrl+Q**: Quit

## License

This project is licensed under the MIT License - see the LICENSE file for details.