"""
CreatorLens — application configuration.

Loaded once at startup from environment variables (or a .env file).
Access settings anywhere via:

    from backend.config import settings
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Storage
    upload_dir: str = "./uploads"
    max_upload_bytes: int = 524_288_000  # 500 MB

    # IBM watsonx.ai
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    granite_model_id: str = "ibm/granite-3-3-8b-instruct"

    # Dev flags
    use_mock_ai: bool = True

    # CORS
    frontend_origin: str = "http://localhost:3000"


settings = Settings()
