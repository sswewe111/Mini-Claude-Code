from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from queue import Empty, Queue
import threading
import time
import uuid
WORKDIR = Path.cwd()

SCHEDULED_TASKS_FILE = WORKDIR / ".claude" / "scheduled_tasks.json"
CRON_LOCK_FILE = WORKDIR / ".claude" / "cron.lock"
AUTO_EXPIRY_DAYS = 7
JITTER_MINUTES = [0, 30]  
JITTER_OFFSET_MAX = 4     

"""
CronLock 的作用是：防止多个程序实例同时运行 cron 检查逻辑，避免同一个定时任务被多个进程重复触发。
"""
class CronLock:

    def __init__(self, lock_path: Path = None):
        self._lock_path = lock_path or CRON_LOCK_FILE

    """
    用于尝试获取锁
    1.如果锁文件已经存在，读取里面保存的 PID。
    2.使用 os.kill(stored_pid, 0) 检查该 PID 对应的进程是否还活着。
    3.如果进程还活着，说明另一个 session 正在持有锁，返回 False。
    4.如果 PID 无效、进程不存在、权限错误或文件内容不是合法 PID，就认为这是一个过期锁。
    5.创建 .claude 目录，并把当前进程 PID 写入锁文件。
    6.返回 True。
    """
    def acquire(self) -> bool:
        if self._lock_path.exists():
            try:
                stored_pid = int(self._lock_path.read_text().strip())
                os.kill(stored_pid, 0)#使用 os.kill(stored_pid, 0) 检查该 PID 对应的进程是否还活着
                return False
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                pass
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.write_text(str(os.getpid()))
        return True
    
    # 用于释放锁
    def release(self):
        try:
            if self._lock_path.exists():
                stored_pid = int(self._lock_path.read_text().strip())
                if stored_pid == os.getpid():
                    self._lock_path.unlink()
        except (ValueError, OSError):
            pass

"""
cron_matches的作用是：判断某个 cron 表达式是否匹配指定的时间。
"""
def cron_matches(expr: str, dt: datetime) -> bool:
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    values = [dt.minute, dt.hour, dt.day, dt.month, dt.weekday()]
    cron_dow = (dt.weekday() + 1) % 7
    values[4] = cron_dow
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for field, value, (lo, hi) in zip(fields, values, ranges):
        if not _field_matches(field, value, lo, hi):
            return False
    return True

"""
_field_matches的作用是：判断 cron 表达式中的单个字段是否匹配当前字段值。
"""
def _field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)
        if part == "*":
            # */N -- check if value is on the step grid
            if (value - lo) % step == 0:
                return True
        elif "-" in part:
            # Range: N-M
            start, end = part.split("-", 1)
            start, end = int(start), int(end)
            if start <= value <= end and (value - start) % step == 0:
                return True
        else:
            # Exact value
            if int(part) == value:
                return True
    return False

"""
CronScheduler 是整个定时任务系统的核心管理类。它负责：
1.保存任务列表。
2.启动后台线程。
3.每分钟检查 cron 是否触发。
4.把触发的任务放进通知队列。
5.支持创建、删除、列出任务。
6.支持 durable 持久化任务。
7.支持 one-shot 一次性任务。
8.支持 recurring 任务 7 天自动过期。
9.支持简单 jitter，避免任务总是在整点或半点触发。
"""
class CronScheduler:
    
    def __init__(self):
        self.tasks = []        
        self.queue = Queue()   
        self._stop_event = threading.Event()
        self._thread = None
        self._last_check_minute = -1  
    
    #启动调度器时，先从磁盘加载 durable 任务，然后启动后台线程。
    def start(self):
        self._load_durable()
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
        count = len(self.tasks)
        if count:
            print(f"[Cron] Loaded {count} scheduled tasks")
    
    # 停止后台线程。
    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
    
    #创建一个定时任务
    def create(self, cron_expr: str, prompt: str,
               recurring: bool = True, durable: bool = False) -> str:
        task_id = str(uuid.uuid4())[:8]
        now = time.time()
        task = {
            "id": task_id,
            "cron": cron_expr,
            "prompt": prompt,
            "recurring": recurring,
            "durable": durable,
            "createdAt": now,
        }
        
        if recurring:
            task["jitter_offset"] = self._compute_jitter(cron_expr)
        self.tasks.append(task)
        if durable:
            self._save_durable()
        mode = "recurring" if recurring else "one-shot"
        store = "durable" if durable else "session-only"
        return f"Created task {task_id} ({mode}, {store}): cron={cron_expr}"
    
    # 根据 ID 删除任务
    def delete(self, task_id: str) -> str:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if len(self.tasks) < before:
            self._save_durable()
            return f"Deleted task {task_id}"
        return f"Task {task_id} not found"
    
    # 列出当前任务
    def list_tasks(self) -> str:
        if not self.tasks:
            return "No scheduled tasks."
        lines = []
        for t in self.tasks:
            mode = "recurring" if t["recurring"] else "one-shot"
            store = "durable" if t["durable"] else "session"
            age_hours = (time.time() - t["createdAt"]) / 3600
            lines.append(
                f"  {t['id']}  {t['cron']}  [{mode}/{store}] "
                f"({age_hours:.1f}h old): {t['prompt'][:60]}"
            )
        return "\n".join(lines)
    
    #清空通知队列，并返回所有待处理通知
    def drain_notifications(self) -> list[str]:
        notifications = []
        while True:
            try:
                notifications.append(self.queue.get_nowait())
            except Empty:
                break
        return notifications
    
    # 用于给 recurring 任务增加一个小偏移，避免任务都在 :00 或 :30 精确触发
    def _compute_jitter(self, cron_expr: str) -> int:
        fields = cron_expr.strip().split()
        if len(fields) < 1:
            return 0
        minute_field = fields[0]
        try:
            minute_val = int(minute_field)
            if minute_val in JITTER_MINUTES:
                # Deterministic jitter based on the expression hash
                return (hash(cron_expr) % JITTER_OFFSET_MAX) + 1
        except ValueError:
            pass
        return 0
    
    # 后台线程：每秒钟检查是否有任务到期。
    def _check_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()
            current_minute = now.hour * 60 + now.minute
            if current_minute != self._last_check_minute:
                self._last_check_minute = current_minute
                self._check_tasks(now)
            self._stop_event.wait(timeout=1)
    
    # 根据当前时间检查所有任务，点燃火柴
    def _check_tasks(self, now: datetime):
        expired = []
        fired_oneshots = []
        for task in self.tasks:
            age_days = (time.time() - task["createdAt"]) / 86400
            if task["recurring"] and age_days > AUTO_EXPIRY_DAYS:
                expired.append(task["id"])
                continue
            check_time = now
            jitter = task.get("jitter_offset", 0)
            if jitter:
                check_time = now - timedelta(minutes=jitter)
            if cron_matches(task["cron"], check_time):
                notification = (
                    f"[Scheduled task {task['id']}]: {task['prompt']}"
                )
                self.queue.put(notification)
                task["last_fired"] = time.time()
                print(f"[Cron] Fired: {task['id']}")
                if not task["recurring"]:
                    fired_oneshots.append(task["id"])
        # Clean up expired and one-shot tasks
        if expired or fired_oneshots:
            remove_ids = set(expired) | set(fired_oneshots)
            self.tasks = [t for t in self.tasks if t["id"] not in remove_ids]
            for tid in expired:
                print(f"[Cron] Auto-expired: {tid} (older than {AUTO_EXPIRY_DAYS} days)")
            for tid in fired_oneshots:
                print(f"[Cron] One-shot completed and removed: {tid}")
            self._save_durable()

    #从.claude/scheduled加载持久任务_tasks.json。
    def _load_durable(self):
        
        if not SCHEDULED_TASKS_FILE.exists():
            return
        try:
            data = json.loads(SCHEDULED_TASKS_FILE.read_text())
            # Only load durable tasks
            self.tasks = [t for t in data if t.get("durable")]
        except Exception as e:
            print(f"[Cron] Error loading tasks: {e}")
    
    """
    用于检测程序关闭期间错过的 durable 任务
    """
    def detect_missed_tasks(self) -> list[dict]:
        now = datetime.now()
        missed = []
        for task in self.tasks:
            last_fired = task.get("last_fired")
            if last_fired is None:
                continue
            last_dt = datetime.fromtimestamp(last_fired)
            # Walk forward minute-by-minute from last_fired to now (cap at 24h)
            check = last_dt + timedelta(minutes=1)
            cap = min(now, last_dt + timedelta(hours=24))
            while check <= cap:
                if cron_matches(task["cron"], check):
                    missed.append({
                        "id": task["id"],
                        "cron": task["cron"],
                        "prompt": task["prompt"],
                        "missed_at": check.isoformat(),
                    })
                    break  # one miss is enough to flag it
                check += timedelta(minutes=1)
        return missed
    
    # 保存 durable 任务到磁盘。
    def _save_durable(self):
        
        durable = [t for t in self.tasks if t.get("durable")]
        SCHEDULED_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEDULED_TASKS_FILE.write_text(
            json.dumps(durable, indent=2) + "\n"
        )
# Global scheduler
scheduler = CronScheduler()