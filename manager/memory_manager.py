from pathlib import Path
import re
WORKDIR = Path.cwd()
from utils.config_handler import memory_config
from utils.logger_handler import logger

"""
MemoryManager 负责“记忆系统”的核心读写流程：
它把跨会话需要保留的信息保存到 .memory/ 目录下，
每条记忆是一个独立的 Markdown 文件，
并通过 MEMORY.md 维护一个简短索引。
它还负责在 agent 启动或运行时，
把已有记忆加载进内存，
并组装成可注入 system prompt 的文本。
"""
class MemoryManager:
    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or WORKDIR / memory_config["MEMORY_DIR"]
        self.memories = {} 
    
    """
    load_all() 用于从磁盘加载所有记忆
    """
    def load_all(self):
        # 清空已有内存缓存。如果 .memory/ 不存在，就直接返
        self.memories = {}
        if not self.memory_dir.exists():
            return
        # 扫描 .memory/ 下的所有 Markdown 文件
        for md_file in sorted(self.memory_dir.glob("*.md")):
            if md_file.name == "MEMORY.md":
                continue
            parsed = self._parse_frontmatter(md_file.read_text(encoding="utf-8"))
            if parsed:
                name = parsed.get("name", md_file.stem)
                self.memories[name] = {
                    "description": parsed.get("description", ""),
                    "type": parsed.get("type", "project"),
                    "content": parsed.get("content", ""),
                    "file": md_file.name,
                }
        count = len(self.memories)
        if count > 0:
            logger.info(f"[Memory loaded: {count} memories from {self.memory_dir}]")
    
    """
    用于把内存里的记忆转换成 system prompt 片段
    """
    def load_memory_prompt(self) -> str:
        if not self.memories:
            return ""
        
        sections = []
        sections.append("# Memories (persistent across sessions)")
        sections.append("")
        
        for mem_type in memory_config["MEMORY_TYPES"]:
            typed = {k: v for k, v in self.memories.items() if v["type"] == mem_type}
            if not typed:
                continue
            sections.append(f"## [{mem_type}]")
            for name, mem in typed.items():
                sections.append(f"### {name}: {mem['description']}")
                if mem["content"].strip():
                    sections.append(mem["content"].strip())
                sections.append("")
        return "\n".join(sections)
    
    """
    用于保存一条新记忆
    它接收四个字段：
        name：记忆名称
        description：一行描述
        mem_type：记忆类型
        content：完整内容
    """
    def save_memory(self, name: str, description: str, mem_type: str, content: str) -> str:
        
        if mem_type not in memory_config["MEMORY_TYPES"]:
            logger.warning(f"Error: type must be one of {memory_config['MEMORY_TYPES']}")
            return f"Error: type must be one of {memory_config['MEMORY_TYPES']}"
        # 把 name 转成安全文件名
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        if not safe_name:
            logger.warning("Error: invalid memory name")
            return "Error: invalid memory name"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # Write individual memory file with frontmatter
        frontmatter = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mem_type}\n"
            f"---\n"
            f"{content}\n"
        )
        file_name = f"{safe_name}.md"
        file_path = self.memory_dir / file_name
        file_path.write_text(frontmatter, encoding="utf-8")
        # Update in-memory store
        self.memories[name] = {
            "description": description,
            "type": mem_type,
            "content": content,
            "file": file_name,
        }
        self._rebuild_index()
        logger.info(f"Saved memory '{name}' [{mem_type}] to {file_path.relative_to(WORKDIR)}")
        return f"Saved memory '{name}' [{mem_type}] to {file_path.relative_to(WORKDIR)}"
    
    """
    用于生成记忆索引
    """
    def _rebuild_index(self):
        lines = ["# Memory Index", ""]
        for name, mem in self.memories.items():
            lines.append(f"- {name}: {mem['description']} [{mem['type']}]")
            if len(lines) >= memory_config["MAX_INDEX_LINES"]:
                lines.append(f"... (truncated at {memory_config['MAX_INDEX_LINES']} lines)")
                break
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (WORKDIR / memory_config["MEMORY_INDEX"]).write_text("\n".join(lines) + "\n", encoding="utf-8")

    """
    用于解析 Markdown frontmatter
    """
    def _parse_frontmatter(self, text: str) -> dict | None:
        
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not match:
            return None
        header, body = match.group(1), match.group(2)
        result = {"content": body.strip()}
        for line in header.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
        return result
    
memory_mgr = MemoryManager()
