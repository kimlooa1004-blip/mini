import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from PIL import Image  # noqa: E402


def png(size=(50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def temp_db():
    """Point the app at a throwaway SQLite file and return its directory object."""
    d = tempfile.TemporaryDirectory()
    os.environ["APP_DB_PATH"] = str(Path(d.name) / "t.db")
    return d
