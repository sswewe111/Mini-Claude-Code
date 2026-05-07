import json
import os
import random
from openai import OpenAI
from dotenv import load_dotenv

from utils.normalize_messages import normalize_messages
from utils.config_handler import recovery_config
#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

def estimate_tokens(messages: list) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(json.dumps(messages, default=str)) // 4

# 这个函数会在消息列表超过上下文限制时被调用，用于压缩历史消息
def auto_compact(messages: list) -> list:
    """
    Compress conversation history into a short continuation summary.
    """
    conversation_text = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this conversation for continuity. Include:\n"
        "1) Task overview and success criteria\n"
        "2) Current state: completed work, files touched\n"
        "3) Key decisions and failed approaches\n"
        "4) Remaining next steps\n"
        "Be concise but preserve critical details.\n\n"
        + conversation_text
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=normalize_messages([
                {"role": "system", "content": prompt},
            ]),
            max_tokens=4000,
        )
        summary = response.choices[0].message.content
    except Exception as e:
        summary = f"(compact failed: {e}). Previous context lost."
    continuation = (
        "This session continues from a previous conversation that was compacted. "
        f"Summary of prior context:\n\n{summary}\n\n"
        "Continue from where we left off without re-asking the user."
    )
    return [{"role": "user", "content": continuation}]

# 这个函数会在工具调用失败时被调用，用于计算下一次重试的延迟时间
def backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random(0, 1)."""
    delay = min(recovery_config.get("backoff_base_delay", 1) * (2 ** attempt), recovery_config.get("backoff_max_delay", 60))
    jitter = random.uniform(0, 1)
    return delay + jitter