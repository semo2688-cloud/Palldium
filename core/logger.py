import json
import os
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
_FAILURE_LOG = os.path.join(_LOG_DIR, "failures.jsonl")


def log_failure(
    url: str,
    platform: str,
    query: str = "",
    status_code: int | None = None,
    error: str = "",
) -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "query": query,
        "url": url,
        "status_code": status_code,
        "error": error[:300],
    }
    try:
        with open(_FAILURE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_recent_failures(limit: int = 100) -> list[dict]:
    if not os.path.exists(_FAILURE_LOG):
        return []
    entries: list[dict] = []
    try:
        with open(_FAILURE_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return entries[-limit:]
