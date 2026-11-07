"""Daily family post to MAX at 06:00 Moscow time: weather, extras and a matching photo.

Runs as a long-lived process (started and kept alive by cron).
Only one instance can run at a time, a day is never posted twice, and every failure is
reported to Telegram through the server monitor's bot (alerts.py).

Two roles (FAMILY_POST_ROLE):
- primary (aak-first) posts at 06:00. After a confirmed post it writes a marker onto the
  standby over SSH and copies the MAX login there, so the standby's copy stays valid.
- standby (horek_fi) wakes at 06:40. With the marker present it does nothing and never
  touches MAX. Without it, it opens the chat and posts only if today's post is not there.
"""
import fcntl
import os
import shlex
import subprocess
import time
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

import config
from ai_generator import AIDescriptionGeneratorQwenVL
from alerts import alert, heartbeat
from download_pics import download_random_image, purge_old_images
from extras import MONTHS, build_extras, pick_photo_topic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "max_profile")
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "family_post.lock")
LAST_POST_FILE = os.path.join(STATE_DIR, "last_post_date")
# FAMILY_POST_CHAT_URL overrides the target, e.g. CHAT_URL_ME (Избранное) for a test run
CHAT_URL = os.getenv("FAMILY_POST_CHAT_URL") or config.CHAT_URL_FAM

MSK = ZoneInfo("Europe/Moscow")
ROLE = os.getenv("FAMILY_POST_ROLE", "primary")
POST_HOUR = 6
POST_MINUTE = int(os.getenv("STANDBY_DELAY_MINUTES", "40")) if ROLE == "standby" else 0
PRIMARY_MARKER = os.path.join(STATE_DIR, "primary_done")   # written by the primary over SSH
# primary only: where the standby lives, e.g. familypost@2.27.33.175 (unset = no standby)
STANDBY_HOST = os.getenv("STANDBY_HOST")
STANDBY_DIR = os.getenv("STANDBY_DIR", "family_post")
STANDBY_SSH_KEY = os.getenv("STANDBY_SSH_KEY")
CATCH_UP_MINUTES = 30      # started late (restart, reboot)? still post inside this window
ATTEMPTS = 3               # tries per morning, only for failures before Enter was pressed
RETRY_PAUSE = 300
TEXTBOX = "[role='textbox']"

CITIES = config.CITIES
WEATHER_CODES = config.WEATHER_CODES


class SendUnconfirmed(Exception):
    """Enter was pressed but the chat did not take the message. Never retried: it may have gone out."""


def moscow_now():
    return datetime.now(MSK)


def log(*args):
    print(moscow_now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def short(e):
    """First line of an exception; Playwright errors carry a long call log after it."""
    return f"{type(e).__name__}: {str(e).strip().splitlines()[0] if str(e).strip() else ''}"[:300]


def type_multiline(page, text, delay=0):
    # Enter sends the message, so line breaks must be typed as Shift+Enter
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=delay)
        if i < len(lines) - 1:
            page.keyboard.press("Shift+Enter")


def wait_sent(page, timeout_ms=20000):
    """MAX empties the composer once it accepts a message; text left there means it was not sent."""
    try:
        page.wait_for_function(
            "sel => { const t = document.querySelector(sel); return !!t && t.innerText.trim() === ''; }",
            arg=TEXTBOX, timeout=timeout_ms)
    except Exception:
        raise SendUnconfirmed("после Enter текст остался в поле ввода")


def send_message_with_pic(page, message_content, image_path):
    """Photo with the text as its caption. Any error raised before Enter is safe to retry."""
    page.locator("button:has(use[href='#icon_attachment'])").first.click(timeout=15000)
    log("✓ Кнопка прикрепления нажата")
    photo_button = page.locator("[role='menuitem']:has(use[href='#icon_image'])").first
    with page.expect_file_chooser(timeout=15000) as fc_info:
        photo_button.click(timeout=15000)
    fc_info.value.set_files(image_path)
    log("✓ Файл выбран")
    time.sleep(3)  # upload and preview

    page.locator(TEXTBOX).first.click(timeout=15000)
    type_multiline(page, message_content, delay=50)
    log("✓ Текст введён")
    time.sleep(1)

    page.keyboard.press("Enter")
    wait_sent(page)
    log("✓ Сообщение с фото отправлено")


def send_message(page, text):
    box = page.wait_for_selector(TEXTBOX, timeout=30000)
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    type_multiline(page, text)
    page.keyboard.press("Enter")
    wait_sent(page)
    log("✓ Текстовое сообщение отправлено")


def get_weather_summary():
    today = moscow_now().strftime("%Y-%m-%d")
    lines = []
    temps_for_clothes = []

    for city, (lat, lon) in CITIES.items():
        url = (
            f"{config.URL_WEATHER}"
            f"latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,windspeed_10m,weathercode"
            f"&timezone=auto"
        )

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # Проверяем Content-Type
            if 'application/json' not in response.headers.get('Content-Type', ''):
                print(f"⚠️ {city}: API вернул не JSON, а {response.headers.get('Content-Type')}")
                print(f"   Текст ответа: {response.text[:200]}")
                lines.append(f"{city}: ошибка получения данных")
                continue
                
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ {city}: Ошибка запроса - {e}")
            lines.append(f"{city}: ошибка соединения")
            continue
        except ValueError as e:
            print(f"❌ {city}: Ошибка парсинга JSON - {e}")
            print(f"   Текст ответа: {response.text[:200]}")
            lines.append(f"{city}: ошибка данных")
            continue

        hourly = data.get("hourly")
        if not hourly:
            print(f"⚠️ {city}: Нет данных hourly в ответе")
            lines.append(f"{city}: нет данных")
            continue

        temps, winds, codes = [], [], []

        for t, temp, wind, code in zip(
            hourly.get("time", []),
            hourly.get("temperature_2m", []),
            hourly.get("windspeed_10m", []),
            hourly.get("weathercode", [])
        ):
            if t and t.startswith(today):
                temps.append(temp)
                winds.append(wind)
                codes.append(code)

        if not temps:
            lines.append(f"{city}: нет данных за сегодня")
            continue

        t_min = round(min(temps), 1)
        t_max = round(max(temps), 1)
        w_avg = round(sum(winds) / len(winds), 1) if winds else 0
        
        # Безопасное получение описания погоды
        if codes:
            most_common_code = max(set(codes), key=codes.count)
            desc = WEATHER_CODES.get(most_common_code, "неизвестно")
        else:
            desc = "нет данных"

        lines.append(f"{city}: {t_min}…{t_max}°C, ветер {w_avg} км/ч, {desc}")
        temps_for_clothes += [t_min, t_max]

    if not temps_for_clothes:
        # Если нет данных ни по одному городу, используем значения по умолчанию
        print("⚠️ Нет данных о погоде, использую значения по умолчанию")
        clothes = "одевайтесь по погоде"
        lines = ["Погода: данные недоступны"]
    else:
        avg_temp = sum(temps_for_clothes) / len(temps_for_clothes)

        if avg_temp < -10:
            clothes = "тёплая зимняя куртка, шапка, варежки, шарф"
        elif avg_temp < 0:
            clothes = "зимняя куртка, шапка, перчатки"
        elif avg_temp < 10:
            clothes = "лёгкая куртка или толстовка"
        elif avg_temp < 18:
            clothes = "ветровка или худи"
        else:
            clothes = "лёгкая одежда"

    return lines, clothes


def build_message_with_ai():
    weather_lines, clothes = get_weather_summary()
    top_lines, extra_lines = build_extras()
    parts = []
    if top_lines:
        parts.append("\n".join(top_lines))
    parts.append("Погода на сегодня:\n" + "\n".join(weather_lines))
    if extra_lines:
        parts.append("\n".join(extra_lines))
    parts.append(f"Рекомендация по одежде: {clothes}")
    raw_text = "\n\n".join(parts)
    log("Текст поста:\n" + raw_text)
    return AIDescriptionGeneratorQwenVL().generate_viral_description(original_text=raw_text)


def open_chat(page):
    page.goto(CHAT_URL, timeout=60000)
    try:
        page.wait_for_selector(TEXTBOX, timeout=60000)
    except Exception:
        raise RuntimeError("поле ввода не появилось — возможно, слетел вход в MAX (max_profile)")


def already_posted_today(page):
    """Today's post always carries the date line from extras.date_line()."""
    now = moscow_now()
    time.sleep(5)  # let the latest messages render
    return page.get_by_text(f"Сегодня {now.day} {MONTHS[now.month - 1]}", exact=False).count() > 0


def run_once():
    """Builds and sends one post. Returns 'photo', 'text' (the photo path failed)
    or, on the standby, 'already' when today's post is in the chat."""
    purge_old_images()
    msg = build_message_with_ai()
    image_path = None
    try:
        image_path = download_random_image(pick_photo_topic())
    except Exception as e:
        log(f"⚠ Картинка не скачалась: {short(e)}")

    try:
        with sync_playwright() as p:
            # Started for the post only: a Chromium kept open for weeks grew past 1 GB of RAM.
            browser = p.chromium.launch_persistent_context(
                PROFILE_DIR, headless=True, viewport={"width": 1280, "height": 900})
            try:
                page = browser.new_page()
                open_chat(page)
                if ROLE == "standby" and already_posted_today(page):
                    return "already"
                if image_path:
                    try:
                        send_message_with_pic(page, msg, image_path)
                        return "photo"
                    except SendUnconfirmed:
                        raise
                    except Exception as e:
                        log(f"⚠ Фото не отправилось ({short(e)}), отправляю текстом")
                        open_chat(page)  # reload drops the half-made attachment
                send_message(page, msg)
                return "text"
            finally:
                browser.close()
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


def posted_today():
    try:
        with open(LAST_POST_FILE, encoding="utf-8") as f:
            return f.read().strip() == moscow_now().date().isoformat()
    except FileNotFoundError:
        return False


def mark_day_done():
    with open(LAST_POST_FILE, "w", encoding="utf-8") as f:
        f.write(moscow_now().date().isoformat())


def seconds_until_post():
    now = moscow_now()
    target = now.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
    if posted_today() or now > target + timedelta(minutes=CATCH_UP_MINUTES):
        target += timedelta(days=1)
    elif now >= target:
        return 0
    return (target - now).total_seconds()


def wait_for_post_time():
    wait = seconds_until_post()
    if wait > 0:
        log(f"Следующий пост: {(moscow_now() + timedelta(seconds=wait)):%Y-%m-%d %H:%M} МСК")
    while (wait := seconds_until_post()) > 0:
        time.sleep(min(wait, 300))


def primary_posted_today():
    try:
        with open(PRIMARY_MARKER, encoding="utf-8") as f:
            return f.read().strip() == moscow_now().date().isoformat()
    except FileNotFoundError:
        return False


def _ssh_cmd():
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
    if STANDBY_SSH_KEY:
        cmd += ["-i", STANDBY_SSH_KEY, "-o", "IdentitiesOnly=yes"]
    return cmd


def notify_standby():
    """Primary only, after a confirmed post: marker first (it is what stops the standby),
    then the MAX login without caches. Never raises; a failure means the standby will check the chat."""
    if ROLE != "primary" or not STANDBY_HOST:
        return
    today = moscow_now().date().isoformat()
    steps = [
        ("метка", _ssh_cmd() + [STANDBY_HOST,
                                f"mkdir -p {STANDBY_DIR}/state && echo {today} > {STANDBY_DIR}/state/primary_done"], 60),
        ("вход MAX", ["rsync", "-a", "--delete", "--exclude=*Cache*", "--exclude=*cache*",
                      "--exclude=Singleton*", "-e", shlex.join(_ssh_cmd()),
                      PROFILE_DIR + "/", f"{STANDBY_HOST}:{STANDBY_DIR}/max_profile/"], 600),
    ]
    for name, cmd, timeout in steps:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout).strip()[:200] or f"код {r.returncode}")
            log(f"✓ Резерв: {name} обновлена" if name == "метка" else f"✓ Резерв: {name} скопирован")
        except Exception as e:
            log(f"⚠ Резерв: {name} — {short(e)}")
            alert(f"⚠️ Не удалось обновить резервный сервер ({name}): {short(e)}. "
                  "Завтра резерв проверит чат сам, двойного поста не будет.")
            return


def post_today():
    """Up to ATTEMPTS tries; the day is marked done afterwards whatever happened, so it is never posted twice."""
    try:
        if ROLE == "standby" and primary_posted_today():
            log("Основной сервер отправил пост — резерв не нужен")
            return
        for attempt in range(1, ATTEMPTS + 1):
            try:
                result = run_once()
                if result == "already":
                    log("Пост уже в чате — резерв не нужен")
                    alert("ℹ️ Сегодняшний пост в чате есть, а метки от aak-first нет "
                          "(сбой связи aak-first → horek_fi или неподтверждённая отправка). Повторно не отправляю.")
                    return
                heartbeat()
                if result == "text":
                    alert("⚠️ Пост ушёл без картинки: прикрепить фото не получилось. Подробности в logs/family.log")
                if ROLE == "standby":
                    alert("⚠️ aak-first не отправил пост к 06:40 — его отправил резервный сервер horek_fi.")
                log("=== Готово! ===")
                notify_standby()
                return
            except SendUnconfirmed as e:
                # No marker: the standby will look at the chat and post only if this one did not go out.
                alert(f"⚠️ Не уверен, что пост ушёл ({e}). Резервный сервер проверит чат в 06:40.")
                return
            except Exception as e:
                log(f"❌ Попытка {attempt}/{ATTEMPTS}: {short(e)}\n{traceback.format_exc()}")
                if attempt == ATTEMPTS:
                    alert(f"❌ Пост не отправлен после {ATTEMPTS} попыток: {short(e)}")
                    return
                time.sleep(RETRY_PAUSE)
    finally:
        mark_day_done()


def main_loop():
    if not CHAT_URL:
        raise SystemExit("CHAT_URL_FAM не задан в .env")
    os.makedirs(STATE_DIR, exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Уже работает другой экземпляр — выхожу")
        return
    log(f"Запущен ({ROLE}), PID {os.getpid()}")
    while True:
        try:
            wait_for_post_time()
            post_today()
        except Exception as e:
            # Keep the loop alive whatever happens; a dead process would miss every following day.
            log(f"Неожиданная ошибка: {short(e)}\n{traceback.format_exc()}")
            alert(f"❌ Неожиданная ошибка в цикле: {short(e)}")
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
