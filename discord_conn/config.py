import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
ENV_PATH = ROOT_DIR / ".env"
CONFIG_YAML_PATH = CONFIG_DIR / "config.yaml"

# Load .env if present
load_dotenv(dotenv_path=ENV_PATH)
# Also check config/.env
if not os.getenv("DISCORD_USER_TOKEN") and (CONFIG_DIR / ".env").exists():
    load_dotenv(dotenv_path=CONFIG_DIR / ".env")


class Config:
    def __init__(self, yaml_path: Optional[Path] = None):
        self.yaml_path = yaml_path or CONFIG_YAML_PATH
        self._raw_yaml: Dict[str, Any] = {}
        self._load_yaml()

    def _load_yaml(self) -> None:
        if self.yaml_path.exists():
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                self._raw_yaml = yaml.safe_load(f) or {}
        else:
            self._raw_yaml = {}

    @property
    def discord_token(self) -> str:
        return os.getenv("DISCORD_USER_TOKEN", "").strip()

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    @property
    def database_path(self) -> Path:
        custom_path = os.getenv("DATABASE_PATH")
        if custom_path:
            p = Path(custom_path)
            return p if p.is_absolute() else ROOT_DIR / p
        return ROOT_DIR / "data" / "discord_conn.db"

    @property
    def reports_dir(self) -> Path:
        rel_path = self._raw_yaml.get("output", {}).get("reports_dir", "reports")
        p = Path(rel_path)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def discord_api_base(self) -> str:
        return self._raw_yaml.get("discord", {}).get("api_base_url", "https://discord.com/api/v10")

    @property
    def request_delay(self) -> float:
        return float(self._raw_yaml.get("discord", {}).get("request_delay_seconds", 1.0))

    @property
    def max_messages_per_sync(self) -> int:
        return int(self._raw_yaml.get("discord", {}).get("max_messages_per_sync", 200))

    @property
    def user_agent(self) -> str:
        return self._raw_yaml.get("discord", {}).get(
            "user_agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        )

    @property
    def ai_model(self) -> str:
        return self._raw_yaml.get("ai", {}).get("model", "gemini-3.8-flash")

    @property
    def ai_fallback_model(self) -> str:
        return self._raw_yaml.get("ai", {}).get("fallback_model", "gemini-3.7-flash")

    @property
    def ai_fallback_candidates(self) -> List[str]:
        cfg_candidates = self._raw_yaml.get("ai", {}).get("fallback_candidates")
        if cfg_candidates and isinstance(cfg_candidates, list):
            return [str(m).strip() for m in cfg_candidates if m]
        return ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest"]

    @property
    def ai_max_retries(self) -> int:
        return int(self._raw_yaml.get("ai", {}).get("max_retries", 2))

    @property
    def ai_retry_delay(self) -> float:
        return float(self._raw_yaml.get("ai", {}).get("retry_delay_seconds", 2.0))

    @property
    def ai_temperature(self) -> float:
        return float(self._raw_yaml.get("ai", {}).get("temperature", 0.3))

    @property
    def session_gap_minutes(self) -> int:
        return int(self._raw_yaml.get("pipeline", {}).get("session_gap_minutes", 30))

    @property
    def bot_prefixes(self) -> List[str]:
        return list(self._raw_yaml.get("pipeline", {}).get("bot_prefixes", ["!", "/", "$", "?", "-", ".", ">"]))

    @property
    def prune_repeated_messages(self) -> bool:
        return bool(self._raw_yaml.get("pipeline", {}).get("prune_repeated_messages", True))

    @property
    def max_context_tokens(self) -> int:
        return int(self._raw_yaml.get("pipeline", {}).get("max_context_tokens", 50000))

    @property
    def watched_channels(self) -> List[Dict[str, Any]]:
        return list(self._raw_yaml.get("watched_channels", []))


config = Config()
