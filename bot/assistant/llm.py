"""Клиент LLM для бота: любой OpenAI-совместимый API (локальная Ollama, OpenRouter...).

Настраивается только переменными окружения (.env в папке bot):
    USE_LLM=1            включатель LLM-разбора; при 0 или ошибке модели — правила engine.py
    LLM_BASE_URL         например http://localhost:11434/v1
    LLM_API_KEY          для локальной Ollama не нужен
    LLM_MODEL            например qwen2.5:7b-instruct
    LLM_TEMPERATURE / LLM_MAX_TOKENS / LLM_TIMEOUT
"""
import asyncio
import json
import os
import re

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

_client: AsyncOpenAI | None = None


def llm_enabled() -> bool:
    return os.getenv('USE_LLM', '0').strip() == '1' and bool(os.getenv('LLM_MODEL', '').strip())


def get_client() -> AsyncOpenAI:
    global _client
    if _client is not None:
        return _client

    base_url = os.getenv('LLM_BASE_URL', 'http://localhost:11434/v1').strip()
    api_key = os.getenv('LLM_API_KEY', '').strip()
    if not api_key:
        # SDK требует непустой ключ, даже если сервер (Ollama) его не проверяет.
        api_key = 'ollama'
    _client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(os.getenv('LLM_TIMEOUT', '45')),
        max_retries=0,
    )
    return _client


def parse_json_answer(raw: str) -> dict:
    raw = (raw or '').strip()
    fenced = re.search(r'```(?:json)?\s*(.+?)\s*```', raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    start, end = raw.find('{'), raw.rfind('}')
    candidates = [raw]
    if start != -1 and end > start:
        candidates.append(raw[start:end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
    raise ValueError(f'Модель вернула не JSON: {raw[:300]}')


async def chat_json(system_prompt: str, user_prompt: str) -> dict:
    """Один запрос к модели с ответом строго в JSON.

    Любая проблема (сеть, таймаут, битый JSON) — исключение: вызывающий код
    обязан ловить его и работать по правилам движка. Меню и кнопки бота от
    ответа модели не зависят.
    """
    attempts = int(os.getenv('LLM_PARSE_ATTEMPTS', '2'))
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            response = await asyncio.wait_for(
                get_client().chat.completions.create(
                    model=os.getenv('LLM_MODEL', '').strip(),
                    temperature=float(os.getenv('LLM_TEMPERATURE', '0.2')),
                    max_tokens=int(os.getenv('LLM_MAX_TOKENS', '400')),
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt},
                    ],
                ),
                timeout=float(os.getenv('LLM_WAIT_TIMEOUT', '60')),
            )
        except (APIConnectionError, APIStatusError, asyncio.TimeoutError) as error:
            raise RuntimeError(f'LLM недоступна: {type(error).__name__}: {str(error)[:200]}') from error
        try:
            return parse_json_answer(response.choices[0].message.content or '')
        except ValueError as error:
            last_error = error
    raise RuntimeError(f'LLM не отдала корректный JSON за {attempts} попыток: {last_error}')
