from dotenv import load_dotenv
import os
load_dotenv()

OLLAMA_ADDRESS = os.getenv('OLLAMA_ADDRESS')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL')
UNSPLASH_KEY = os.getenv("UNSPLASH_KEY")

CHAT_URL_FAM = os.getenv("CHAT_URL_FAM")
CHAT_URL_ME = os.getenv("CHAT_URL_ME")
CHAT_URL_KEK = os.getenv("CHAT_URL_KEK")

URL_WEATHER="https://api.open-meteo.com/v1/forecast?"
URL_TRAFFIC="https://yandex.ru/maps/api/traffic/jams"

CITIES = {
    "Санкт‑Петербург": (59.9386, 30.3141),
}

WEATHER_CODES = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь", 51: "лёгкая морось", 53: "морось",
    55: "сильная морось", 61: "лёгкий дождь", 63: "дождь", 65: "сильный дождь",
    71: "лёгкий снег", 73: "снег", 75: "сильный снег", 80: "ливни", 95: "гроза",
}