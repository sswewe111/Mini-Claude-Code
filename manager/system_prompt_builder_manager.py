import datetime
import os
from pathlib import Path
import re
WORKDIR = Path.cwd()
from system_prompt import SYSTEM_CORE_BUILDER,SYSTEM_TASK

DYNAMIC_BOUNDARY = "=== DYNAMIC_BOUNDARY ==="
from dotenv import load_dotenv
import platform
from utils.logger_handler import logger

load_dotenv(override=True)
MODEL = os.environ["MODEL_ID"]

"""
SystemPromptBuilder 的作用是：把系统提示词拆成多个来源清晰、职责单一的 section，然后按固定顺序组装成最终传给模型的 system prompt。
它不是把系统提示词写成一个巨大的硬编码字符串，而是把 prompt 构造成一条流水线：
核心行为指令
    工具列表
    Skill 元数据
    长期记忆
    CLAUDE.md 指令链
    动态上下文
"""
class SystemPromptBuilder:
   
    def __init__(self, workdir: Path = None, tools: list = None):
        self.workdir = workdir or WORKDIR
        self.tools = tools or []
        self.skills_dir = self.workdir / "skills"
        self.memory_dir = self.workdir / ".memory"
    # -- Section 1: 核心指令 --
    def _build_core(self) -> str:
        return SYSTEM_TASK
            
    # -- Section 2: 工具列表,把 TOOLS 里的工具定义转成可读的 prompt 文本 --
    def _build_tool_listing(self) -> str:

        if not self.tools:
            return ""
        lines = ["# Available tools"]
        for tool in self.tools:
            tool_def = tool.get("function", tool)
            props = tool_def.get("parameters", {}).get("properties", {})
            params = ", ".join(props.keys())
            lines.append(f"- {tool_def['name']}({params}): {tool_def['description']}")
        return "\n".join(lines)
    
    # -- Section 3: Skill 元数据 --
    def _build_skill_listing(self) -> str:
        if not self.skills_dir.exists():
            return ""
        skills = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text(encoding="utf-8")
            # Parse frontmatter for name + description
            match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if not match:
                continue
            meta = {}
            for line in match.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            name = meta.get("name", skill_dir.name)
            desc = meta.get("description", "")
            skills.append(f"- {name}: {desc}")
        if not skills:
            return ""
        return "# Available skills\n" + "\n".join(skills)
    # -- Section 4: 长期记忆 --
    def _build_memory_section(self) -> str:
        if not self.memory_dir.exists():
            return ""
        memories = []
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            text = md_file.read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
            if not match:
                continue
            header, body = match.group(1), match.group(2).strip()
            meta = {}
            for line in header.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            name = meta.get("name", md_file.stem)
            mem_type = meta.get("type", "project")
            desc = meta.get("description", "")
            memories.append(f"[{mem_type}] {name}: {desc}\n{body}")
        if not memories:
            return ""
        return "# Memories (persistent)\n\n" + "\n\n".join(memories)
    
    # -- Section 5: CLAUDE.md 指令链 --
    def _build_claude_md(self) -> str:
       
        sources = []
        # User-global
        user_claude = Path.home() / ".claude" / "CLAUDE.md"
        if user_claude.exists():
            sources.append(("user global (~/.claude/CLAUDE.md)", user_claude.read_text(encoding="utf-8")))
        # Project root
        project_claude = self.workdir / "CLAUDE.md"
        if project_claude.exists():
            sources.append(("project root (CLAUDE.md)", project_claude.read_text(encoding="utf-8")))
        # Subdirectory -- in real CC, this walks from cwd up to project root
        # Teaching: check cwd if different from workdir
        cwd = Path.cwd()
        if cwd != self.workdir:
            subdir_claude = cwd / "CLAUDE.md"
            if subdir_claude.exists():
                sources.append((f"subdir ({cwd.name}/CLAUDE.md)", subdir_claude.read_text(encoding="utf-8")))
        if not sources:
            return ""
        parts = ["# CLAUDE.md instructions"]
        for label, content in sources:
            parts.append(f"## From {label}")
            parts.append(content.strip())
        return "\n\n".join(parts)
    # -- Section 6: 动态上下文 --
    def _build_dynamic_context(self) -> str:
        lines = [
            f"Current date: {datetime.date.today().isoformat()}",
            f"Working directory: {self.workdir}",
            f"Model: {MODEL}",
            f"Platform: {platform.system()}",
        ]
        return "# Dynamic context\n" + "\n".join(lines)
    
    # -- 最终组装入口 --
    def build(self) -> str:
        sections = []
        core = self._build_core()
        if core:
            sections.append(core)
        tools = self._build_tool_listing()
        if tools:
            sections.append(tools)
        skills = self._build_skill_listing()
        if skills:
            sections.append(skills)
        memory = self._build_memory_section()
        if memory:
            sections.append(memory)
        claude_md = self._build_claude_md()
        if claude_md:
            sections.append(claude_md)

        sections.append(DYNAMIC_BOUNDARY)
        dynamic = self._build_dynamic_context()
        if dynamic:
            sections.append(dynamic)
        return "\n\n".join(sections)
