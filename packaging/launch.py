"""Entry script for the PyInstaller build (a package's ``__main__`` cannot be frozen directly)."""

import sys

from audiobook_reader.app import main

sys.exit(main())
