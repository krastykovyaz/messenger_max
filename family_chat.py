import time
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from ai_generator import AIDescriptionGeneratorQwenVL
import config

PROFILE_DIR = "max_profile"
CHAT_URL = config.CHAT_URL_FAM

SELECTORS = ["[role='textbox']"]

CITIES = config.CITIES

WEATHER_CODES = config.WEATHER_CODES


def get_weather_summary():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = []
    temps_for_clothes = []

    for city, (lat, lon) in CITIES.items():
        url = (
            f"{config.URL_WEATHER}"
            f"latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,windspeed_10m,weathercode"
            f"&timezone=auto"
        )

        data = requests.get(url).json()
        hourly = data["hourly"]

        temps, winds, codes = [], [], []

        for t, temp, wind, code in zip(
            hourly["time"],
            hourly["temperature_2m"],
            hourly["windspeed_10m"],
            hourly["weathercode"]
        ):
            if t.startswith(today):
                temps.append(temp)
                winds.append(wind)
                codes.append(code)

        if not temps:
            lines.append(f"{city}: нет данных")
            continue

        t_min = round(min(temps), 1)
        t_max = round(max(temps), 1)
        w_avg = round(sum(winds) / len(winds), 1)
        desc = WEATHER_CODES.get(max(set(codes), key=codes.count))

        lines.append(f"{city}: {t_min}…{t_max}°C, ветер {w_avg} км/ч, {desc}")
        temps_for_clothes += [t_min, t_max]

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


def get_spb_traffic():
    try:
        data = requests.get(config.URL_TRAFFIC).json()
        score = data["data"]["score"]
        return f"Пробки в Санкт‑Петербурге: {score}/10"
    except:
        return None


def build_message_with_ai():
    weather_lines, clothes = get_weather_summary()
    traffic = get_spb_traffic()
    traffic = traffic if traffic else ''
    raw_text = (
        "Погода на сегодня:\n"
        + "\n".join(weather_lines)
        + "\n\n"
        + traffic
        + "\n\n"
        f"Рекомендация по одежде: {clothes}"
    )
    print(raw_text)
    ai = AIDescriptionGeneratorQwenVL()
    final_text = ai.generate_viral_description(
        original_text=raw_text
    )

    # generate_viral_description возвращает корутину → вызываем .result()
    if hasattr(final_text, "result"):
        return final_text.result()

    return final_text


def send_message(page, text):
    input_box = None
    for selector in SELECTORS:
        try:
            input_box = page.wait_for_selector(selector, timeout=3000)
            if input_box:
                break
        except:
            pass

    if not input_box:
        raise Exception("Поле ввода не найдено")

    input_box.click()
    page.keyboard.type(text)
    page.keyboard.press("Enter")


def wait_until_6_moscow():
    while True:
        now = datetime.utcnow()
        moscow = now + timedelta(hours=3)
        print("Текущее московское время:", moscow)

        if moscow.hour == 6 and moscow.minute == 0:
            return

        time.sleep(30)


def main_loop():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=True,
            viewport={"width": 1280, "height": 900}
        )

        page = browser.new_page()

        while True:
            wait_until_6_moscow()
            page.goto(CHAT_URL)

            msg = build_message_with_ai()
            send_message(page, msg)

            time.sleep(60)


if __name__ == "__main__":
    main_loop()
