"""
Phase 10F: Forge Local Configuration Manager
Manages user credentials and LLM provider keys stored in ~/.forge/config.json.
"""

import json
import logging
from pathlib import Path
from typing import Any

import keyring

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".forge"
CONFIG_FILE = CONFIG_DIR / "config.json"
SERVICE_NAME = "ForgeEngine"


class ConfigManager:
    """Manages reading and writing developer configuration with OS Credential Store (keyring)."""

    @classmethod
    def ensure_config_dir(cls) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            CONFIG_FILE.write_text("{}", encoding="utf-8")

    @classmethod
    def load_config(cls) -> dict[str, Any]:
        cls.ensure_config_dir()
        try:
            res = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return dict(res) if isinstance(res, dict) else {}
        except Exception:
            return {}

    @classmethod
    def save_config(cls, data: dict[str, Any]) -> None:
        cls.ensure_config_dir()
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def set_key(cls, provider: str, key: str) -> None:
        p = provider.lower().strip()
        val = key.strip()

        # 1. Save secret securely to OS Native Credential Vault
        try:
            keyring.set_password(SERVICE_NAME, p, val)
        except Exception as e:
            logger.warning(f"Keyring storage failed for provider '{p}': {e}")

        # 2. Track configured provider list in config.json
        config = cls.load_config()
        if "providers" not in config:
            config["providers"] = []
        if p not in config["providers"]:
            config["providers"].append(p)
        cls.save_config(config)

    @classmethod
    def get_key(cls, provider: str) -> str | None:
        p = provider.lower().strip()

        # 1. Try OS Credential Store
        try:
            val = keyring.get_password(SERVICE_NAME, p)
            if val:
                return val
        except Exception as e:
            logger.warning(f"Keyring access failed for provider '{p}': {e}")

        # 2. Fallback to legacy config file if present
        config = cls.load_config()
        keys = config.get("keys", {})
        if p in keys:
            return str(keys[p])

        # 3. Fallback to environment variables (e.g. DEEPSEEK_API_KEY, GEMINI_API_KEY)
        import os

        env_val = os.getenv(f"{p.upper()}_API_KEY") or os.getenv(p.upper())
        if env_val:
            return env_val

        return None

    @classmethod
    def list_keys(cls) -> dict[str, str]:
        config = cls.load_config()
        providers: list[str] = config.get("providers", [])

        # Also check legacy keys
        legacy_keys: dict[str, str] = config.get("keys", {})
        for lk in legacy_keys:
            if lk not in providers:
                providers.append(lk)

        masked_map: dict[str, str] = {}
        for p in providers:
            val = cls.get_key(p)
            if val:
                masked_map[p] = f"{val[:4]}...{val[-4:]}" if len(val) > 8 else "****"

        return masked_map
