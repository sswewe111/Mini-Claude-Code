import json
import threading
import time

from tools.message_bus import TASKS_DIR, CLAIM_EVENTS_PATH



_claim_lock = threading.Lock()

"""
每次队友成功认领任务时，都会调用此函数保存事件信息，包括认领者、任务 ID、时间戳等。
1.持久化记录谁何时认领了任务
2.支持后续审计或调试任务认领流程
"""
def _append_claim_event(payload: dict):
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    with CLAIM_EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

"""
检查某个队友的角色是否符合任务的角色要求。任务可能指定 claim_role 或 required_role。
1.防止不合适的队友认领某些任务
2.支持任务板的角色约束机制
"""
def _task_allows_role(task: dict, role: str | None) -> bool:
    required_role = task.get("claim_role") or task.get("required_role") or ""
    if not required_role:
        return True
    return bool(role) and role == required_role

"""
判断任务是否可被认领。
1.status 为 "pending"
2.没有当前认领者 (owner 为空)
3.没有阻塞任务 (blockedBy 为空)
4.队友角色符合任务要求（调用 _task_allows_role）
"""
def is_claimable_task(task: dict, role: str | None = None) -> bool:
    return (
        task.get("status") == "pending"
        and not task.get("owner")
        and not task.get("blockedBy")
        and _task_allows_role(task, role)
    )

"""
扫描 .tasks/ 目录下所有任务文件，返回所有当前可被认领的任务列表。
自动空闲队友在 idle 阶段扫描任务板
支持自主认领机制（无需 lead 手动分配）
"""
def scan_unclaimed_tasks(role: str | None = None) -> list:
    TASKS_DIR.mkdir(exist_ok=True)
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text(encoding="utf-8"))
        if is_claimable_task(task, role):
            unclaimed.append(task)
    return unclaimed

"""
执行认领任务操作，将任务从 "pending" 状态改为 "in_progress" 并设置认领者。
1.加锁 _claim_lock 确保线程安全
2.检查任务是否存在
3.判断任务是否可认领（调用 is_claimable_task）
4.更新任务属性：
    owner
    status
    claimed_at
    claim_source
5.写回任务文件
6.调用 _append_claim_event 记录事件
7.返回认领结果字符串
"""
def claim_task(
    task_id: int,
    owner: str,
    role: str | None = None,
    source: str = "manual",
) -> str:
    with _claim_lock:
        path = TASKS_DIR / f"task_{task_id}.json"
        if not path.exists():
            return f"Error: Task {task_id} not found"
        task = json.loads(path.read_text(encoding="utf-8"))
        if not is_claimable_task(task, role):
            return f"Error: Task {task_id} is not claimable for role={role or '(any)'}"
        task["owner"] = owner
        task["status"] = "in_progress"
        task["claimed_at"] = time.time()
        task["claim_source"] = source
        path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    _append_claim_event({
        "event": "task.claimed",
        "task_id": task_id,
        "owner": owner,
        "role": role,
        "source": source,
        "ts": time.time(),
    })
    return f"Claimed task #{task_id} for {owner} via {source}"

"""
生成身份信息块（identity block），包含队友的名字、角色和团队信息。
1.用于上下文压缩后重新注入身份信息
2.确保长期运行的自主队友不会忘记自己的角色与团队身份
"""
def make_identity_block(name: str, role: str, team_name: str) -> dict:
    return {
        "role": "user",
        "content": f"<identity>You are '{name}', role: {role}, team: {team_name}. Continue your work.</identity>",
    }

"""
检查消息上下文是否包含身份块，如果没有，则插入身份块和 assistant 确认消息。
1.在 idle 或自动认领新任务时维护队友的身份上下文
2.避免上下文压缩或消息截断导致自主队友“丢失身份”
"""
def ensure_identity_context(messages: list, name: str, role: str, team_name: str):
    if messages and "<identity>" in str(messages[0].get("content", "")):
        return
    messages.insert(0, make_identity_block(name, role, team_name))
    messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})


def clain_task_handler(args: dict, sender: str,role:dict) -> str:
    task_id=args["task_id"]
    owner=sender
    role=role
    source= "manual"

    return claim_task(task_id, owner, role, source)
