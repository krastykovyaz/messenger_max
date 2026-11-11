"""Extra lines for the morning post: date, holidays (fixed and Easter-based), day off or working day,
New Year countdown, birthdays, name days, ice warning, rain, evening temp, Friday weekend outlook,
pressure, fishing score, magnetic storms, moon, dacha tip, daylight, UV, pollen, water, FX.

Every block is independent: if one fails it is skipped, the post is still sent.
"""
import json
import os
from datetime import date, datetime, timedelta

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


def orthodox_easter(year):
    """Orthodox Easter as a Gregorian date (Meeus' Julian algorithm + 13 days, valid 1900-2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


MASLENITSA_DAYS = ["Встреча", "Заигрыш", "Лакомка", "Разгуляй",
                   "Тёщины вечёрки", "Золовкины посиделки", "Прощёное воскресенье"]


def movable_holiday(d):
    """Easter-based holiday on date d as (name, photo topic), or None."""
    delta = (d - orthodox_easter(d.year)).days
    if -55 <= delta <= -49:   # the week before Clean Monday (Easter - 48)
        return f"Масленица: {MASLENITSA_DAYS[delta + 55]}", "russian pancakes blini"
    return {
        -7: ("Вербное воскресенье", "willow branches spring"),
        0: ("Пасха", "easter eggs"),
        49: ("Троица", "birch forest summer"),
    }.get(delta)


def date_line():
    now = _moscow_now()
    line = f"Сегодня {now.day} {MONTHS[now.month - 1]}, {WEEKDAYS[now.weekday()]}"
    names = [n for n in ((movable_holiday(now.date()) or (None,))[0],
                         HOLIDAYS.get((now.month, now.day))) if n]
    if names:
        line += " — " + "; ".join(names)
    return line


def day_type_line():
    """Holiday day-off transfers from isdayoff.ru: only unusual days get a line."""
    d = _moscow_now().date()
    r = requests.get(f"https://isdayoff.ru/{d:%Y%m%d}?pre=1", timeout=10)
    r.raise_for_status()
    code = r.text.strip()   # 0 working, 1 day off, 2 shortened (day before a holiday)
    weekend = d.weekday() >= 5
    if code == "0" and weekend:
        return "🗓 Сегодня рабочий день (перенос выходного)"
    if code == "1" and not weekend:
        return "🗓 Сегодня выходной день"
    if code == "2":
        return "🗓 Сегодня сокращённый рабочий день"
    return None


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


def plural(n, forms):
    """Russian plural: plural(5, ("день", "дня", "дней")) -> "дней"."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def new_year_line():
    d = _moscow_now().date()
    if d.month != 12 or d.day == 31:
        return None
    left = (date(d.year + 1, 1, 1) - d).days
    return f"🎄 До Нового года {left} {plural(left, ('день', 'дня', 'дней'))}"


def _load_namedays():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "namedays.json")
    with open(path, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def nameday_line():
    d = _moscow_now()
    names = _load_namedays().get(f"{d.day:02d}.{d.month:02d}")
    return f"😇 Именины: {', '.join(names)}" if names else None


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
           f"&hourly=temperature_2m,precipitation_probability,precipitation,surface_pressure,weathercode,windspeed_10m"
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

    # Ice: freezing rain today, or the temperature crossed 0°C overnight after rain or snow
    night = [(tp, pr) for t, tp, _, pr, _ in allrows if f"{yday}T12:00" <= t <= f"{today}T12:00"]
    codes_today = [c for t, c in zip(h["time"], h["weathercode"]) if t.startswith(today)]
    if ice_risk(night, codes_today):
        lines.append("⚠️ Возможен гололёд — осторожно на улице!")

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

    # Weekend outlook, Fridays only
    if _moscow_now().weekday() == 4:
        w = _safe(weekend_line)
        if w:
            lines.append(w)

    # Pressure + trend (hPa -> mmHg)
    mm = lambda v: round(v * 0.750062)
    morning = next((ps for t, _, _, _, ps in rows if t.endswith("06:00")), None)
    evening = next((ps for t, _, _, _, ps in rows if t.endswith("18:00")), None)
    dp_day = dp_24h = None
    if morning is not None:
        trend = ""
        if evening is not None:
            dp_day = mm(evening) - mm(morning)
            trend = " (к вечеру растёт ↑)" if dp_day >= 2 else " (к вечеру падает ↓)" if dp_day <= -2 else " (стабильное)"
        vs = ""
        if y_morning is not None:
            dp_24h = mm(morning) - mm(y_morning)
            vs = f", {'+' if dp_24h > 0 else ''}{dp_24h} к вчера" if dp_24h else ", как вчера"
        lines.append(f"⏲ Давление {mm(morning)} мм рт. ст.{vs}{trend}")

    # Fishing score from pressure stability, daytime wind and the moon
    winds = [w for t, w in zip(h["time"], h["windspeed_10m"])
             if t.startswith(today) and "06:00" <= t[11:16] <= "20:00" and w is not None]
    if dp_day is not None or dp_24h is not None:
        label, why = fishing_score(dp_day, dp_24h, sum(winds) / len(winds) if winds else None, moon_phase())
        lines.append(f"🎣 Клёв: {label}" + (f" ({', '.join(why)})" if why else ""))
    return lines


def fishing_score(dp_day, dp_24h, wind_kmh, moon):
    """Folk rule of thumb: steady pressure and light wind are good, jumps and strong wind are bad."""
    score, why = 0, []
    changes = [abs(x) for x in (dp_day, dp_24h) if x is not None]
    if changes and max(changes) <= 2:
        score += 2
        why.append("давление стабильное")
    elif changes and max(changes) >= 5:
        score -= 2
        why.append("давление скачет")
    if wind_kmh is not None:
        if wind_kmh <= 12:
            score += 1
            why.append("слабый ветер")
        elif wind_kmh >= 30:
            score -= 1
            why.append("сильный ветер")
    if moon in ("новолуние", "полнолуние"):
        score -= 1
        why.append(moon)
    label = "хороший" if score >= 2 else "средний" if score >= 0 else "плохой"
    return label, why


def weekend_line():
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get(f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
                     f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max"
                     f"&timezone=Europe%2FMoscow&forecast_days=3", timeout=10)
    r.raise_for_status()
    d = r.json()["daily"]
    parts = []
    for i, name in ((1, "сб"), (2, "вс")):
        desc = config.WEATHER_CODES.get(d["weathercode"][i], "переменная погода")
        rain = d["precipitation_probability_max"][i]
        part = f"{name} {round(d['temperature_2m_min'][i])}…{round(d['temperature_2m_max'][i])}°C, {desc}"
        if rain is not None and rain >= 40:
            part += f" ({rain}%)"
        parts.append(part)
    return "📅 Выходные: " + "; ".join(parts)


def ice_risk(night, codes_today):
    """night: (temperature, precipitation) pairs from yesterday 12:00 to today 12:00."""
    if any(c in (56, 57, 66, 67) for c in codes_today if c is not None):   # freezing drizzle/rain
        return True
    temps = [t for t, _ in night if t is not None]
    precip = sum(p or 0 for _, p in night)
    return bool(temps) and min(temps) <= 0 < max(temps) and precip >= 0.3


def kp_line():
    """Planetary Kp from NOAA SWPC; only disturbed days (Kp 4+) get a line."""
    r = requests.get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json", timeout=15)
    r.raise_for_status()
    data = r.json()
    rows = data if data and isinstance(data[0], dict) else [dict(zip(data[0], row)) for row in data[1:]]
    today = _moscow_now().date()
    vals = [float(x["kp"]) for x in rows if x.get("kp") is not None and
            (datetime.fromisoformat(x["time_tag"][:19]) + timedelta(hours=3)).date() == today]
    if not vals:
        return None
    kp = max(vals)
    if kp >= 4.67:   # NOAA G1 starts at Kp 5- (4.67)
        k = round(kp)
        return f"🧲 Магнитная буря: до {k} баллов (G{min(5, k - 4)})"
    if kp >= 4.0:
        return "🧲 Геомагнитное поле возмущено: до 4 баллов"
    return None


def daylight_line():
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get(f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
                     f"&daily=sunrise,sunset,daylight_duration&timezone=Europe%2FMoscow"
                     f"&past_days=1&forecast_days=1", timeout=10)
    r.raise_for_status()
    d = r.json()["daily"]
    i = d["time"].index(_moscow_now().strftime("%Y-%m-%d"))
    dur = d["daylight_duration"][i]
    hours, mins = divmod(round(dur / 60), 60)
    line = f"🌅 Восход {d['sunrise'][i][11:16]}, закат {d['sunset'][i][11:16]}, день {hours} ч {mins:02d} мин"
    if i > 0 and d["daylight_duration"][i - 1]:
        diff = round((dur - d["daylight_duration"][i - 1]) / 60)
        if diff > 0:
            line += f" (прибавился на {diff} мин)"
        elif diff < 0:
            line += f" (убавился на {-diff} мин)"
    return line


def dacha_line():
    """Gardening tip by the moon, dacha season (April-September) only."""
    if not 4 <= _moscow_now().month <= 9:
        return None
    moon = moon_phase()
    if moon in ("новолуние", "полнолуние"):
        return f"🌱 Дача: {moon} — посадки лучше отложить, хороший день для прополки"
    if moon in ("растущая луна", "первая четверть"):
        return "🌱 Дача: луна растёт — время сеять и сажать то, что растёт над землёй"
    return "🌱 Дача: луна убывает — время для корнеплодов, обрезки и прополки"


def uv_line():
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get(f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
                     f"&daily=uv_index_max&timezone=Europe%2FMoscow&forecast_days=1", timeout=10)
    r.raise_for_status()
    uv = r.json()["daily"]["uv_index_max"][0]
    if uv is None or uv < 3:
        return None
    level = ("умеренный — кепка и крем от солнца" if uv < 6 else
             "высокий — крем SPF 30+, днём лучше в тени" if uv < 8 else
             "очень высокий — с 12 до 16 лучше не быть на солнце")
    return f"☀️ УФ-индекс {round(uv)}: {level}"


# grains/m³ thresholds (moderate, high) per plant
POLLEN = {"alder_pollen": ("ольха", 10, 100), "birch_pollen": ("берёза", 10, 100),
          "grass_pollen": ("злаки", 5, 50), "mugwort_pollen": ("полынь", 5, 50)}


def pollen_line():
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get("https://air-quality-api.open-meteo.com/v1/air-quality"
                     f"?latitude={lat}&longitude={lon}&hourly={','.join(POLLEN)}"
                     f"&timezone=Europe%2FMoscow&forecast_days=1", timeout=15)
    r.raise_for_status()
    h = r.json()["hourly"]
    parts = []
    for key, (name, moderate, high) in POLLEN.items():
        vals = [v for v in h.get(key, []) if v is not None]
        peak = max(vals) if vals else 0
        if peak >= high:
            parts.append(f"{name} — высокий уровень")
        elif peak >= moderate:
            parts.append(f"{name} — средний")
    return "🌼 Пыльца: " + ", ".join(parts) if parts else None


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
    movable = movable_holiday(now.date())   # Easter outranks a fixed date (e.g. 12 April 2026)
    if movable:
        return movable[1]
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


# (feels-like below this °C, advice); the first band that fits wins
CLOTHING_BANDS = [
    (-20, "пуховик, тёплая шапка, варежки, шарф, термобельё"),
    (-10, "тёплая зимняя куртка, шапка, варежки, шарф"),
    (-3, "зимняя куртка, шапка, перчатки, шарф"),
    (3, "тёплая куртка, шапка, перчатки"),
    (8, "демисезонная куртка, лёгкая шапка"),
    (13, "лёгкая куртка или плотная толстовка"),
    (18, "ветровка или худи"),
    (23, "футболка, на вечер лёгкая кофта"),
    (99, "лёгкая одежда, головной убор от солнца"),
]


def clothing_advice(feels_min, t_min, t_max, wind_max, rain, snow, ice, uv):
    """Pure rule: base outfit from the coldest feels-like temperature of the day, plus add-ons."""
    base = next(text for limit, text in CLOTHING_BANDS if feels_min < limit)
    extras_ = []
    if snow:
        extras_.append("зимняя обувь")
    elif rain:
        extras_.append("непромокаемая куртка и обувь, зонт")
    if ice:
        extras_.append("обувь с нескользящей подошвой")
    if wind_max is not None and wind_max >= 35:
        extras_.append("капюшон или куртка, закрытая от ветра")
    if t_max - t_min >= 8:
        extras_.append("оденьтесь слоями: днём заметно теплее")
    if uv is not None and uv >= 6:
        extras_.append("кепка и солнцезащитные очки")
    feels = round(feels_min)
    sign = "−" if feels < 0 else ""
    return (f"Рекомендация по одежде (ощущается как {sign}{abs(feels)}°C): "
            + "; ".join([base] + extras_))


def clothing_line():
    """Daytime (07-20) data for the first city: feels-like, rain/snow, wind, ice, UV."""
    city, (lat, lon) = next(iter(config.CITIES.items()))
    r = requests.get(f"{config.URL_WEATHER}latitude={lat}&longitude={lon}"
                     f"&hourly=temperature_2m,apparent_temperature,precipitation,snowfall,"
                     f"precipitation_probability,weathercode,windspeed_10m"
                     f"&daily=uv_index_max&timezone=Europe%2FMoscow&past_days=1&forecast_days=1", timeout=10)
    r.raise_for_status()
    data = r.json()
    h = data["hourly"]
    today = _moscow_now().strftime("%Y-%m-%d")
    yday = (_moscow_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = list(zip(h["time"], h["temperature_2m"], h["apparent_temperature"], h["precipitation"],
                    h["snowfall"], h["precipitation_probability"], h["weathercode"], h["windspeed_10m"]))
    day = [x for x in rows if x[0].startswith(today) and "07:00" <= x[0][11:16] <= "20:00"]
    if not day:
        return None
    temps = [x[1] for x in day if x[1] is not None]
    feels = [x[2] for x in day if x[2] is not None]
    if not temps or not feels:
        return None
    snow_codes = (71, 73, 75, 77, 85, 86)
    snow = sum(x[4] or 0 for x in day) >= 0.5 or any(x[6] in snow_codes for x in day)
    rain = not snow and (sum(x[3] or 0 for x in day) >= 0.5 or any((x[5] or 0) >= 60 for x in day))
    night = [(x[1], x[3]) for x in rows if f"{yday}T12:00" <= x[0] <= f"{today}T12:00"]
    ice = ice_risk(night, [x[6] for x in rows if x[0].startswith(today)])
    winds = [x[7] for x in day if x[7] is not None]
    uv = (data.get("daily", {}).get("uv_index_max") or [None])[0]
    return clothing_advice(min(feels), min(temps), max(temps), max(winds) if winds else None,
                           rain, snow, ice, uv)


def _safe(fn):
    """Runs one block; a failing source drops its line, never the post."""
    try:
        return fn()
    except Exception as e:
        print(f"[extras] {fn.__name__}: {type(e).__name__}: {e}")
        return None


def build_extras():
    """Returns (top_lines, extra_lines)."""
    top = ([_safe(date_line), _safe(day_type_line), _safe(new_year_line)]
           + (_safe(birthday_lines) or []) + [_safe(nameday_line)])
    extra = (_safe(weather_extras) or []) + [
        _safe(kp_line),
        f"🌙 {moon_phase().capitalize()}",
        _safe(dacha_line),
        _safe(daylight_line),
        _safe(uv_line),
        _safe(pollen_line),
        _safe(water_line),
        _safe(fx_line),
    ]
    return [x for x in top if x], [x for x in extra if x]


if __name__ == "__main__":
    t, e = build_extras()
    print("\n".join(t)); print(); print("\n".join(e))
