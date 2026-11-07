"""Extra lines for the morning post: rain, evening temp, pressure, moon, date, FX, birthdays.

Every block is independent: if one fails it is skipped, the post is still sent.
"""
from datetime import datetime, timedelta

import requests
import config

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

# (month, day) -> name, loaded from birthdays.json (kept out of git, the repo is public)
BIRTHDAYS = getattr(config, "BIRTHDAYS", {})

HOLIDAYS = getattr(config, "HOLIDAYS", {
    # Официальные нерабочие праздничные дни РФ
    (1, 1): "Новый год", (1, 2): "новогодние каникулы", (1, 3): "новогодние каникулы",
    (1, 4): "новогодние каникулы", (1, 5): "новогодние каникулы", (1, 6): "новогодние каникулы",
    (1, 7): "Рождество Христово", (1, 8): "новогодние каникулы",
    (2, 23): "День защитника Отечества", (3, 8): "Международный женский день",
    (5, 1): "Праздник Весны и Труда", (5, 9): "День Победы",
    (6, 12): "День России", (11, 4): "День народного единства",
    # Популярные памятные даты
    (1, 14): "Старый Новый год", (1, 25): "Татьянин день", (2, 14): "День святого Валентина",
    (4, 12): "День космонавтики", (5, 24): "День славянской письменности",
    (6, 22): "День памяти и скорби", (7, 8): "День семьи, любви и верности",
    (9, 1): "День знаний", (10, 5): "День учителя", (12, 31): "Новогодняя ночь",
})


def _moscow_now():
    return datetime.utcnow() + timedelta(hours=3)


def date_line():
    now = _moscow_now()
    line = f"Сегодня {now.day} {MONTHS[now.month - 1]}, {WEEKDAYS[now.weekday()]}"
    hol = HOLIDAYS.get((now.month, now.day))
    if hol:
        line += f" — {hol}"
    return line


def birthday_lines(days_ahead=3):
    today = _moscow_now().date()
    out = []
    for offset in range(days_ahead + 1):
        d = today + timedelta(days=offset)
        name = BIRTHDAYS.get((d.month, d.day))
        if not name:
            continue
        if offset == 0:
            out.append(f"🎂 Сегодня день рождения: {name}! Поздравляем!")
        elif offset == 1:
            out.append(f"🎂 Завтра день рождения: {name}")
        else:
            out.append(f"🎂 Через {offset} дн. ({d.day:02d}.{d.month:02d}) день рождения: {name}")
    return out


def moon_phase():
    # Simple synodic-month approximation (reference new moon: 2000-01-06 18:14 UTC)
    days = (datetime.utcnow() - datetime(2000, 1, 6, 18, 14)).total_seconds() / 86400
    age = days % 29.530588853
    frac = age / 29.530588853
    names = ["новолуние", "растущая луна", "первая четверть", "растущая луна",
             "полнолуние", "убывающая луна", "последняя четверть", "убывающая луна"]
    idx = int((frac * 8) + 0.5) % 8
    return names[idx]


def weather_extras():
    """Rain chance, evening temperature, pressure + trend for the first city."""
    city, (lat, lon) = next(iter(config.CITIES.items()))
    url = (f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
           f"&hourly=temperature_2m,precipitation_probability,precipitation,surface_pressure"
           f"&timezone=Europe%2FMoscow&past_days=1&forecast_days=1")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    h = r.json()["hourly"]
    today = _moscow_now().strftime("%Y-%m-%d")
    allrows = list(zip(h["time"], h["temperature_2m"], h["precipitation_probability"],
                       h["precipitation"], h["surface_pressure"]))
    rows = [r_ for r_ in allrows if r_[0].startswith(today)]
    yday = (_moscow_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    y_morning = next((r_[4] for r_ in allrows if r_[0] == f"{yday}T06:00"), None)
    lines = []

    # Rain
    wet = [(t[11:16], pp) for t, _, pp, pr, _ in rows if (pp or 0) >= 50 or (pr or 0) >= 0.2]
    max_pp = max((pp or 0) for _, _, pp, _, _ in rows)
    if wet:
        lines.append(f"☔ Возьмите зонт: дождь вероятен с {wet[0][0]} (до {max_pp}%)")
    else:
        lines.append(f"☂ Дождя не ожидается (макс. вероятность {max_pp}%)")

    # Evening temperature
    ev = next((tp for t, tp, *_ in rows if t.endswith("18:00")), None)
    if ev is not None:
        lines.append(f"🌆 Вечером в 18:00: {round(ev)}°C")

    # Pressure + trend (hPa -> mmHg)
    mm = lambda v: round(v * 0.750062)
    morning = next((ps for t, _, _, _, ps in rows if t.endswith("06:00")), None)
    evening = next((ps for t, _, _, _, ps in rows if t.endswith("18:00")), None)
    if morning is not None:
        trend = ""
        if evening is not None:
            diff = mm(evening) - mm(morning)
            trend = " (к вечеру растёт ↑)" if diff >= 2 else " (к вечеру падает ↓)" if diff <= -2 else " (стабильное)"
        vs = ""
        if y_morning is not None:
            d = mm(morning) - mm(y_morning)
            vs = f", {'+' if d > 0 else ''}{d} к вчера" if d else ", как вчера"
        lines.append(f"🎣 Давление {mm(morning)} мм рт. ст.{vs}{trend}")
    lines.append(f"🌙 {moon_phase().capitalize()}")
    return lines


def water_line():
    lat, lon = getattr(config, "WATER_POINT", (59.95, 29.9))  # Финский залив у СПб
    url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
           f"&hourly=sea_surface_temperature&timezone=Europe%2FMoscow&forecast_days=1")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    h = r.json()["hourly"]
    vals = [v for t, v in zip(h["time"], h["sea_surface_temperature"]) if v is not None]
    if not vals:
        return None
    return f"🌊 Вода в Финском заливе: {round(sum(vals) / len(vals), 1)}°C"


def fx_line():
    r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
    r.raise_for_status()
    v = r.json()["Valute"]
    return f"💱 Курс ЦБ: USD {v['USD']['Value']:.2f} ₽, EUR {v['EUR']['Value']:.2f} ₽"


HOLIDAY_PHOTOS = {
    (1, 1): "new year fireworks", (12, 31): "new year eve", (1, 7): "christmas winter",
    (1, 14): "winter night lights", (2, 14): "valentines hearts", (2, 23): "snowy field sunrise",
    (3, 8): "spring flowers tulips", (4, 12): "space rocket stars", (5, 1): "spring blossom",
    (5, 9): "red tulips memorial", (6, 12): "russian landscape summer", (9, 1): "school autumn leaves",
    (10, 5): "autumn books", (11, 4): "saint petersburg architecture",
}


def _weather_code_today():
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get(f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
                     f"&daily=weathercode&timezone=Europe%2FMoscow&forecast_days=1", timeout=10)
    r.raise_for_status()
    return r.json()["daily"]["weathercode"][0]


def pick_photo_topic():
    """Unsplash search query that matches the day: birthday > holiday > weather > season."""
    now = _moscow_now()
    key = (now.month, now.day)
    if key in BIRTHDAYS:
        return "birthday cake balloons"
    if key in HOLIDAY_PHOTOS:
        return HOLIDAY_PHOTOS[key]
    season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
              6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}[now.month]
    try:
        code = _weather_code_today()
    except Exception as e:
        print(f"[extras] photo weather: {e}")
        code = None
    if code in (71, 73, 75, 77, 85, 86):
        return "snowy landscape"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain city street"
    if code in (45, 48):
        return "foggy morning forest"
    if code in (95, 96, 99):
        return "storm clouds"
    if code in (0, 1):
        return f"{season} sunrise nature"
    return f"{season} landscape"


def build_extras():
    """Returns (top_lines, extra_lines)."""
    top, extra = [], []
    for fn, bucket in ((date_line, top),):
        try:
            bucket.append(fn())
        except Exception as e:
            print(f"[extras] {fn.__name__}: {e}")
    try:
        top += birthday_lines()
    except Exception as e:
        print(f"[extras] birthdays: {e}")
    try:
        extra += weather_extras()
    except Exception as e:
        print(f"[extras] weather_extras: {e}")
    try:
        w = water_line()
        if w:
            extra.append(w)
    except Exception as e:
        print(f"[extras] water: {e}")
    try:
        extra.append(fx_line())
    except Exception as e:
        print(f"[extras] fx: {e}")
    return top, extra


if __name__ == "__main__":
    t, e = build_extras()
    print("\n".join(t)); print(); print("\n".join(e))
