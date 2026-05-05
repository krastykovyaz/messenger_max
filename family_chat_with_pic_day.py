from playwright.sync_api import sync_playwright
from download_pics import download_random_image
import time
import os
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

MESSAGE = "Привет тест с картинкой"

def send_message_with_pic(page, message_content, image_path):
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Файл не найден: {image_path}")
    print(f"✓ Файл найден: {image_path}")

    # 1. Кликаем на иконку скрепки
    attach_button = page.locator("button:has(svg):left-of([placeholder*='Сообщение'])").first
    attach_button.click()
    print("✓ Кнопка прикрепления нажата")
    time.sleep(0.5)
    
    # 2. Кликаем на "Фото или видео" в появившемся меню
    photo_button = page.locator("text='Фото или видео'").first
    
    # Ждём пока файловый диалог откроется и загружаем файл
    with page.expect_file_chooser() as fc_info:
        photo_button.click()
        print("✓ Кликнули на 'Фото или видео'")
    
    file_chooser = fc_info.value
    file_chooser.set_files(image_path)
    print("✓ Файл выбран")
    
    # 3. Ждём загрузки и появления превью
    time.sleep(3)
    
    # Проверяем превью
    try:
        preview = page.locator("img[src*='blob:'], div[class*='preview'], div[class*='media']").first
        if preview.is_visible(timeout=2000):
            print("✓ Превью картинки появилось")
        else:
            print("⚠ Превью не видно")
    except:
        print("⚠ Превью не найдено")

    # 4. Вводим текст
    input_box = page.locator("[placeholder*='Сообщение']").first
    input_box.click()
    page.keyboard.type(message_content, delay=50)
    print("✓ Текст введён")
    
    time.sleep(1)

    # 5. Отправляем
    page.keyboard.press("Enter")
    print("✓ Сообщение отправлено")
    if os.path.exists(image_path):
        os.remove(image_path)
    time.sleep(3)


def get_russian_holidays():
    """
    Получает информацию о праздниках и памятных датах в России.
    Использует API calendarific.com (бесплатный лимит: 1000 запросов/месяц)
    """
    try:
        # Получите бесплатный API ключ на https://calendarific.com/
        API_KEY = "YOUR_API_KEY_HERE"  # Замените на свой ключ
        
        today = datetime.utcnow() + timedelta(hours=3)  # Московское время
        year = today.year
        month = today.month
        day = today.day
        
        # API calendarific
        url = f"https://calendarific.com/api/v2/holidays?api_key={API_KEY}&country=RU&year={year}&month={month}&day={day}"
        
        response = requests.get(url, timeout=10)
        data = response.json()
        
        holidays = []
        if data.get("response") and data["response"].get("holidays"):
            for holiday in data["response"]["holidays"]:
                name = holiday.get("name", "")
                description = holiday.get("description", "")
                holiday_type = holiday.get("type", [])
                
                # Фильтруем только значимые праздники
                if "National holiday" in holiday_type or "Observance" in holiday_type:
                    holidays.append(name)
        
        return holidays if holidays else None
        
    except Exception as e:
        print(f"Ошибка при получении праздников: {e}")
        return None


def get_russian_holidays_alternative():
    """
    Альтернативный способ: используем API isdayoff.ru (бесплатный, без регистрации)
    Возвращает информацию о выходных и праздниках в России
    """
    try:
        today = datetime.utcnow() + timedelta(hours=3)  # Московское время
        date_str = today.strftime("%Y%m%d")
        
        # API isdayoff.ru: 0 - рабочий день, 1 - выходной, 2 - сокращенный
        url = f"https://isdayoff.ru/api/getdata?date={date_str}"
        response = requests.get(url, timeout=10)
        
        day_type = response.text.strip()
        
        # Дополнительно проверяем название праздника
        url_info = f"https://isdayoff.ru/{date_str}"
        
        # Простой словарь основных российских праздников
        holidays_dict = {
            "01-01": "Новый год",
            "01-02": "Новогодние каникулы",
            "01-03": "Новогодние каникулы",
            "01-04": "Новогодние каникулы",
            "01-05": "Новогодние каникулы",
            "01-06": "Новогодние каникулы",
            "01-07": "Рождество Христово",
            "01-08": "Новогодние каникулы",
            "02-23": "День защитника Отечества",
            "03-08": "Международный женский день",
            "05-01": "Праздник Весны и Труда",
            "05-09": "День Победы",
            "06-12": "День России",
            "11-04": "День народного единства",
        }
        
        month_day = today.strftime("%m-%d")
        holiday_name = holidays_dict.get(month_day)
        
        # Проверка на Масленицу и Пасху (переходящие праздники)
        # Для точного расчёта нужна библиотека easter
        try:
            from dateutil.easter import easter
            
            easter_date = easter(today.year)
            
            # Прощёное воскресенье - за день до начала Великого поста (за 48 дней до Пасхи)
            forgiveness_sunday = easter_date - timedelta(days=48)
            
            # Масленичная неделя - 7 дней перед Великим постом
            maslenitsa_start = easter_date - timedelta(days=55)
            maslenitsa_end = easter_date - timedelta(days=49)
            today_date = today.date()
            if today_date == forgiveness_sunday:
                return ["Прощёное воскресенье"]
            elif maslenitsa_start <= today_date <= maslenitsa_end:
                day_num = (today_date - maslenitsa_start).days + 1
                maslenitsa_days = {
                    1: "Масленица: Встреча",
                    2: "Масленица: Заигрыш",
                    3: "Масленица: Лакомка",
                    4: "Масленица: Разгуляй",
                    5: "Масленица: Тёщины вечерки",
                    6: "Масленица: Золовкины посиделки",
                    7: "Масленица: Прощёное воскресенье"
                }
                return [maslenitsa_days.get(day_num, "Масленичная неделя")]
            elif today_date == easter_date:
                return ["Пасха"]
                
        except ImportError:
            print("Установите python-dateutil для расчёта переходящих праздников: pip install python-dateutil")
        
        if holiday_name:
            return [holiday_name]
        elif day_type == "1":
            return ["Выходной день"]
        
        return None
        
    except Exception as e:
        print(f"Ошибка при получении информации о празднике: {e}")
        return None


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

    avg_temp = sum(temps_for_clothes) / (len(temps_for_clothes) + 10**(-6))

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
    
    # Получаем информацию о праздниках
    holidays = get_russian_holidays_alternative()
    holiday_text = ""
    if holidays:
        holiday_text = f"🎉 Сегодня: {', '.join(holidays)}\n\n"
    
    raw_text = (
        holiday_text
        + "Погода на сегодня:\n"
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
            try:
                image_path = download_random_image()
                send_message_with_pic(page, msg, image_path)
            except Exception as e:
                print(e)
                send_message(page, msg)
            print("\n=== Готово! ===")
            time.sleep(60)


if __name__ == "__main__":
    main_loop()
    # print(get_russian_holidays_alternative())
    # print(get_weather_summary())