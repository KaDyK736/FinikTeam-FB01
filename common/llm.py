"""Клиент LLM через любой OpenAI-совместимый API: Ollama, Mistral, OpenRouter.

Провайдер меняется только переменными окружения, правок в коде не требуется:
    LLM_API_KEY        ключ провайдера (у локальной Ollama — любая непустая строка)
    LLM_BASE_URL       по умолчанию https://openrouter.ai/api/v1; локально http://localhost:11434/v1
    LLM_MODEL          модель, например qwen2.5:7b-instruct
    LLM_TEMPERATURE    по умолчанию 0.3
    LLM_MAX_TOKENS     по умолчанию 900
    LLM_TIMEOUT / LLM_MAX_RETRIES / LLM_RATE_ATTEMPTS / LLM_RATE_DELAY / LLM_PARSE_ATTEMPTS
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_client: AsyncOpenAI | None = None


class LlmNotConfigured(RuntimeError):
    pass


class LlmUnavailable(RuntimeError):
    """Провайдер недоступен: сеть, лимит или неверный ключ."""


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def get_base_url() -> str:
    return os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


def get_client() -> AsyncOpenAI:
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise LlmNotConfigured(
            "LLM_API_KEY не задан. Ключ берётся у выбранного провайдера "
            "(OpenRouter: https://openrouter.ai/keys, Mistral: https://console.mistral.ai) "
            "и добавляется в .env как LLM_API_KEY=..."
        )

    attribution = {
        "HTTP-Referer": os.getenv("LLM_REFERER", "https://localhost"),
        "X-Title": os.getenv("LLM_TITLE", "Faberlic FB01 client card bot"),
    }

    _client = AsyncOpenAI(
        api_key=api_key,
        base_url=get_base_url(),
        timeout=float(os.getenv("LLM_TIMEOUT", "90")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "0")),
        default_headers=attribution if "openrouter" in get_base_url() else {},
    )
    return _client


def get_model() -> str:
    model = os.getenv("LLM_MODEL", "").strip()
    if not model:
        raise LlmNotConfigured(
            "LLM_MODEL не задан. Пропишите модель в .env; список доступных: "
            "python scripts/check_llm.py models"
        )
    return model


def get_temperature() -> float:
    # При temperature=0 qwen2.5:7b зацикливается на длинном JSON и обрывает его мусором.
    return float(os.getenv("LLM_TEMPERATURE", "0.3"))


def parse_json_answer(raw: str) -> dict:
    raw = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    start, end = raw.find("{"), raw.rfind("}")
    candidates = [raw]
    if start != -1 and end > start:
        candidates.append(raw[start:end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as error:
            last = error

    raise ValueError(
        f"Модель вернула не JSON ({last}): {raw[:600]}"
    ) from last


async def chat(system_prompt: str, user_prompt: str) -> ChatResult:
    attempts = int(os.getenv("LLM_RATE_ATTEMPTS", "5"))
    delay = float(os.getenv("LLM_RATE_DELAY", "15"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "900"))

    for attempt in range(attempts):
        try:
            response = await get_client().chat.completions.create(
                model=get_model(),
                temperature=get_temperature(),
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            usage = response.usage
            return ChatResult(
                text=response.choices[0].message.content or "",
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
        except APIStatusError as error:
            limited = isinstance(error, RateLimitError) or error.status_code == 429
            if limited and attempt + 1 < attempts:
                await asyncio.sleep(delay * (attempt + 1))
                continue
            reason = "превышен лимит тарифа" if limited else f"HTTP {error.status_code}"
            raise LlmUnavailable(
                f"{reason} у {get_base_url()} (модель {get_model()}, попыток {attempt + 1}): {str(error)[:200]}"
            ) from error
        except APIConnectionError as error:
            cause = error.__cause__ or error
            raise LlmUnavailable(
                f"Нет связи с {get_base_url()}: {type(cause).__name__}: {str(cause)[:200]}"
            ) from error

    raise LlmUnavailable(f"Не получили ответ от {get_base_url()} за {attempts} попыток")


async def complete(system_prompt: str, user_prompt: str) -> str:
    return (await chat(system_prompt, user_prompt)).text


async def chat_json(system_prompt: str, user_prompt: str) -> tuple[dict, ChatResult]:
    """Битый JSON от локальной модели — обычное дело, поэтому пробуем ещё раз."""
    attempts = int(os.getenv("LLM_PARSE_ATTEMPTS", "3"))
    last_error: Exception | None = None
    answer = ChatResult(text="")

    for attempt in range(attempts):
        answer = await chat(system_prompt, user_prompt)
        try:
            return parse_json_answer(answer.text), answer
        except ValueError as error:
            last_error = error

    raise ValueError(f"Карточка не распарсилась за {attempts} попыток: {last_error}") from last_error


async def complete_json(system_prompt: str, user_prompt: str) -> dict:
    card, _ = await chat_json(system_prompt, user_prompt)
    return card


async def list_models() -> list[tuple[str, str]]:
    import httpx

    url = get_base_url().rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            response = await http.get(url, headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise LlmUnavailable(
                f"Провайдер не отдал список моделей: {error.response.status_code} {get_base_url()} "
                f"(проверь LLM_API_KEY и LLM_BASE_URL в .env)"
            ) from error
        except httpx.HTTPError as error:
            raise LlmUnavailable(f"Сеть недоступна: {type(error).__name__} {get_base_url()}") from error

    return sorted((item.get("id", ""), item.get("name", "")) for item in payload.get("data", []))
