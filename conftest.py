"""Root conftest: adds the project root to sys.path so local modules are importable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
