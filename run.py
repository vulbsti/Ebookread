#!/usr/bin/env python3
"""Development launcher for Ebookread (GTK4 / Libadwaita)."""

import sys
from epubread.main import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
