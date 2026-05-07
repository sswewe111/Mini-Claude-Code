from state.agent_state import PlanItem, PlanningState
from utils.config_handler import todo_manager_config

class TodoManager:
    def __init__(self):
        self.state = PlanningState()

    #更新计划，输入是一个包含content、status和activeForm的字典列表
    def update(self, items: list) -> str:
        if len(items) > 12:
            raise ValueError("Keep the session plan short (max 12 items)")
        normalized = []
        in_progress_count = 0
        for index, raw_item in enumerate(items):
            content = str(raw_item.get("content", "")).strip()
            status = str(raw_item.get("status", "pending")).lower()
            active_form = str(raw_item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {index}: content required")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"Item {index}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            normalized.append(PlanItem(
                content=content,
                status=status,
                active_form=active_form,
            ))
        #确保最多只有一个in_progress的item
        if in_progress_count > 1:
            raise ValueError("Only one plan item can be in_progress")
        self.state.items = normalized
        self.state.rounds_since_update = 0
        #更新计划后返回渲染的计划文本
        return self.render()
    
    def note_round_without_update(self) -> None:
        self.state.rounds_since_update += 1
    #提供一个提醒函数，如果连续多轮没有更新计划，就提醒模型刷新计划
    def reminder(self) -> str | None:
        if not self.state.items:
            return None
        if self.state.rounds_since_update < todo_manager_config["PLAN_REMINDER_INTERVAL"]:
            return None
        return "<reminder>Refresh your current plan before continuing.</reminder>"
    
    def render(self) -> str:
        if not self.state.items:
            return "No session plan yet."
        lines = []
        for item in self.state.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[item.status]
            line = f"{marker} {item.content}"
            if item.status == "in_progress" and item.active_form:
                line += f" ({item.active_form})"
            lines.append(line)
        completed = sum(1 for item in self.state.items if item.status == "completed")
        lines.append(f"\n({completed}/{len(self.state.items)} completed)")
        return "\n".join(lines)

TODO = TodoManager()
