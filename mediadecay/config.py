import os
from pathlib import Path

import yaml

_config = None


def validate_config(cfg: dict) -> None:
    """Validate config schema. Raises ValueError for missing required fields."""
    # Plex section (required)
    if "plex" not in cfg:
        raise ValueError("Config missing required section: 'plex'")
    for field in ("url", "token"):
        if not cfg["plex"].get(field):
            raise ValueError(f"Config 'plex' section missing required field: '{field}'")

    # Web section (required)
    if "web" not in cfg:
        raise ValueError("Config missing required section: 'web'")
    for field in ("secret_key", "admin_password"):
        if not cfg["web"].get(field):
            raise ValueError(f"Config 'web' section missing required field: '{field}'")

    # Notifications section (conditional)
    notifications = cfg.get("notifications", {})
    if notifications.get("enabled"):
        method = notifications.get("method", "email")
        if method == "email":
            email_cfg = notifications.get("email", {})
            if not email_cfg:
                raise ValueError("Config 'notifications' enabled with method 'email' but 'email' section is missing")
            for field in ("from", "smtp_host"):
                if not email_cfg.get(field):
                    raise ValueError(f"Config 'notifications.email' missing required field: '{field}'")
        elif method == "discord":
            discord_cfg = notifications.get("discord", {})
            if not discord_cfg or not discord_cfg.get("webhook_url"):
                raise ValueError("Config 'notifications' enabled with method 'discord' but 'discord.webhook_url' is missing")

    # Optional manager sections — validate only if present
    for section in ("sonarr", "radarr", "medusa", "ombi"):
        if section in cfg:
            for field in ("url", "api_key"):
                if not cfg[section].get(field):
                    raise ValueError(f"Config '{section}' section missing required field: '{field}'")


def load_config(path: str | None = None) -> dict:
    global _config
    if _config is not None and path is None:
        return _config
    if path is None:
        path = os.environ.get("MEDIACLEANER_CONFIG", "config.yaml")
    with open(Path(path)) as f:
        _config = yaml.safe_load(f)
    validate_config(_config)
    return _config


def get_config() -> dict:
    if _config is None:
        return load_config()
    return _config
