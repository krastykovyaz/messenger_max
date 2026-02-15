import os
import random
import requests
import config

UNSPLASH_KEY = config.UNSPLASH_KEY
SAVE_DIR = "images"

TOPICS = [
    # Рыбалка
    "fishing", "river fishing", "lake", "boat", "nature morning", "water", "outdoor",

    # Город
    "city", "architecture", "urban", "street", "buildings", "night city",

    # Природа
    "nature", "landscape", "mountains", "forest", "river", "lake", "sunrise", "sunset"
]

def download_random_image():
    # выбираем случайную тему
    topic = random.choice(TOPICS)
    print(f"Выбрана тема: {topic}")

    # запрос к Unsplash
    url = "https://api.unsplash.com/photos/random"
    params = {
        "query": topic,
        "orientation": "landscape"
    }
    headers = {"Authorization": f"Client-ID {UNSPLASH_KEY}"}

    r = requests.get(url, params=params, headers=headers)
    r.raise_for_status()
    data = r.json()

    # ссылка на картинку
    img_url = data["urls"]["regular"]

    # создаём папку
    os.makedirs(SAVE_DIR, exist_ok=True)

    # имя файла
    filename = os.path.join(SAVE_DIR, f"{topic.replace(' ', '_')}_{data['id']}.jpg")

    # скачиваем картинку
    img = requests.get(img_url)
    img.raise_for_status()

    with open(filename, "wb") as f:
        f.write(img.content)

    print(f"Картинка сохранена: {filename}")
    return filename


if __name__ == "__main__":
    download_random_image()
