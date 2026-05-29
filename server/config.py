"""
SoulYatri Speech — Configuration Management
=============================================
Centralized configuration using pydantic-settings.
All values are loaded from environment variables / .env file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LiveKitSettings(BaseSettings):
    """LiveKit server connection settings."""

    model_config = SettingsConfigDict(env_prefix="LIVEKIT_")

    url: str = "ws://localhost:7880"
    api_key: str = "devkey"
    api_secret: str = "secret"


class OllamaSettings(BaseSettings):
    """Ollama LLM settings."""

    model_config = SettingsConfigDict(env_prefix="OLLAMA_")

    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"


class WhisperSettings(BaseSettings):
    """faster-whisper STT settings."""

    model_config = SettingsConfigDict(env_prefix="WHISPER_")

    model_size: str = "small"
    device: str = "cuda"
    compute_type: str = "float16"


class TTSSettings(BaseSettings):
    """edge-tts settings."""

    model_config = SettingsConfigDict(env_prefix="TTS_")

    voice_hindi: str = "hi-IN-SwaraNeural"
    voice_english: str = "en-IN-NeerjaNeural"


class SessionSettings(BaseSettings):
    """Session management settings."""

    model_config = SettingsConfigDict(env_prefix="SESSION_")

    timeout_seconds: int = 300
    max_conversation_history: int = 20


class EmotionSettings(BaseSettings):
    """Emotion extraction settings."""

    model_config = SettingsConfigDict(env_prefix="EMOTION_")

    model_name: str = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
    device: str = "cuda"
    enabled: bool = True


class SpeakerSettings(BaseSettings):
    """Speaker embedding settings."""

    model_config = SettingsConfigDict(env_prefix="SPEAKER_")

    model_source: str = "speechbrain/spkrec-ecapa-voxceleb"
    save_dir: str = "models/speaker_encoder"
    device: str = "cuda"
    enabled: bool = True


class FillerSettings(BaseSettings):
    """Filler phrase system settings."""

    model_config = SettingsConfigDict(env_prefix="FILLER_")

    enabled: bool = True
    pre_synthesize: bool = True
    phrases_path: str = ""


class BargeInSettings(BaseSettings):
    """Barge-in detection settings."""

    model_config = SettingsConfigDict(env_prefix="BARGE_IN_")

    enabled: bool = True
    threshold: float = 0.5
    min_speech_duration_ms: int = 200
    cooldown_ms: int = 500


class Settings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    log_level: str = "INFO"
    log_format: str = "json"

    # Sub-settings
    livekit: LiveKitSettings = LiveKitSettings()
    ollama: OllamaSettings = OllamaSettings()
    whisper: WhisperSettings = WhisperSettings()
    tts: TTSSettings = TTSSettings()
    session: SessionSettings = SessionSettings()
    emotion: EmotionSettings = EmotionSettings()
    speaker: SpeakerSettings = SpeakerSettings()
    filler: FillerSettings = FillerSettings()
    barge_in: BargeInSettings = BargeInSettings()


# Singleton instance — import this everywhere
settings = Settings()
