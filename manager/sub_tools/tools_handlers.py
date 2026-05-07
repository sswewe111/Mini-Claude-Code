from tools.bash_tools import run_bash_windows 
from tools.compact_tools import compact_history
from tools.file_tools import run_read, run_write, run_edit
from tools.request_tools import sub_plan_approval, sub_shutdown_response
from tools.message_bus import BUS
from tools.request_store import REQUEST_STORE
from tools.auto_tools import clain_task_handler
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash_windows(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw["state"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"],kw["new_text"]),
    "compact": lambda **kw: compact_history(kw["messages"], kw["state"], kw.get("focus")),
    "send_message": lambda **kw: BUS.send(kw["sender"],kw["to"], kw["content"]),
    "read_inbox": lambda **kw: BUS.read_inbox(kw["sender"]),
    "shutdown_response": lambda **kw: sub_shutdown_response(kw["sender"], kw["args"]),
    "plan_approval": lambda **kw: sub_plan_approval(kw["sender"], kw["args"]),
    "claim_task": lambda **kw: clain_task_handler(kw["args"], kw["sender"], kw.get("role")),
}