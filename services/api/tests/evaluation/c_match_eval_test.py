"""Collects the Lane C evaluation dataset (c_match_eval.py is not matched by pytest's default pattern)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from c_match_eval import *  # noqa: E402,F401,F403
