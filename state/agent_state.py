from dataclasses import dataclass, field
from pathlib import Path

# 这个文件定义了Agent Loop的状态类LoopState。
@dataclass
class LoopState:
    # The minimal loop state: history, loop count, and why we continue.
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None

"""
content:这一步要做什么
status:这一步现在处在什么状态
activeForm:当它正在进行中时，可以用更自然的进行时描述"""
@dataclass
class PlanItem:
    content: str
    status: str = "pending"
    active_form: str = ""

"""
rounds_since_updat:连续多少轮过去了，模型还没有更新这份计划。
"""
@dataclass
class PlanningState:
    items: list[PlanItem] = field(default_factory=list)
    rounds_since_update: int = 0

"""
name:skill的名字
description:skill的描述
path:skill的路径
"""
@dataclass
class SkillManifest:
    name: str
    description: str
    path: Path

"""
body:skill的内容
"""
@dataclass
class SkillDocument:
    manifest: SkillManifest
    body: str

"""
has_compacted：这一轮之前是否已经做过完整压缩
last_summary：最近一次压缩得到的摘要
recent_files：最近碰过哪些文件，压缩后方便继续追踪
"""
@dataclass
class CompactState:
    has_compacted: bool = False
    last_summary: str = ""
    recent_files: list[str] = field(default_factory=list)