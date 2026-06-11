# Ensure the repo root is on sys.path so `src.*` imports work from tests/.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
