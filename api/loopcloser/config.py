"""Runtime settings from environment variables.

Secrets (GEMINI_API_KEY) are injected by Cloud Run from Secret Manager
(--set-secrets). In production we never read a .env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    env: str  # "local" | "test" | "production"
    auth_mode: str  # "firebase" | "demo"
    allow_demo_auth_in_production: bool
    storage_backend: str  # "memory" | "firestore"
    firebase_project: str | None
    cors_origins: tuple[str, ...]
    rate_limit_per_minute: int
    rate_limit_sensitive_per_minute: int
    gemini_api_key: str | None
    gemini_model: str
    escalate_after_failed_contacts: int
    version: str

    @property
    def is_production(self) -> bool:
        return self.env == "production"


class ConfigError(RuntimeError):
    pass


def load_config() -> Config:
    env = os.getenv("APP_ENV", "local").lower()
    if env not in {"production", "test"} and not _bool("DOTENV_DISABLED"):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:  # pragma: no cover
            pass
    cfg = Config(
        env=env,
        auth_mode=os.getenv("AUTH_MODE", "firebase" if env == "production" else "demo").lower(),
        allow_demo_auth_in_production=_bool("ALLOW_DEMO_AUTH_IN_PRODUCTION"),
        storage_backend=os.getenv("STORAGE_BACKEND", "memory").lower(),
        firebase_project=os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT"),
        cors_origins=tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        ),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "120")),
        rate_limit_sensitive_per_minute=int(os.getenv("RATE_LIMIT_SENSITIVE_PER_MINUTE", "10")),
        gemini_api_key=(os.getenv("GEMINI_API_KEY") or "").strip() or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        escalate_after_failed_contacts=int(os.getenv("ESCALATE_AFTER_FAILED_CONTACTS", "3")),
        version=os.getenv("APP_VERSION", os.getenv("K_REVISION", "dev")),
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.auth_mode not in {"firebase", "demo"}:
        raise ConfigError(f"AUTH_MODE must be firebase or demo, got {cfg.auth_mode}")
    if cfg.storage_backend not in {"memory", "firestore"}:
        raise ConfigError(f"STORAGE_BACKEND must be memory or firestore, got {cfg.storage_backend}")
    if cfg.is_production:
        if cfg.auth_mode == "demo" and not cfg.allow_demo_auth_in_production:
            raise ConfigError("Demo auth is disabled in production. Set AUTH_MODE=firebase.")
        if cfg.storage_backend != "firestore":
            raise ConfigError("Production must use STORAGE_BACKEND=firestore.")
        if "*" in cfg.cors_origins:
            raise ConfigError("Wildcard CORS is not allowed in production.")


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
