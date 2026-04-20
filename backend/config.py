from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-nano"
    # OpenAI TTS kept as a fallback engine. When ELEVENLABS_API_KEY is set,
    # services/tts.py prefers ElevenLabs to keep the TTS provider cleanly
    # separated from the LLM selection list required by the submission brief.
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "nova"
    # ElevenLabs TTS — primary engine when the key is configured.
    # voice_id comes from the user's ElevenLabs library (VoiceLab / Voices).
    # model_id "eleven_multilingual_v2" supports Korean reliably.
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL_ID: str = "eleven_multilingual_v2"
    # 네이버 검색 API (뉴스 수집 4번째 소스). 둘 다 비어있으면 NaverSearchClient
    # 는 no-op로 동작하고 나머지 3개 소스만 사용됨.
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    AUDIO_CACHE_DIR: str = "./media/audio"
    LLM_MAX_RETRIES: int = 2

    DATABASE_URL: str = "sqlite:///./briefbot.db"
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    COLLECT_PER_CATEGORY: int = 20
    CLUSTER_THRESHOLD: float = 0.6
    ARTICLE_HOURS: int = 24

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
