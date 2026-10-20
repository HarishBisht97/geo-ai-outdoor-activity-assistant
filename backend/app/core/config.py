from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["production", "development", "test"] = "production"
    log_level: str = "info"
    allowed_origins: str = "http://localhost:5173"

    contact_email: str = ""
    geocoder_country_bias: str = "in"

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_urls: str = (
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    )
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_aq_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    open_meteo_elevation_url: str = "https://api.open-meteo.com/v1/elevation"
    osrm_driving_url: str = "https://router.project-osrm.org"
    osrm_foot_url: str = "https://routing.openstreetmap.de/routed-foot"
    osrm_bike_url: str = "https://routing.openstreetmap.de/routed-bike"

    slm_enabled: bool = True
    model_repo: str = ""
    model_revision: str = "main"
    model_file: str = "qwen3-1.7b-q4_k_m.gguf"
    model_path: str = "/models/qwen3-1.7b-q4_k_m.gguf"
    model_base_id: str = "Qwen/Qwen3-1.7B"
    model_base_revision: str = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
    model_quant: str = "Q4_K_M"
    n_ctx: int = 4096
    n_threads: int = 2
    n_gpu_layers: int = 0
    slm_intent_timeout_s: float = 25
    slm_explain_timeout_s: float = 50
    slm_max_regenerations: int = 0
    slm_queue_max: int = 4
    slm_intent_max_tokens: int = 200
    slm_explain_max_tokens: int = 420

    request_timeout_s: float = 90
    max_concurrent_requests: int = 3
    max_radius_km: float = 50
    max_window_days: int = 7
    max_candidates: int = 12
    max_results: int = 5
    rate_limit_per_min: int = 10

    http_timeout_s: float = 20
    overpass_timeout_s: float = 45
    overpass_budget_s: float = 50
    overpass_context_budget_s: float = 30
    places_hedge_after_s: float = 10  # start the Nominatim fallback if Overpass is still running
    places_prefer_overpass_s: float = 20  # with fallback results in hand, wait for Overpass until then
    context_soft_wait_s: float = 12  # surrounding-feature context is skipped for the request after this
    http_retries: int = 2
    http_throttle: bool = True  # per-host politeness intervals; only disabled for replayed tests

    cache_ttl_geocode: int = 7 * 24 * 3600
    cache_ttl_places: int = 24 * 3600
    cache_ttl_context: int = 24 * 3600
    cache_ttl_weather: int = 30 * 60
    cache_ttl_air: int = 60 * 60
    cache_ttl_routing: int = 6 * 3600
    cache_ttl_elevation: int = 30 * 24 * 3600

    openaq_api_key: str = Field(default="", repr=False)

    @field_validator("log_level")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def overpass_mirrors(self) -> list[str]:
        return [u.strip() for u in self.overpass_urls.split(",") if u.strip()]

    @property
    def user_agent(self) -> str:
        contact = f" ({self.contact_email})" if self.contact_email else ""
        return f"GeoAI-Outdoor-Assistant/0.1 (+https://github.com/HarishBisht97/geo-ai-outdoor-activity-assistant){contact}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
