import os
import random
import requests
import config

UNSPLASH_KEY = config.UNSPLASH_KEY
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

TOPICS = [
    # Рыбалка
    "fishing", "river fishing", "lake", "boat", "nature morning", "water", "outdoor",

    # Город
    "city", "architecture", "urban", "street", "buildings", "night city",

    # Природа
    "nature", "landscape", "mountains", "forest", "river", "lake", "sunrise", "sunset"
]

def download_random_image(topic=None):
    try:
        return _download(topic or random.choice(TOPICS))
    except Exception as e:
        print(f"⚠ Тема '{topic}' не сработала ({e}), беру случайную")
        return _download(random.choice(TOPICS))


def _download(topic):
    print(f"Выбрана тема: {topic}")

    # запрос к Unsplash
    url = "https://api.unsplash.com/photos/random"
    params = {
        "query": topic,
        "orientation": "landscape"
    }
    headers = {"Authorization": f"Client-ID {UNSPLASH_KEY}"}

    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    # ссылка на картинку
    img_url = data["urls"]["regular"]

    # создаём папку
    os.makedirs(SAVE_DIR, exist_ok=True)

    # имя файла
    filename = os.path.join(SAVE_DIR, f"{topic.replace(' ', '_')}_{data['id']}.jpg")

    # скачиваем картинку
    img = requests.get(img_url, timeout=60)
    img.raise_for_status()

    with open(filename, "wb") as f:
        f.write(img.content)

    print(f"Картинка сохранена: {filename}")
    return filename


if __name__ == "__main__":
    download_random_image()
