import os
import json
try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
    readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass
from openai import OpenAI
from dotenv import load_dotenv

#导入日志配置文件
from utils.logger_handler import logger
#导入提示词
from system_prompt import SUBAGENT_SYSTEM
#导入工具配置
from tools_configs import TOOLS
#导入agent state
from state.agent_state import LoopState
#导入utils里的相关函数
from utils.path_sandbox import safe_path
from utils.normalize_messages import normalize_messages
#导入工具函数
from tools.bash_tools import run_bash_windows 
from tools.file_tools import run_read, run_write, run_edit
from manager.todo_manager import TODO
from state.agent_state import CompactState

#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

#系统提示词
SYSTEM =SUBAGENT_SYSTEM

#工具配置
TOOLS = TOOLS
#工具名映射到处理函数
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash_windows(kw["command"], kw["tool_call_id"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw["tool_call_id"], kw["state"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"],kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    
}

def read_subagent(prompt: str, state: CompactState) -> str:
    logger.info(f"Subagent received task: {prompt}")
    sub_messages = [{"role": "user", "content": prompt}]  # fresh context
    for _ in range(30):  # safety limit
        response = client.chat.completions.create(
            model=MODEL,
            messages=normalize_messages([
                {"role": "system", "content": SYSTEM},
                *sub_messages,
            ]),
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=8000,
        )
        #获取模型恢复的content，并追加到消息列表中
        assistant_message = response.choices[0].message
        assistant_record = {
            "role": "assistant",
            "content": assistant_message.content,
        }
        #判断是否调用工具，如果调用了工具就执行工具函数，并将结果追加到消息列表中
        if assistant_message.tool_calls:
            assistant_record["tool_calls"] = [
                #model_dump() 把 OpenAI SDK 返回的对象转换成普通 Python 字典
                tool_call.model_dump() for tool_call in assistant_message.tool_calls 
            ]

        sub_messages.append(assistant_record)

        #如果没有调用工具就结束循环
        if not assistant_message.tool_calls:
            logger.info(f"子Agent完成任务，返回结果给主Agent")
            return assistant_message.content
        
        #如果调用工具，就执行工具函数
        for tool_call in assistant_message.tool_calls:
            function = tool_call.function
            tool_name = function.name #获取工具名
            tool_args = json.loads(function.arguments or "{}") #获取工具参数，可能没有参数则默认为空字典

            handler = TOOL_HANDLERS.get(tool_name)
            output = handler(**tool_args,tool_call_id=tool_call.id,state=state) if handler else f"Unknown tool: {tool_name}"

            print(f"> {tool_name}:")
            print(output[:200])

            sub_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })
    
    
 