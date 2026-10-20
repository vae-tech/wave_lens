"""The Python unit tests of the tools (make unit): python3 -I -m unittest discover -s tests/unit -t ."""
import os, sys

sys.dont_write_bytecode = True
TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'tools')
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
