"""
SoulYatri Speech — LiveKit Token Generator
=============================================
Generates LiveKit access tokens for development testing.

Usage:
    python scripts/generate_token.py
    python scripts/generate_token.py --room my-room --identity user1
"""

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_token(room: str, identity: str) -> dict:
    """Generate a LiveKit access token.

    Args:
        room: Room name to join.
        identity: Participant identity.

    Returns:
        Dict with token and connection info.
    """
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("LIVEKIT_API_KEY", "devkey")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "secret")
    livekit_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")

    try:
        from livekit import api as livekit_api

        token = (
            livekit_api.AccessToken(api_key, api_secret)
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
            "url": livekit_url,
            "room": room,
            "identity": identity,
        }

    except ImportError:
        print("Error: livekit-api not installed. Run: pip install livekit-api")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Generate LiveKit access tokens")
    parser.add_argument("--room", default="soulyatri-room", help="Room name")
    parser.add_argument("--identity", default="user", help="Participant identity")

    args = parser.parse_args()
    result = generate_token(args.room, args.identity)

    print(f"\n{'='*50}")
    print(f"  LiveKit Access Token")
    print(f"{'='*50}")
    print(f"  Room:     {result['room']}")
    print(f"  Identity: {result['identity']}")
    print(f"  URL:      {result['url']}")
    print(f"  Token:    {result['token'][:50]}...")
    print(f"{'='*50}\n")

    # Also output just the token for scripting
    print(result["token"])


if __name__ == "__main__":
    main()
