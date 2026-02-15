from playwright.sync_api import sync_playwright
import time
import config

PROFILE_DIR = "max_profile"
CHAT_URL = config.CHAT_URL_ME
MESSAGE = "Привет тест3"

SELECTORS = [
    "[contenteditable='true']",
    "[role='textbox']",
    "div[contenteditable]",
    "div[class*='input']",
    "div[class*='editor']",
]

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        viewport={"width": 1280, "height": 900}
    )

    page = browser.new_page()
    page.goto(CHAT_URL)

    input_box = None

    # for selector in SELECTORS:
    #     try:
    input_box = page.wait_for_selector(SELECTORS[1], timeout=3000)
    # print(f"----{}-----")
    # if input_box:
    #     print(f"==========-{selector}-==========")
    #     break
    #     except:
    #         pass

    if not input_box:
        raise Exception("Поле ввода не найдено. Нужно посмотреть DOM.")

    input_box.click()
    page.keyboard.type(MESSAGE)
    page.keyboard.press("Enter")

    time.sleep(2)
