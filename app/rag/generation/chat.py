import json
from urllib.request import Request, urlopen

from app.core.config import settings


def chat_json(instructions: str, content: dict) -> dict:
    if not settings.chat_base_url or not settings.chat_model or settings.chat_model == "your_chat_model_here":
        raise RuntimeError("请先配置 CHAT_BASE_URL 和 CHAT_MODEL")
    headers = {"Content-Type": "application/json"}
    if settings.chat_api_key and settings.chat_api_key != "your_api_key_here":
        headers["Authorization"] = f"Bearer {settings.chat_api_key}"
    request = Request(
        f"{settings.chat_base_url.rstrip('/')}/chat/completions",
        headers=headers,
        data=json.dumps({
            "model": settings.chat_model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=45) as response:
            message = json.load(response)["choices"][0]["message"]["content"]
        result = json.loads(message)
        if not isinstance(result, dict):
            raise ValueError("Expected JSON object")
        return result
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("对话模型请求失败，请检查服务地址、模型和鉴权配置") from exc
