from typing import Optional
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
            r = requests.post(self.ollama_url, json=payload, timeout=300)
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
        prompt = self._build_prompt(original_text)

        try:
            response = self._ollama_generate(prompt)
            if not response:
                return self._fallback(original_text)
            return response.strip()
        except Exception as e:
            print(f"[AI ERROR] Ошибка генерации: {e}")
            return self._fallback(original_text)

    def _fallback(self, original_text: str) -> str:
        return f"Доброе утро! {original_text}"

    def _build_prompt(self, original_text: str) -> str:
        return f"""
Сформируй доброе, тёплое и заботливое утреннее сообщение для родителей на основе данных ниже.

Обязательно включи исходные данные в финальный текст в сжатом виде, без искажений:
{original_text}

ТРЕБОВАНИЯ:
- Стиль: спокойный, дружелюбный, поддерживающий, как от внимательного родителя
- Длина: 2–4 предложения
- Эмодзи: 1–3, уместные, без перебора
- Не использовать HTML, хештеги, ссылки, капс
- Не использовать призывы к действию
- Не использовать рекламный стиль
- Передай атмосферу спокойного начала дня
- Добавь мягкое пожелание хорошего дня
- Пиши естественно, как человек

Верни только финальный текст.
""".strip()


if __name__ == '__main__':
    a = AIDescriptionGeneratorQwenVL()
    print(a.generate_viral_description("Погода + пробки + одежда"))
