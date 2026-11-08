"""Environment configuration for the local prototype."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime budgets and local model choice."""

    model_config = SettingsConfigDict(env_prefix="VIBANA_", extra="forbid")

    model: str = "qwen3-vl:4b-instruct"
    num_ctx: int = Field(default=8192, gt=0)
    seed: int = 42
    max_attempts: int = Field(default=3, gt=0)
    max_steps: int = Field(default=10, gt=0)
    max_candidates: int = Field(default=40, gt=0)
    model_timeout_s: float = Field(default=180.0, gt=0)
