import os
import random
import time
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

def purge_old_images(max_age_days=2):
    """Pictures are deleted after each post; this sweeps up any left behind by a crash."""
    if not os.path.isdir(SAVE_DIR):
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for name in os.listdir(SAVE_DIR):
        path = os.path.join(SAVE_DIR, name)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed += 1
    return removed


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
