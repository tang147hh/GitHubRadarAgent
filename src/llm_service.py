from __future__ import annotations

from typing import Optional

import requests


class LLMService:
    """Minimal OpenAI-compatible Chat Completions client."""

    WARNING_PREFIX = "LLM_WARNING:"

    def __init__(
        self,
        api_key: Optional[str],
        base_url: Optional[str],
        model: Optional[str],
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.last_warning: Optional[str] = None

    def is_available(self) -> bool:
        return bool(self.api_key and self.model)

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        if not self.is_available():
            warning = "LLM unavailable: OPENAI_API_KEY or OPENAI_MODEL is not configured."
            self.last_warning = warning
            return f"{self.WARNING_PREFIX} {warning}"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty assistant message")
            self.last_warning = None
            return content.strip()
        except Exception as exc:  # pragma: no cover - depends on remote LLM service
            warning = f"LLM request failed, fallback will be used: {exc}"
            self.last_warning = warning
            return f"{self.WARNING_PREFIX} {warning}"
