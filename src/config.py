from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Config(BaseModel):
    client_secrets_file: Path = Path(os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "credentials.json"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(Path.home() / "Pictures" / "Organized")))
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2-vision")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    min_file_size_bytes: int = int(os.getenv("MIN_FILE_SIZE_BYTES", "500000"))
    min_resolution_width: int = int(os.getenv("MIN_RESOLUTION_WIDTH", "640"))
    min_resolution_height: int = int(os.getenv("MIN_RESOLUTION_HEIGHT", "480"))
    blur_threshold: float = float(os.getenv("BLUR_THRESHOLD", "100.0"))
    hash_distance_threshold: int = int(os.getenv("HASH_DISTANCE_THRESHOLD", "8"))
    token_dir: Path = Path(os.getenv("TOKEN_DIR", str(Path.home() / ".google-photos-organizer")))

    def ensure_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token_dir.mkdir(parents=True, exist_ok=True)


config = Config()
