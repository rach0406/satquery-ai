"""Central configuration for the SatQuery AI backend.

Everything is environment-overridable so the same image runs on a laptop
during the SIH demo and in a container afterwards.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _b(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _i(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class Settings:
    """Runtime settings. Instantiated once via :func:`get_settings`."""

    app_name: str = "SatQuery AI"
    team: str = "Avengers"
    problem_statement: str = "SIH26167"
    version: str = "1.0.0"

    # --- paths -------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    data_dir: Path = Path(os.getenv("SATQUERY_DATA_DIR", PROJECT_ROOT / "data"))

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def scenes_dir(self) -> Path:
        return self.data_dir / "scenes"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def benchmarks_dir(self) -> Path:
        return self.data_dir / "benchmarks"

    # --- network -----------------------------------------------------
    gibs_wms_url: str = os.getenv(
        "GIBS_WMS_URL",
        "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi",
    )
    gibs_wmts_url: str = os.getenv(
        "GIBS_WMTS_URL",
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best",
    )
    power_api_url: str = os.getenv(
        "NASA_POWER_URL",
        "https://power.larc.nasa.gov/api/temporal/daily/point",
    )
    http_timeout: int = _i("SATQUERY_HTTP_TIMEOUT", 45)
    http_retries: int = _i("SATQUERY_HTTP_RETRIES", 2)
    max_parallel_fetch: int = _i("SATQUERY_MAX_PARALLEL_FETCH", 8)

    # --- behaviour ---------------------------------------------------
    offline_mode: bool = _b("SATQUERY_OFFLINE", False)
    cache_enabled: bool = _b("SATQUERY_CACHE", True)
    cache_ttl_seconds: int = _i("SATQUERY_CACHE_TTL", 60 * 60 * 24 * 14)
    default_raster_size: int = _i("SATQUERY_RASTER_SIZE", 512)
    max_upload_mb: int = _i("SATQUERY_MAX_UPLOAD_MB", 60)

    # --- grounding ---------------------------------------------------
    #: Relative tolerance when checking a narrated number against the fact store.
    numeric_tolerance: float = float(os.getenv("SATQUERY_NUMERIC_TOLERANCE", "0.02"))
    #: If the narrator emits any number that cannot be traced to a fact, fall
    #: back to the deterministic template narrator instead of shipping it.
    strict_grounding: bool = _b("SATQUERY_STRICT_GROUNDING", True)

    # --- LLM (entirely optional) -------------------------------------
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    llm_model: str = os.getenv("SATQUERY_LLM_MODEL", "claude-sonnet-4-5")
    llm_enabled: bool = _b("SATQUERY_LLM_ENABLED", True)
    llm_timeout: int = _i("SATQUERY_LLM_TIMEOUT", 30)

    # --- auth --------------------------------------------------------
    #: How long a signed session token stays valid.
    session_ttl_seconds: int = _i("SATQUERY_SESSION_TTL", 60 * 60 * 12)
    #: When true, the analysis endpoints demand a bearer token. Left off by
    #: default so `curl` demos and the /docs "Try it out" panel keep working;
    #: the console gates access on the client either way.
    require_auth: bool = _b("SATQUERY_REQUIRE_AUTH", False)
    #: Ship a pre-seeded demo login so a judge can sign in without signing up.
    seed_demo_user: bool = _b("SATQUERY_SEED_DEMO_USER", True)

    # --- server ------------------------------------------------------
    host: str = os.getenv("SATQUERY_HOST", "127.0.0.1")
    port: int = _i("SATQUERY_PORT", 8000)
    cors_origins: list[str] = (
        os.getenv("SATQUERY_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    )

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.cache_dir,
            self.scenes_dir,
            self.models_dir,
            self.uploads_dir,
            self.reports_dir,
            self.benchmarks_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
