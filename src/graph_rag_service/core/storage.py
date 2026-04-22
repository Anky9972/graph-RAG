import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class StorageProvider:
    def _normalize_filename(self, filename: str) -> str:
        return Path(filename).name

    def save_file(self, filename: str, content: bytes) -> str:
        raise NotImplementedError
        
    def read_file(self, filename: str) -> bytes:
        raise NotImplementedError
        
    def delete_file(self, filename: str) -> bool:
        raise NotImplementedError

class LocalStorage(StorageProvider):
    def __init__(self, upload_dir="data/uploads"):
        self.upload_dir = Path(upload_dir).resolve()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
    def save_file(self, filename: str, content: bytes) -> str:
        filename = self._normalize_filename(filename)
        file_path = self.upload_dir / filename

        with open(file_path, "wb") as f:
            f.write(content)

        return filename
        
    def read_file(self, filename: str) -> bytes:
        filename = self._normalize_filename(filename)
        file_path = self.upload_dir / filename
        with open(file_path, "rb") as f:
            return f.read()
            
    def delete_file(self, filename: str) -> bool:
        filename = self._normalize_filename(filename)
        file_path = self.upload_dir / filename
        try:
            if file_path.exists():
                file_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Error deleting file {filename}: {e}")
            return False

def get_storage():
    """
    Returns the appropriate storage provider based on configuration.
    Currently defaults to LocalStorage which writes to data/uploads.
    """
    return LocalStorage()
