from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    kubeconfig_path: str = "configs/rbac/agent-kubeconfig.yaml"
    git_token: str
    git_repo: str
    git_base_branch: str = "main"


@lru_cache
def get_settings() -> Settings:
    return Settings()
