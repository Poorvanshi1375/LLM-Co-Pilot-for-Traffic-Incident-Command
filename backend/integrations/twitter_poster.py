"""
Twitter/X Poster — auto-post incident alerts as tweets.
Gracefully skips if credentials are not configured.
Posting is OFF unless the server sets TWITTER_ENABLED=true, so a public demo
can never tweet from the account just because someone flipped the UI toggle.
"""
from __future__ import annotations

import os
from typing import Optional

_client = None
_initialized = False


def twitter_enabled() -> bool:
    """Server-side kill switch for all posting."""
    return os.getenv("TWITTER_ENABLED", "false").strip().lower() == "true"


def _get_client():
    """Lazily initialize the tweepy client."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    api_key = os.getenv("TWITTER_API_KEY", "")
    api_secret = os.getenv("TWITTER_API_SECRET", "")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_token, access_secret]):
        print("Twitter: credentials not configured — posting disabled")
        return None

    try:
        import tweepy
        _client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        print("Twitter: client initialized")
        return _client
    except ImportError:
        print("Twitter: tweepy not installed — posting disabled")
        return None
    except Exception as e:
        print(f"Twitter: init error — {e}")
        return None


def post_tweet(text: str) -> dict:
    """Post a tweet. Returns status dict with tweet_id/url or skip reason."""
    if not twitter_enabled():
        return {"status": "skipped", "reason": "posting disabled on this server (TWITTER_ENABLED is not true)"}
    client = _get_client()
    if client is None:
        return {"status": "skipped", "reason": "Twitter credentials not configured"}

    try:
        # Truncate to 280 chars
        truncated = text[:280]
        response = client.create_tweet(text=truncated)
        tweet_id = response.data["id"]
        return {
            "status": "posted",
            "tweet_id": tweet_id,
            "url": f"https://x.com/i/status/{tweet_id}",
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200]}
