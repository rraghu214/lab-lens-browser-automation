"""Standalone LLM client for LabLens.

Provider chain (text): Gemini -> Groq -> Cerebras -> NVIDIA -> OpenRouter -> GitHub -> Ollama
Provider chain (vision): Gemini -> GitHub (gpt-4.1-mini) -> Ollama (if vision model)

Each provider is tried in order; on HTTP 429 a 5s pause is inserted before
continuing to the next provider. Other HTTP errors skip immediately.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import httpx


def load_env(path: str = ".env") -> None:
    """Load key=value pairs from `path` into os.environ (skips comments and blanks)."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k and k not in os.environ:
                os.environ[k] = v


# ── Provider descriptors ─────────────────────────────────────────────────────

class _Provider:
    def __init__(self, name: str, base_url: str, api_key: str,
                 model: str, vision: bool = False):
        self.name     = name
        self.base_url = base_url
        self.api_key  = api_key
        self.model    = model
        self.vision   = vision


def _gemini_provider() -> Optional[_Provider]:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return _Provider("gemini", "https://generativelanguage.googleapis.com", key, model, vision=True)


def _groq_provider() -> Optional[_Provider]:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        return None
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return _Provider("groq", "https://api.groq.com/openai", key, model)


def _cerebras_provider() -> Optional[_Provider]:
    key = os.getenv("CEREBRAS_API_KEY", "")
    if not key:
        return None
    model = os.getenv("CEREBRAS_MODEL", "llama3.1-70b")
    return _Provider("cerebras", "https://api.cerebras.ai", key, model)


def _nvidia_provider() -> Optional[_Provider]:
    key = os.getenv("NVIDIA_API_KEY", "")
    if not key:
        return None
    model = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
    return _Provider("nvidia", "https://integrate.api.nvidia.com", key, model)


def _openrouter_provider() -> Optional[_Provider]:
    key = os.getenv("OPEN_ROUTER_API_KEY", "")
    if not key:
        return None
    model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    return _Provider("openrouter", "https://openrouter.ai/api", key, model)


def _github_provider() -> Optional[_Provider]:
    key = os.getenv("GITHUB_ACCESS_TOKEN", "")
    if not key:
        return None
    model = os.getenv("GITHUB_MODEL", "openai/gpt-4.1-mini")
    return _Provider("github", "https://models.inference.ai.azure.com", key, model, vision=True)


def _ollama_provider() -> Optional[_Provider]:
    model = os.getenv("OLLAMA_MODEL", "")
    if not model:
        return None
    base = os.getenv("OLLAMA_URL", "http://localhost:11434")
    return _Provider("ollama", base, "", model)


def _build_chain() -> list[_Provider]:
    builders = [
        _gemini_provider,
        _groq_provider,
        _cerebras_provider,
        _nvidia_provider,
        _openrouter_provider,
        _github_provider,
        _ollama_provider,
    ]
    return [p for b in builders if (p := b()) is not None]


def _build_vision_chain(all_providers: list[_Provider]) -> list[_Provider]:
    return [p for p in all_providers if p.vision]


# ── HTTP helpers ─────────────────────────────────────────────────────────────

async def _openai_chat(client: httpx.AsyncClient, provider: _Provider,
                       messages: list[dict], max_tokens: int) -> dict:
    """Call an OpenAI-compatible /v1/chat/completions endpoint."""
    headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
    payload = {"model": provider.model, "messages": messages, "max_tokens": max_tokens}
    r = await client.post(f"{provider.base_url}/v1/chat/completions",
                          json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    data = r.json()
    choice = data["choices"][0]
    return {
        "text":       choice["message"]["content"],
        "tokens_in":  data.get("usage", {}).get("prompt_tokens", 0),
        "tokens_out": data.get("usage", {}).get("completion_tokens", 0),
        "provider":   provider.name,
        "model":      provider.model,
    }


async def _gemini_chat(client: httpx.AsyncClient, provider: _Provider,
                       messages: list[dict], max_tokens: int) -> dict:
    """Call the Gemini generateContent REST endpoint."""
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        content = m["content"]
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"text": part["text"]})
                elif part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    if url.startswith("data:"):
                        mime, b64 = url.split(",", 1)
                        mime = mime.split(":")[1].split(";")[0]
                        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
            contents.append({"role": role, "parts": parts})
        else:
            contents.append({"role": role, "parts": [{"text": content}]})

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{provider.model}:generateContent?key={provider.api_key}")
    payload = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = await client.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    candidate = data["candidates"][0]
    finish = candidate.get("finishReason", "")
    # Thinking models split output into thought parts + answer parts;
    # iterate all parts and keep the last text part (the actual answer).
    content_parts = candidate.get("content", {}).get("parts", [])
    text = ""
    for part in content_parts:
        if "text" in part:
            text = part["text"]
    if not text and finish == "MAX_TOKENS":
        raise RuntimeError(
            "Gemini hit MAX_TOKENS with no output — "
            "increase max_tokens (thinking model needs headroom)"
        )
    usage = data.get("usageMetadata", {})
    return {
        "text":       text,
        "tokens_in":  usage.get("promptTokenCount", 0),
        "tokens_out": usage.get("candidatesTokenCount", 0),
        "provider":   provider.name,
        "model":      provider.model,
    }


async def _ollama_chat(client: httpx.AsyncClient, provider: _Provider,
                       messages: list[dict], max_tokens: int) -> dict:
    payload = {"model": provider.model, "messages": messages, "stream": False,
               "options": {"num_predict": max_tokens}}
    r = await client.post(f"{provider.base_url}/api/chat", json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return {
        "text":       data["message"]["content"],
        "tokens_in":  data.get("prompt_eval_count", 0),
        "tokens_out": data.get("eval_count", 0),
        "provider":   provider.name,
        "model":      provider.model,
    }


# ── LLMClient ────────────────────────────────────────────────────────────────

class LLMClient:
    def __init__(self, providers: list[_Provider]):
        self._providers = providers
        self._vision_providers = _build_vision_chain(providers)

    @classmethod
    def from_env(cls, env_file: str = ".env") -> "LLMClient":
        load_env(env_file)
        return cls(_build_chain())

    def describe(self) -> str:
        if not self._providers:
            return "No providers configured"
        return "Providers: " + ", ".join(f"{p.name}({p.model})" for p in self._providers)

    async def chat(self, messages: list[dict], max_tokens: int = 2048) -> dict:
        """Try each text provider in order; return first success."""
        last_error: Exception | None = None
        async with httpx.AsyncClient() as client:
            for provider in self._providers:
                try:
                    if provider.name == "gemini":
                        return await _gemini_chat(client, provider, messages, max_tokens)
                    elif provider.name == "ollama":
                        return await _ollama_chat(client, provider, messages, max_tokens)
                    else:
                        return await _openai_chat(client, provider, messages, max_tokens)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        print(f"    [!] {provider.name}: rate limited -- waiting 5s before fallback")
                        await asyncio.sleep(5)
                    else:
                        print(f"    [!] {provider.name}: HTTP {e.response.status_code}")
                    last_error = e
                    continue
                except Exception as e:
                    print(f"    [!] {provider.name}: {type(e).__name__}: {str(e)[:100]}")
                    last_error = e
                    continue
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def vision(self, messages: list[dict], max_tokens: int = 2048) -> dict:
        """Try each vision-capable provider in order; return first success."""
        last_error: Exception | None = None
        async with httpx.AsyncClient() as client:
            for provider in self._vision_providers:
                try:
                    if provider.name == "gemini":
                        return await _gemini_chat(client, provider, messages, max_tokens)
                    else:
                        return await _openai_chat(client, provider, messages, max_tokens)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        print(f"    [!] {provider.name}: rate limited -- waiting 5s before fallback")
                        await asyncio.sleep(5)
                    else:
                        print(f"    [!] {provider.name}: HTTP {e.response.status_code}")
                    last_error = e
                    continue
                except Exception as e:
                    print(f"    [!] {provider.name}: {type(e).__name__}: {str(e)[:100]}")
                    last_error = e
                    continue
        raise RuntimeError(f"All vision providers failed. Last error: {last_error}")


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def _test():
        load_env(".env")
        client = LLMClient.from_env()
        print(client.describe())
        if not client._providers:
            print('{"status": "error", "reason": "no providers configured"}')
            sys.exit(1)
        result = await client.chat(
            [{"role": "user", "content": 'Reply with exactly: {"status": "ok"}'}],
            max_tokens=200,
        )
        print(result["text"].strip())

    asyncio.run(_test())
