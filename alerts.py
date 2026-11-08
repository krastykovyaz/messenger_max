"""Failure alerts and the daily heartbeat, sent through the server monitor's Telegram bot.

Credentials are read from config.ALERT_ENV_FILE (TG_BOT_TOKEN, TG_CHAT_ID, HB_URL).
Nothing here ever raises: a broken alert channel must not break the post.
"""
import os
import socket
import urllib.parse

import requests
import config


HOST_LABEL = os.getenv("FAMILY_POST_HOST_LABEL") or socket.gethostname().split(".")[0]


def _env():
    path = config.ALERT_ENV_FILE
    env = {}
    if not path or not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def alert(text):
    """Sends a plain-text Telegram message. Returns True when it was delivered."""
    env = _env()
    if not env.get("TG_BOT_TOKEN") or not env.get("TG_CHAT_ID"):
        print(f"[alert] (no channel configured) {text}")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{env['TG_BOT_TOKEN']}/sendMessage",
            data={"chat_id": env["TG_CHAT_ID"], "text": f"{HOST_LABEL} · семейный пост\n{text}"[:4000]},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        # The exception text can contain the bot URL, so only its type is logged.
        print(f"[alert] не удалось отправить ({type(e).__name__}): {text}")
        return False


def heartbeat(name="aak-first-family-post", max_silence=26 * 3600):
    """Tells the monitor's heartbeat receiver a post went out. Silence longer than
    max_silence (a missed morning) raises an alert there."""
    url = _env().get("HB_URL")
    if not url:
        return False
    try:
        requests.get(f"{url.rstrip('/')}/{urllib.parse.quote(name)}?max={max_silence}", timeout=10)
        return True
    except Exception:
        return False
