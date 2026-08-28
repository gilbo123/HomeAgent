from pathlib import Path

from .config import Config
from .db import ChatDatabase
from .ollama import OllamaClient
from .uploads import UploadStore


class App:
    """Dependency-injected application facade handed to every request.

    Holds the four collaborators plus the static-file location, so the
    HTTP handler never reaches into module-level state.
    """

    def __init__(self, cfg, db, ollama, uploads, static_dir: Path):
        self.cfg = cfg
        self.db = db
        self.ollama = ollama
        self.uploads = uploads
        self.static_dir = static_dir

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        """Release held resources (database connection)."""
        self.db.close()

    # -- convenience lookups used by the handler ------------------------
    @property
    def index_html(self) -> Path:
        """Path to the bundled single-page UI."""
        return self.static_dir / "index.html"
