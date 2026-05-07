import json
from pathlib import Path
import threading
import time
from tools.message_bus import REQUESTS_DIR

"""
RequestStore 是协议请求的持久化状态存储
"""
class RequestStore:

    def __init__(self, base_dir: Path):
        self.dir = base_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
    
    def _path(self, request_id: str) -> Path:
        return self.dir / f"{request_id}.json"
    
    def create(self, record: dict) -> dict:
        request_id = record["request_id"]
        with self._lock:
            self._path(request_id).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
    
    """查询请求状态：用于查看某个请求当前是 pending、approved 还是 rejected"""
    def get(self, request_id: str) -> dict | None:
        path = self._path(request_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    
    """更新请求状态：用于更新某个请求的状态"""
    def update(self, request_id: str, **changes) -> dict | None:
        with self._lock:
            record = self.get(request_id)
            if not record:
                return None
            record.update(changes)
            record["updated_at"] = time.time()
            self._path(request_id).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

REQUEST_STORE = RequestStore(REQUESTS_DIR)