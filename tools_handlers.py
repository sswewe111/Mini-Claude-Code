#导入工具函数
import json

from manager.worktree_manager import WORKTREES
from tools.auto_tools import claim_task
from tools.bash_tools import run_bash_windows 
from tools.event_bus import EVENTS
from tools.file_tools import run_read, run_write, run_edit
from tools.request_tools import _check_shutdown_status, handle_plan_review, handle_shutdown_request
from manager.todo_manager import TODO
from tools.skills_tools import SKILL_REGISTRY
from tools.compact_tools import compact_history
from tools.memory_save import run_save_memory
from manager.background_manager import BG
from manager.cron_scheduler_manager import scheduler
from manager.teammate_manager import TEAM

from manager.task_manager import tasks
#导入子Agent
from subagent.read_agent import read_subagent

from state.agent_state import CompactState
from tools.message_bus import BUS

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash_windows(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw["state"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"],kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    "task": lambda **kw: read_subagent(kw["prompt"], kw["state"]),
    "load_skill": lambda **kw: SKILL_REGISTRY.load_full_text(kw["name"]),
    "compact": lambda **kw: compact_history(kw["messages"], kw["state"], kw.get("focus")),
    "save_memory":  lambda **kw: run_save_memory(kw["name"], kw["description"], kw["type"], kw["content"]),

    "task_create": lambda **kw: tasks.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: tasks.update(kw["task_id"], kw.get("status"), kw.get("owner"), kw.get("addBlockedBy"), kw.get("addBlocks")),
    "task_list":   lambda **kw: tasks.list_all(),
    "task_get":    lambda **kw: tasks.get(kw["task_id"]),

    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),

    "cron_create": lambda **kw: scheduler.create(kw["cron"], kw["prompt"], kw.get("recurring", True), kw.get("durable", False)),
    "cron_delete": lambda **kw: scheduler.delete(kw["id"]),
    "cron_list":   lambda **kw: scheduler.list_tasks(),

    "spawn_teammate":  lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"],kw["state"]),
    "list_teammates":  lambda **kw: TEAM.list_all(),
    "send_message":    lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":      lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":       lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),

    "shutdown_request":  lambda **kw: handle_shutdown_request(kw["teammate"]),
    "shutdown_response": lambda **kw: _check_shutdown_status(kw.get("request_id", "")),
    "plan_approval":     lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "idle":              lambda **kw: "Lead does not idle.",
    "claim_task":        lambda **kw: claim_task(kw["task_id"], "lead"),

    "task_bind_worktree": lambda **kw: tasks.bind_worktree(kw["task_id"], kw["worktree"], kw.get("owner", "")),
    "worktree_create": lambda **kw: WORKTREES.create(kw["name"], kw.get("task_id"), kw.get("base_ref", "HEAD")),
    "worktree_list": lambda **kw: WORKTREES.list_all(),
    "worktree_enter": lambda **kw: WORKTREES.enter(kw["name"]),
    "worktree_status": lambda **kw: WORKTREES.status(kw["name"]),
    "worktree_run": lambda **kw: WORKTREES.run(kw["name"], kw["command"]),
    "worktree_closeout": lambda **kw: WORKTREES.closeout(
        kw["name"],
        kw["action"],
        kw.get("reason", ""),
        kw.get("force", False),
        kw.get("complete_task", False),
    ),
    "worktree_keep": lambda **kw: WORKTREES.keep(kw["name"]),
    "worktree_remove": lambda **kw: WORKTREES.remove(
        kw["name"],
        kw.get("force", False),
        kw.get("complete_task", False),
        kw.get("reason", ""),
    ),
    "worktree_events": lambda **kw: EVENTS.list_recent(kw.get("limit", 20)),
}

