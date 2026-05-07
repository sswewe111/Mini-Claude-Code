from pathlib import Path
WORKDIR = Path.cwd()
from manager.memory_manager import memory_mgr
def build_system_prompt(Pre_system,Next_system) -> str:
    """Assemble system prompt with memory content included."""
    parts = [Pre_system]
    # Inject memory content if available
    memory_section = memory_mgr.load_memory_prompt()
    if memory_section:
        parts.append(memory_section)
    parts.append(Next_system)
    return "\n\n".join(parts)