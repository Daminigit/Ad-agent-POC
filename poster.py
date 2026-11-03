"""
Root proxy launcher for Poster Generator CLI
============================================
Delegates CLI execution to poster_generator/poster.py.
"""

import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).parent / "poster_generator" / "poster.py"
    cmd = [sys.executable, str(script)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))
