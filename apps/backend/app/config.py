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

    # Auth — session cookie
    session_cookie_name: str = "hearth_session"
    session_cookie_samesite: str = "lax"  # "lax" in dev/same-site prod; "none" if API on a different registrable domain
    session_cookie_secure: bool = False  # False in local; True in prod (and required when samesite="none")
    session_max_age_days: int = 30

    # Auth — login throttling (per-email)
    login_lockout_threshold: int = 5
    login_lockout_minutes: int = 15

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
