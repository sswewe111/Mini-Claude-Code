from pathlib import Path
import re
from utils.logger_handler import logger

from state.agent_state import SkillDocument, SkillManifest
WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"

class SkillRegistry:
    def __init__(self, skills_dir: Path):
        #保存技能目录
        self.skills_dir = skills_dir
        #创建一个空字典，用于保存所有技能文档
        self.documents: dict[str, SkillDocument] = {}
        #调用 _load_all() 加载所有技能
        self._load_all()
    
    # 加载所有技能，并封装成SkillDocument
    def _load_all(self) -> None:
        if not self.skills_dir.exists():
            return
        #self.skills_dir.rglob("SKILL.md") 的作用是：从 self.skills_dir 这个目录开始，递归查找所有名为 SKILL.md 的文件
        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            meta, body = self._parse_frontmatter(path.read_text(encoding="utf-8"))
            name = meta.get("name", path.parent.name)
            description = meta.get("description", "No description")
            manifest = SkillManifest(name=name, description=description, path=path)
            self.documents[name] = SkillDocument(manifest=manifest, body=body.strip())

    ##解析 Markdown 文件头配置         
    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, match.group(2)
    
    #生成技能目录说明
    def describe_available(self) -> str:
        if not self.documents:
            return "(no skills available)"
        lines = []
        for name in sorted(self.documents):
            manifest = self.documents[name].manifest
            lines.append(f"- {manifest.name}: {manifest.description}")
        return "\n".join(lines)
    
    #按名称加载完整技能内容
    def load_full_text(self, name: str) -> str:
        document = self.documents.get(name)
        logger.info(f"加载{name}的技能内容")
        if not document:
            known = ", ".join(sorted(self.documents)) or "(none)"
            return f"Error: Unknown skill '{name}'. Available skills: {known}"
        return (
            f"<skill name=\"{document.manifest.name}\">\n"
            f"{document.body}\n"
            "</skill>"
        )

SKILL_REGISTRY = SkillRegistry(SKILLS_DIR)