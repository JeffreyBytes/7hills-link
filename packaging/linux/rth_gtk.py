# PyInstaller runtime hook: the Linux build ships pywebview's GTK backend only, so skip the Qt attempt.
import os

os.environ.setdefault("PYWEBVIEW_GUI", "gtk")
