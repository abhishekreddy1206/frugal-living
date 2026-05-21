from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str = "missing"  # unused while llm.py routes through the Claude Code CLI
    jwt_secret: str = "change-me"
    env: str = "local"
    log_level: str = "INFO"

    # Content ingestion
    youtube_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "frugal-living-dev/0.1"

    # Voice (optional)
    openai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
