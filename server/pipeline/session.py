"""
SoulYatri Speech — Session State Manager
==========================================
Manages per-user conversation state including history,
language preferences, and session lifecycle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import active_sessions

logger = get_logger(__name__)


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""

    role: str          # "user" or "assistant"
    content: str       # Text content
    language: str      # Detected language
    timestamp: float   # Unix timestamp


@dataclass
class SessionState:
    """State for a single user session."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    conversation_history: list[ConversationTurn] = field(default_factory=list)
    preferred_language: Optional[str] = None
    is_active: bool = True
    turn_count_total: int = 0

    # Phase 2: Emotion and speaker tracking
    emotion_history: list[dict[str, Any]] = field(default_factory=list)
    turn_metadata: list[dict[str, Any]] = field(default_factory=list)
    speaker_embedding: Optional[object] = None  # np.ndarray, kept generic to avoid import

    def add_turn(self, role: str, content: str, language: str = "en") -> None:
        """Add a conversation turn and update activity timestamp.

        Args:
            role: "user" or "assistant".
            content: Text content of the turn.
            language: Detected language of the turn.
        """
        self.conversation_history.append(
            ConversationTurn(
                role=role,
                content=content,
                language=language,
                timestamp=time.time(),
            )
        )
        self.last_activity = time.time()
        self.turn_count_total += 1

        # Update language preference based on recent turns
        if role == "user":
            self.preferred_language = language

        # Trim history if too long
        max_history = settings.session.max_conversation_history
        if len(self.conversation_history) > max_history:
            self.conversation_history = self.conversation_history[-max_history:]

    def add_emotion(self, emotion: Any) -> None:
        """Record an emotion result for the current session."""
        if emotion is None:
            return

        if hasattr(emotion, "to_dict"):
            payload = emotion.to_dict()
        elif isinstance(emotion, dict):
            payload = emotion
        else:
            payload = {"label": getattr(emotion, "label", "neutral")}

        payload["timestamp"] = time.time()
        self.emotion_history.append(payload)

    def add_turn_metadata(self, metadata: dict[str, Any]) -> None:
        """Store a per-turn metadata bundle."""
        if not metadata:
            return

        self.turn_metadata.append(metadata)
        if len(self.turn_metadata) > settings.session.max_conversation_history:
            self.turn_metadata = self.turn_metadata[-settings.session.max_conversation_history :]

    def get_llm_history(self) -> list[dict]:
        """Get conversation history formatted for the LLM.

        Returns:
            List of {"role": ..., "content": ...} dicts.
        """
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.conversation_history
        ]

    @property
    def is_expired(self) -> bool:
        """Check if session has expired due to inactivity."""
        return (
            time.time() - self.last_activity > settings.session.timeout_seconds
        )

    @property
    def turn_count(self) -> int:
        """Total number of conversation turns."""
        return len(self.conversation_history)


class SessionManager:
    """Manages all active sessions.

    Thread-safe for basic operations. For production scale,
    replace with Redis-backed sessions.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create_session(self, session_id: str) -> SessionState:
        """Create a new session.

        Args:
            session_id: Unique session identifier (e.g., LiveKit participant ID).

        Returns:
            New SessionState instance.
        """
        session = SessionState(session_id=session_id)
        self._sessions[session_id] = session
        active_sessions.inc()

        logger.info("session_created", session_id=session_id)
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get an existing session.

        Args:
            session_id: Session identifier.

        Returns:
            SessionState if found and not expired, None otherwise.
        """
        session = self._sessions.get(session_id)

        if session is None:
            return None

        if session.is_expired:
            self.remove_session(session_id)
            return None

        return session

    def get_or_create_session(self, session_id: str) -> SessionState:
        """Get an existing session or create a new one.

        Args:
            session_id: Session identifier.

        Returns:
            SessionState instance.
        """
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id)
        return session

    def remove_session(self, session_id: str) -> None:
        """Remove a session.

        Args:
            session_id: Session identifier.
        """
        if session_id in self._sessions:
            session = self._sessions.pop(session_id)
            session.is_active = False
            active_sessions.dec()

            logger.info(
                "session_removed",
                session_id=session_id,
                turns=session.turn_count,
                duration=round(time.time() - session.created_at, 1),
            )

    def cleanup_expired(self) -> int:
        """Remove all expired sessions.

        Returns:
            Number of sessions removed.
        """
        expired_ids = [
            sid for sid, session in self._sessions.items()
            if session.is_expired
        ]

        for sid in expired_ids:
            self.remove_session(sid)

        if expired_ids:
            logger.info("sessions_cleaned_up", count=len(expired_ids))

        return len(expired_ids)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)
