import sys
import os

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))

    return os.path.join(base_path, relative_path)


def get_app_data_dir():
    """
    Returns a writable directory for session temp files.
    Frozen (PyInstaller): csv_analyzer_temp/ next to the executable.
    Dev: csv_analyzer_temp/ at the project root (one level above src/).
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "csv_analyzer_temp")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir
