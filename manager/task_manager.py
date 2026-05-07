import json
from pathlib import Path
import time
WORKDIR = Path.cwd()
from utils.git_path import REPO_ROOT

TASKS_DIR = WORKDIR / ".tasks"

"""
TaskManager 的作用就是管理这些持久任务。
1.每个任务是一个 JSON 文件
2.每个任务有状态：pending、in_progress、completed、deleted
3.每个任务可以依赖其他任务：blockedBy
4.每个任务也可以声明自己阻塞了哪些后续任务：blocks
5.当某个任务完成时，会自动从其他任务的 blockedBy 中移除
"""
class TaskManager:

    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir #保存任务目录路径
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1 #扫描已有任务文件，计算下一个可用 ID
    
    #查找最大任务 ID
    def _max_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0
    
    #加载任务：根据 ID 从文件系统加载任务数据
    def _load(self, task_id: int) -> dict:
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())
    
    # 保存任务：把任务数据写回文件系统
    def _save(self, task: dict):
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2),encoding="utf-8")
    
    #创建任务
    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id, 
            "subject": subject, 
            "description": description,
            "status": "pending", 
            "owner": "", 
            "worktree": "",
            "worktree_state": "unbound", 
            "last_worktree": "",
            "closeout": None, 
            "blockedBy": [],
            "created_at": time.time(), 
            "updated_at": time.time(),
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2)
    
    #获取任务
    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2)
    
    #更新任务
    def update(self, 
               task_id: int, 
               status: str = None, 
               owner: str = None,
               add_blocked_by: list = None, 
               add_blocks: list = None) -> str:
        task = self._load(task_id)
        if owner is not None:
            task["owner"] = owner
        if status:
            if status not in ("pending", "in_progress", "completed", "deleted"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            # 如果任务 1 完成了，那么所有依赖任务 1 的任务，都应该从 blockedBy 中移除 1。
            if status == "completed":
                self._clear_dependency(task_id)
        
        if owner is not None:
            task["owner"] = owner
        task["updated_at"] = time.time()

        #给当前任务增加前置依赖
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        #当前任务完成后，会解锁哪些任务。
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
            # 当你声明“任务 1 blocks 任务 2”时，系统会自动把任务 1 加入任务 2 的 blockedBy
            for blocked_id in add_blocks:
                try:
                    blocked = self._load(blocked_id)
                    if task_id not in blocked["blockedBy"]:
                        blocked["blockedBy"].append(task_id)
                        self._save(blocked)
                except ValueError:
                    pass
        self._save(task)
        return json.dumps(task, indent=2)
    

    def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
        task = self._load(task_id)
        task["worktree"] = worktree
        task["last_worktree"] = worktree
        task["worktree_state"] = "active"
        if owner:
            task["owner"] = owner
        if task["status"] == "pending":
            task["status"] = "in_progress"
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)
    
    def unbind_worktree(self, task_id: int) -> str:
        task = self._load(task_id)
        task["worktree"] = ""
        task["worktree_state"] = "unbound"
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)
    
    def record_closeout(self, task_id: int, action: str, reason: str = "", keep_binding: bool = False) -> str:
        task = self._load(task_id)
        task["closeout"] = {
            "action": action,
            "reason": reason,
            "at": time.time(),
        }
        task["worktree_state"] = action
        if not keep_binding:
            task["worktree"] = ""
        task["updated_at"] = time.time()
        self._save(task)
        return json.dumps(task, indent=2)
    
    # 清理依赖：
    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
    
    

    # 列出所有任务
    def list_all(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "deleted": "[-]"}.get(t["status"], "[?]")
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            owner = f" owner={t['owner']}" if t.get("owner") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

tasks = TaskManager(REPO_ROOT / ".tasks")