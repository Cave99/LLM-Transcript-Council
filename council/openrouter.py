"""Async OpenRouter client used for generator and judge calls."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMResponse:
    text: str
    raw: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None


class OpenRouterClient:
    def __init__(self, *, timeout: float = 120.0) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.site_url = os.getenv("OPENROUTER_SITE_URL", "http://localhost:5001")
        self.app_name = os.getenv("OPENROUTER_APP_NAME", "LLM-Transcript-Council")
        self.timeout = timeout

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        retries: int = 3,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(retries):
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    data = response.json()
                    usage = data.get("usage") or {}
                    choice = data["choices"][0]
                    message = choice.get("message") or {}
                    return LLMResponse(
                        text=message.get("content", ""),
                        raw=data,
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        cost=usage.get("cost"),
                    )
                await asyncio.sleep(2**attempt)

        response.raise_for_status()
        raise RuntimeError("OpenRouter call failed after retries")
