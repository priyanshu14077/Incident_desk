"""M0 check: confirm the configured Groq models exist and read their real limits.

Lists the models your key can see, then sends one 1-token request per configured
model and prints the x-ratelimit-* headers Groq returns. Costs 3 tiny requests.

    uv run python scripts/check_groq.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from incidentdesk import config

API = "https://api.groq.com/openai/v1"


def request(path: str, key: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{API}/{path}",
        data=json.dumps(body).encode() if body else None,
        # Groq's Cloudflare edge rejects urllib's default User-Agent (error 1010).
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "incidentdesk-check/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp), resp.headers


def main() -> int:
    load_dotenv(config.REPO_ROOT / ".env")
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        print("GROQ_API_KEY is not set (put it in .env)")
        return 1

    models, _ = request("models", key)
    available = {m["id"] for m in models["data"]}

    ok = True
    for slot in ("FAST_MODEL", "SMART_MODEL", "FALLBACK_MODEL"):
        litellm_id = getattr(config, slot)
        model_id = litellm_id.removeprefix("groq/")
        if model_id not in available:
            print(f"{slot}: {model_id} NOT AVAILABLE")
            ok = False
            continue
        try:
            _, headers = request(
                "chat/completions",
                key,
                {"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            )
        except urllib.error.HTTPError as e:
            print(f"{slot}: {model_id} request failed: {e.code} {e.read().decode()[:200]}")
            ok = False
            continue
        # Groq: "requests" limits are per day, "tokens" limits are per minute.
        print(
            f"{slot}: {model_id}\n"
            f"  requests/day   {headers.get('x-ratelimit-limit-requests')}"
            f" (remaining {headers.get('x-ratelimit-remaining-requests')})\n"
            f"  tokens/minute  {headers.get('x-ratelimit-limit-tokens')}"
            f" (remaining {headers.get('x-ratelimit-remaining-tokens')})"
        )

    if not ok:
        print("\nAvailable models:\n  " + "\n  ".join(sorted(available)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
