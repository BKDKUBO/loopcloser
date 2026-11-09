"""Runtime settings from environment variables.

Production calls Gemini through Vertex AI (GEMINI_BACKEND=vertex) with the Cloud Run service account, so
it needs no API key. GEMINI_API_KEY (GEMINI_BACKEND=api_key) is only for local experiments.
In production we never read a .env file.
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
    demo_mode: bool  # explicit DEMO_MODE=true: role switcher for judges, next to real Firebase Auth
    storage_backend: str  # "memory" | "firestore"
    firebase_project: str | None
    cors_origins: tuple[str, ...]
    rate_limit_per_minute: int
    rate_limit_sensitive_per_minute: int
    gemini_api_key: str | None
    gemini_model: str
    escalate_after_failed_contacts: int
    version: str
    clinic_phone: str = "(02) 0000-0000 (demo number)"
    ladder_json: str | None = None
    gemini_backend: str = "off"  # "vertex" | "api_key" | "off"
    vertex_project: str | None = None
    vertex_location: str = "global"

    @property
    def auth_mode(self) -> str:
        return "firebase+demo" if self.demo_mode else "firebase"

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
        demo_mode=_bool("DEMO_MODE", False),
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
        clinic_phone=os.getenv("CLINIC_PHONE", "(02) 0000-0000 (demo number)"),
        ladder_json=os.getenv("LADDER_JSON") or None,
        gemini_backend=(
            os.getenv("GEMINI_BACKEND") or ("api_key" if (os.getenv("GEMINI_API_KEY") or "").strip() else "off")
        )
        .strip()
        .lower(),
        vertex_project=os.getenv("VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT"),
        vertex_location=os.getenv("VERTEX_LOCATION", "global"),
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if os.getenv("AUTH_MODE") or os.getenv("ALLOW_DEMO_AUTH_IN_PRODUCTION"):
        raise ConfigError("AUTH_MODE and ALLOW_DEMO_AUTH_IN_PRODUCTION were removed. Use DEMO_MODE=true|false.")
    if cfg.gemini_backend not in {"vertex", "api_key", "off"}:
        raise ConfigError(f"GEMINI_BACKEND must be vertex, api_key or off, got {cfg.gemini_backend}")
    if cfg.storage_backend not in {"memory", "firestore"}:
        raise ConfigError(f"STORAGE_BACKEND must be memory or firestore, got {cfg.storage_backend}")
    if cfg.is_production:
        if cfg.storage_backend != "firestore":
            raise ConfigError("Production must use STORAGE_BACKEND=firestore.")
        if "*" in cfg.cors_origins:
            raise ConfigError("Wildcard CORS is not allowed in production.")


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
