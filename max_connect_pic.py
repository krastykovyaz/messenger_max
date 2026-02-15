from playwright.sync_api import sync_playwright
from download_pics import download_random_image
import time
import os
import config

PROFILE_DIR = "max_profile"
CHAT_URL = config.CHAT_URL_KEK
MESSAGE = "Привет тест с картинкой"
# IMAGE_PATH = "Screenshot2026.png"
IMAGE_PATH = download_random_image()


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

    if not os.path.exists(IMAGE_PATH):
        raise FileNotFoundError(f"Файл не найден: {IMAGE_PATH}")
    print(f"✓ Файл найден: {IMAGE_PATH}")

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
    file_chooser.set_files(IMAGE_PATH)
    print("✓ Файл выбран")
    
    # 3. Ждём загрузки и появления превью
    time.sleep(3)
    # page.screenshot(path="debug_after_upload.png")
    
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
    page.keyboard.type(MESSAGE, delay=50)
    print("✓ Текст введён")
    
    time.sleep(1)
    page.screenshot(path="debug_before_send.png")

    # 5. Отправляем
    page.keyboard.press("Enter")
    print("✓ Сообщение отправлено")

    time.sleep(3)
    # page.screenshot(path="debug_after_send.png")
    
    browser.close()
    print("\n=== Готово! ===")

# if __name__=='__main__':
    