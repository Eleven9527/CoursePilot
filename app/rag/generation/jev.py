"""Optional TypeSafe System One intent classifier."""

import json
import logging
from urllib.request import Request, urlopen

from app.core.config import settings
from app.rag.generation.intents import INTENTS

logger = logging.getLogger(__name__)


def classify_intent(question: str) -> str | None:
    if not settings.jev_api_key:
        return None
    request = Request(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {settings.jev_api_key}", "Content-Type": "application/json"},
        data=json.dumps({
            "model": settings.jev_model,
            "state": question,
            "questions": {
                "intent": {
                    "type": "choice",
                    "instructions": "识别用户的主要课程问答意图。明确要求提示时优先选择 homework_hint。",
                    "criteria": {name: description for name, (description, _) in INTENTS.items()},
                }
            },
        }).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=5) as response:
            answer = json.load(response)["answers"]["intent"]
        choice = answer["choice"]
        if answer["type"] == "choice" and isinstance(choice, str) and choice in INTENTS:
            return choice
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Jev 意图识别不可用，使用对话模型判定 (%s)", type(exc).__name__)
    return None
