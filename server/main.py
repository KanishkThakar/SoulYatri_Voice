"""
SoulYatri Speech — FastAPI Server
====================================
Main application entry point with:
- WebSocket endpoint for real-time audio streaming
- REST endpoints for health, metrics, and token generation
- Lifecycle hooks for model initialization
- CORS configuration for the Next.js client
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from .agent import VoiceAgent
from .config import settings
from .utils.audio import (
    pcm_to_float32,
    float32_to_pcm16,
    resample,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_48K,
)
from .utils.logging_config import setup_logging, get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Global agent instance
# ---------------------------------------------------------------------------
agent = VoiceAgent()


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize and cleanup."""
    setup_logging()
    logger.info("server_starting", host=settings.server_host, port=settings.server_port)

    # Initialize the voice agent (loads models)
    await agent.initialize()

    logger.info("server_ready")
    yield

    # Shutdown
    logger.info("server_stopping")
    await agent.shutdown()
    logger.info("server_stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SoulYatri Speech",
    description="Speech-Native Realtime Emotional Voice AI",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0", "phase": 2}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/api/token")
async def get_token(
    room: str = "soulyatri-room",
    identity: str = "user",
):
    """Generate a LiveKit access token for the client.

    This is a simplified token generator for development.
    In production, use proper authentication.
    """
    try:
        from livekit import api as livekit_api

        token = (
            livekit_api.AccessToken(
                settings.livekit.api_key,
                settings.livekit.api_secret,
            )
            .with_identity(identity)
            .with_grants(
                livekit_api.VideoGrants(
                    room_join=True,
                    room=room,
                )
            )
            .to_jwt()
        )

        return {
            "token": token,
            "url": settings.livekit.url,
            "room": room,
            "identity": identity,
        }

    except ImportError:
        # Fallback if livekit-api is not installed — return dummy token
        logger.warning("livekit_api_not_available")
        return {
            "token": "dev-token",
            "url": settings.livekit.url,
            "room": room,
            "identity": identity,
        }
    except Exception as e:
        logger.error("token_generation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# WebSocket — Real-time audio streaming
# ---------------------------------------------------------------------------
@app.websocket("/ws/audio/{session_id}")
async def audio_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time audio streaming.

    Protocol:
    - Client sends binary frames: raw 16-bit PCM audio at 16kHz mono
    - Server sends binary frames: raw 16-bit PCM audio at 24kHz mono
    - Client can send JSON text frames for control messages

    Control messages (text frames):
        {"type": "config", "sample_rate": 16000}
        {"type": "end"}
    """
    await websocket.accept()
    logger.info("ws_connected", session_id=session_id)

    client_sample_rate = SAMPLE_RATE_16K  # Default

    # Set up audio response callback
    async def on_audio_response(
        sid: str,
        audio_bytes: bytes,
        sample_rate: int,
        metadata: dict | None = None,
    ):
        """Send synthesized audio back to the client."""
        try:
            # Send audio data as binary WebSocket frame
            await websocket.send_bytes(audio_bytes)

            # Also send metadata as text frame
            await websocket.send_text(json.dumps({
                "type": "audio_meta",
                "sample_rate": sample_rate,
                "size": len(audio_bytes),
                "metadata": metadata or {},
            }))
        except Exception as e:
            logger.error("ws_send_error", error=str(e), session_id=sid)

    async def on_transcript(sid: str, role: str, text: str):
        """Send transcript updates to the client."""
        try:
            await websocket.send_text(json.dumps({
                "type": "transcript",
                "role": role,
                "text": text,
                "timestamp": time.time(),
            }))
        except Exception as e:
            logger.error("ws_transcript_error", error=str(e), session_id=sid)

    async def on_turn_metadata(sid: str, metadata: dict):
        """Send per-turn feature metadata to the client."""
        try:
            await websocket.send_text(json.dumps({
                "type": "turn_metadata",
                "metadata": metadata,
            }))
        except Exception as e:
            logger.error("ws_turn_metadata_error", error=str(e), session_id=sid)

    agent.set_audio_callback(on_audio_response)
    agent.set_transcript_callback(on_transcript)
    agent.set_turn_metadata_callback(on_turn_metadata)

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                # Binary frame: audio data
                audio_bytes = message["bytes"]
                await agent.handle_audio_frame(
                    session_id=session_id,
                    audio_bytes=audio_bytes,
                    sample_rate=client_sample_rate,
                )

            elif "text" in message and message["text"]:
                # Text frame: control message
                try:
                    control = json.loads(message["text"])
                    msg_type = control.get("type")

                    if msg_type == "config":
                        client_sample_rate = control.get(
                            "sample_rate", SAMPLE_RATE_16K
                        )
                        logger.info(
                            "ws_config_update",
                            session_id=session_id,
                            sample_rate=client_sample_rate,
                        )
                    elif msg_type == "end":
                        logger.info("ws_client_end", session_id=session_id)
                        break

                except json.JSONDecodeError:
                    logger.warning(
                        "ws_invalid_control",
                        session_id=session_id,
                        data=message["text"][:100],
                    )

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    except Exception as e:
        logger.error("ws_error", session_id=session_id, error=str(e))
    finally:
        await agent.handle_session_end(session_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    setup_logging()
    uvicorn.run(
        "server.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level=settings.log_level.lower(),
        ws_max_size=16 * 1024 * 1024,  # 16MB max WebSocket message
    )
