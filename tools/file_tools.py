from utils.path_sandbox import safe_path
from state.agent_state import CompactState
from tools.compact_tools import track_recent_file,persist_large_output
from utils.logger_handler import logger

def run_read(path: str,tool_call_id: str,state: CompactState, limit: int = None) -> str:
    logger.info(f"开始阅读文件: {path}")
    try:
        track_recent_file(state, path)
        text = safe_path(path).read_text(encoding="utf-8")
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        output = "\n".join(lines)
        return persist_large_output(tool_call_id, output)
    except Exception as e:
        return f"Error: {e}"
    
def run_write(path: str, content: str) -> str:
    logger.info(f"开始写入文件: {path}")
    try:
        
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"
    
def run_edit(path: str, old_text: str, new_text: str) -> str:
    logger.info(f"开始编辑文件: {path}")
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"