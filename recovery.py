"""
This is a recovery file, which takes state data and converts back into python types
- Useful for starting from the middle of a project if a module crashes
- This would only be called if main.py was passed an arg of --recovery [what was the last completed]
- This module needs robust fallbacks, first it needs a way to detect manifest and compare with it's own current version
- next this module needs a way to crash if data the user specified is not actually present
- this will be called by main to load information in
"""
