import json
import subprocess
import threading
import time
from pathlib import Path
import uuid
WORKDIR = Path.cwd()
STALL_THRESHOLD_S = 45  # seconds before a task is considered stalled
RUNTIME_DIR = WORKDIR / ".runtime-tasks"


"""
NotificationQueue 是一个通用的“通知队列”抽象，负责按优先级保存通知，并支持同 key 通知折叠。
"""
class NotificationQueue:
    # 优先级排序：immediate > high > medium > low
    PRIORITIES = {"immediate": 0, "high": 1, "medium": 2, "low": 3}
    def __init__(self):
        self._queue = []  # 保存队列内容，每个元素格式是： (priority, key, message)
        self._lock = threading.Lock()
    
    #向队列添加一条通知。
    def push(self, message: str, priority: str = "medium", key: str = None):
        with self._lock:
            if key:
                # 如果传入 key，则相同 key 的旧消息会被替换
                self._queue = [(p, k, m) for p, k, m in self._queue if k != key]
            self._queue.append((self.PRIORITIES.get(priority, 2), key, message))
            self._queue.sort(key=lambda x: x[0]) # 按优先级数字排序，保证高优先级通知先被取出。
    
    # 取出全部通知，并清空队列
    def drain(self) -> list[str]:
        with self._lock:
            messages = [m for _, _, m in self._queue]
            self._queue.clear()
            return messages
"""
1.启动一个后台线程执行这个命令。
2.立刻把任务 id 返回给模型，不阻塞 agent 主循环。
3.后台线程执行完成后，保存结果、写日志文件、更新状态。
4.把完成通知放入通知队列。
5.在下一次模型调用前，由 agent_loop 调用 BG.drain_notifications()，把完成结果注入对话。
"""
class BackgroundManager:
    def __init__(self):
        self.dir = RUNTIME_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tasks = {}  # task_id -> {status, result, command, started_at}
        self._notification_queue = []  # 保存已完成任务的通知
        self._lock = threading.Lock()

    # 返回某个任务的 JSON 状态文件路径
    def _record_path(self, task_id: str) -> Path:
        return self.dir / f"{task_id}.json"
    
    # 返回某个任务的日志文件路径。
    def _output_path(self, task_id: str) -> Path:
        return self.dir / f"{task_id}.log"
    
    # 把任务状态写入 JSON 文件。
    def _persist_task(self, task_id: str):
        record = dict(self.tasks[task_id])
        self._record_path(task_id).write_text(
            json.dumps(record, indent=2, ensure_ascii=False)
        )
    
    #生成输出预览。
    def _preview(self, output: str, limit: int = 500) -> str:
        compact = " ".join((output or "(no output)").split())
        return compact[:limit]
    
    #启动后台任务
    def run(self, command: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        output_file = self._output_path(task_id)
        self.tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "result": None,
            "command": command,
            "started_at": time.time(),
            "finished_at": None,
            "result_preview": "",
            "output_file": str(output_file.relative_to(WORKDIR)),
        }
        self._persist_task(task_id)
        thread = threading.Thread(
            target=self._execute, args=(task_id, command), daemon=True
        )
        thread.start()
        return (
            f"Background task {task_id} started: {command[:80]} "
            f"(output_file={output_file.relative_to(WORKDIR)})"
        )
    
    # 后台线程真正执行命令
    def _execute(self, task_id: str, command: str):
        try:
            r = subprocess.run(
                command, shell=True, cwd=WORKDIR,
                capture_output=True, text=True, timeout=300
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output = "Error: Timeout (300s)"
            status = "timeout"
        except Exception as e:
            output = f"Error: {e}"
            status = "error"
        final_output = output or "(no output)"
        preview = self._preview(final_output)
        output_path = self._output_path(task_id)
        output_path.write_text(final_output)
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = final_output
        self.tasks[task_id]["finished_at"] = time.time()
        self.tasks[task_id]["result_preview"] = preview
        self._persist_task(task_id)
        with self._lock:
            self._notification_queue.append({
                "task_id": task_id,
                "status": status,
                "command": command[:80],
                "preview": preview,
                "output_file": str(output_path.relative_to(WORKDIR)),
            })

    # 查询后台任务
    def check(self, task_id: str = None) -> str:
        """Check status of one task or list all."""
        if task_id:
            t = self.tasks.get(task_id)
            if not t:
                return f"Error: Unknown task {task_id}"
            visible = {
                "id": t["id"],
                "status": t["status"],
                "command": t["command"],
                "result_preview": t.get("result_preview", ""),
                "output_file": t.get("output_file", ""),
            }
            return json.dumps(visible, indent=2, ensure_ascii=False)
        lines = []
        for tid, t in self.tasks.items():
            lines.append(
                f"{tid}: [{t['status']}] {t['command'][:60]} "
                f"-> {t.get('result_preview') or '(running)'}"
            )
        return "\n".join(lines) if lines else "No background tasks."
    
    #取出完成通知
    def drain_notifications(self) -> list:
        with self._lock:
            notifs = list(self._notification_queue)
            self._notification_queue.clear()
        return notifs
    
    #检测卡住的任务
    def detect_stalled(self) -> list[str]:
        """
        Return task IDs that have been running longer than STALL_THRESHOLD_S.
        """
        now = time.time()
        stalled = []
        for task_id, info in self.tasks.items():
            if info["status"] != "running":
                continue
            elapsed = now - info.get("started_at", now)
            if elapsed > STALL_THRESHOLD_S:
                stalled.append(task_id)
        return stalled
    
BG = BackgroundManager()