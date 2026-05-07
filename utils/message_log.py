import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils.path_sandbox import safe_path


RUN_LOG_NAME = f"messages_run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{os.getpid()}.jsonl"


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def save_message_log(message: Any, token: Any, log_file: Optional[str] = None) -> Path:
    """
    Save one agent message and token info into a JSONL log file.

    Example:
        save_message_log(assistant_message, response.usage)
    """
    log_dir = safe_path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    if log_file is None:
        log_path = log_dir / RUN_LOG_NAME
    else:
        log_path = safe_path(log_file)

    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "message": _to_jsonable(message),
        "token": _to_jsonable(token),
    }

    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    return log_path
