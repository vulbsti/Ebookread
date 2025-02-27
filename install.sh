#!/bin/bash
set -e

echo "EPUBRead Installer"
echo "================="
echo "This script will install EPUBRead on your system."
echo

# Check if running as root/sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo:"
    echo "sudo $0"
    exit 1
fi

# Detect system
DISTRO=""
if [ -f /etc/debian_version ]; then
    DISTRO="debian"
    echo "Detected Debian-based system"
elif [ -f /etc/lsb-release ]; then
    DISTRO="ubuntu"
    echo "Detected Ubuntu-based system"
else
    echo "Warning: Could not detect Debian or Ubuntu. The script may not work correctly."
    echo "Proceeding anyway..."
fi

# Install dependencies
echo "Installing dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv python3-pyqt5 python3-dev

CURRENT_DIR="$(pwd)"
INSTALL_DIR="/opt/epubread"
echo "Installing to $INSTALL_DIR"

# Create installation directory
mkdir -p "$INSTALL_DIR"

# Create a Python virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"

# Activate virtual environment and install dependencies
echo "Installing Python dependencies..."
source "$INSTALL_DIR/venv/bin/activate"
pip install ebooklib Pillow lxml PyQt5 beautifulsoup4 
pip install mobi pdfminer.six fb2reader
deactivate

# Copy application files to install directory
echo "Copying application files..."
cp -r "$CURRENT_DIR/epubread" "$INSTALL_DIR/"
cp -r "$CURRENT_DIR/src" "$INSTALL_DIR/"
cp "$CURRENT_DIR/run.py" "$INSTALL_DIR/"
cp "$CURRENT_DIR/README.md" "$INSTALL_DIR/" 2>/dev/null || true

# Create launcher script
LAUNCHER_SCRIPT="/usr/local/bin/epubread"
echo "Creating launcher script at $LAUNCHER_SCRIPT"

cat > "$LAUNCHER_SCRIPT" << 'EOF'
#!/bin/bash
source /opt/epubread/venv/bin/activate
python /opt/epubread/run.py "$@"
EOF

chmod +x "$LAUNCHER_SCRIPT"

# Create a custom icon if it doesn't exist
ICON_PATH="/usr/share/icons/hicolor/128x128/apps/epubread.png"
mkdir -p "$(dirname "$ICON_PATH")"

if [ ! -f "$ICON_PATH" ]; then
    echo "Creating application icon..."
    
    # Base64-encoded book icon (can be replaced with a real icon later)
    BASE64_ICON="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"
    
    echo "$BASE64_ICON" | base64 --decode > "$ICON_PATH"
fi

# Create desktop entry
DESKTOP_FILE="/usr/share/applications/epubread.desktop"
echo "Creating desktop entry at $DESKTOP_FILE"

cat > "$DESKTOP_FILE" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=EPUBRead
Comment=A lightweight e-book reader for EPUB, PDF, MOBI, FB2
Exec=epubread
Icon=epubread
Terminal=false
Categories=Office;Viewer;
Keywords=ebook;reader;epub;pdf;mobi;fb2;
EOF

# Update desktop database
if [ -x "$(command -v update-desktop-database)" ]; then
    echo "Updating desktop database..."
    update-desktop-database
fi

if [ -x "$(command -v gtk-update-icon-cache)" ]; then
    echo "Updating icon cache..."
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi

echo
echo "Installation complete!"
echo "You can now launch EPUBRead from your applications menu or by running 'epubread' in a terminal."
echo