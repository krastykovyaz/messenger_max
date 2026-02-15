from playwright.sync_api import sync_playwright
import time
import os
import config

PROFILE_DIR = "max_profile"
CHAT_URL = config.CHAT_URL_KEK
MESSAGE = "Привет тест с несколькими картинками"
IMAGE_PATHS = [
    "Screenshot2026.png",
    "Screenshot_2026.png",
    "Screenshot__2026.png"
]

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        viewport={"width": 1280, "height": 900}
    )

    page = browser.new_page()
    page.goto(CHAT_URL, wait_until="networkidle")
    print("✓ Страница загружена")
    time.sleep(2)

    # Проверяем что все файлы существуют
    for img_path in IMAGE_PATHS:
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"Файл не найден: {img_path}")
    print(f"✓ Все {len(IMAGE_PATHS)} файла найдены")

    # 1. Кликаем на иконку скрепки
    attach_button = page.locator("button:has(svg):left-of([placeholder*='Сообщение'])").first
    attach_button.click()
    print("✓ Кнопка прикрепления нажата")
    time.sleep(0.5)
    
    # 2. Кликаем на "Фото или видео" и загружаем ВСЕ файлы сразу
    photo_button = page.locator("text='Фото или видео'").first
    
    with page.expect_file_chooser() as fc_info:
        photo_button.click()
        print("✓ Кликнули на 'Фото или видео'")
    
    file_chooser = fc_info.value
    file_chooser.set_files(IMAGE_PATHS)  # Передаём список файлов
    print(f"✓ Загружено {len(IMAGE_PATHS)} файлов")
    
    # 3. Ждём загрузки всех превью
    time.sleep(4)
    
    # Проверяем количество превью
    previews = page.locator("img[src*='blob:'], div[class*='preview'], div[class*='media']").count()
    print(f"✓ Найдено {previews} превью")

    # 4. Вводим текст
    input_box = page.locator("[placeholder*='Сообщение']").first
    input_box.click()
    page.keyboard.type(MESSAGE, delay=50)
    print("✓ Текст введён")
    
    time.sleep(1)
    page.screenshot(path="debug_before_send.png")

    # 5. Отправляем
    page.keyboard.press("Enter")
    print("✓ Сообщение отправлено")

    time.sleep(3)
    page.screenshot(path="debug_after_send.png")
    
    browser.close()
    print("\n=== Готово! ===")