"""Package-root wrapper for the fixed-version research database validator."""
from pathlib import Path
import runpy
import sys

# This validator is shipped with the package and may be run in-place.  Do not
# create __pycache__ files inside a release directory while checking it.
sys.dont_write_bytecode = True
research = Path(__file__).resolve().parent / "Research"
sys.path.insert(0, str(research))
runpy.run_path(str(research / "validate_research.py"), run_name="__main__")
