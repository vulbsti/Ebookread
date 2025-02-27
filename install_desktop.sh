#!/bin/bash

# Create local desktop entry
mkdir -p ~/.local/share/applications

cat > ~/.local/share/applications/epubread.desktop << EOF
[Desktop Entry]
Name=EPUBRead
Comment=A lightweight e-book reader for EPUB, PDF, MOBI, FB2
Exec=$(realpath ./run.py)
Icon=book
Terminal=false
Type=Application
Categories=Office;Viewer;
Keywords=ebook;reader;epub;pdf;mobi;fb2;
EOF

echo "Desktop entry installed! EPUBRead should now appear in your application menu."