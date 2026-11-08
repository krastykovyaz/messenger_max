import requests
import config


class AIDescriptionGeneratorQwenVL:
    """
    Генератор утренних сообщений через Ollama (синхронный)
    """

    def __init__(self, ollama_url: str = config.OLLAMA_ADDRESS):
        self.ollama_url = ollama_url
        self.model = config.OLLAMA_MODEL

    def _ollama_raw_request(self, payload: dict) -> str:
        try:
            r = requests.post(self.ollama_url, json=payload, timeout=150)  # a cold 12B model on aak-llm needs ~70 s
            r.raise_for_status()
            return r.json().get("response", "")
        except Exception as e:
            print(f"[AI ERROR] Ошибка запроса к Ollama: {e}")
            return ""

    def _ollama_generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        return self._ollama_raw_request(payload)

    def generate_viral_description(self, original_text: str) -> str:
        """A short warm greeting from the model, followed by the data exactly as given.
        The model never rewrites the data lines, so none of them can be dropped or changed."""
        greeting = ""
        try:
            greeting = self._ollama_generate(self._build_prompt(original_text)).strip()
        except Exception as e:
            print(f"[AI ERROR] Ошибка генерации: {e}")
        if not greeting or len(greeting) > 400:
            return self._fallback(original_text)
        return f"{greeting}\n\n{original_text}"

    def _fallback(self, original_text: str) -> str:
        return f"Доброе утро! {original_text}"

    def _build_prompt(self, original_text: str) -> str:
        return f"""
Напиши короткое тёплое утреннее приветствие для семейного чата (родители, бабушка).
Ниже сводка на сегодня — она будет отправлена целиком сразу после твоего текста,
поэтому НЕ повторяй из неё цифры и данные, а только откликнись на настроение дня
(погода, праздник или день рождения, если есть).

Сводка:
{original_text}

ТРЕБОВАНИЯ:
- 1–2 предложения, не больше 300 символов
- 1–2 уместных эмодзи
- Спокойный, заботливый тон, как от близкого человека
- Без HTML, хештегов, ссылок, капса и рекламного стиля

Верни только текст приветствия.
""".strip()


if __name__ == '__main__':
    a = AIDescriptionGeneratorQwenVL()
    print(a.generate_viral_description("Погода + пробки + одежда"))
