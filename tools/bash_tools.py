import subprocess
import os
import locale
from tools.compact_tools import persist_large_output

"""
这段代码定义了一个 run_bash 函数，适用linux系统，
用来执行一条 shell 命令，并返回命令输出。
param command: 要执行的 shell 命令字符串。
return: 命令的输出结果字符串，或错误信息。
"""
def run_bash_linux(command: str,tool_call_id: str) -> str:
    #定义一个危险命令关键词列表。如果输入的命令包含这些关键词，则阻止执行并返回错误信息。
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    
    if any(item in command for item in dangerous):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"
    output = (result.stdout + result.stderr).strip() or "(no output)"
    # 如果输出长度超过阈值，则将其保存到文件中
    return persist_large_output(tool_call_id, output)

import os
import subprocess




def run_bash_windows(command: str,tool_call_id: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

    output = (result.stdout + result.stderr).strip() or "(no output)"
    # 如果输出长度超过阈值，则将其保存到文件中
    return persist_large_output(tool_call_id, output)
