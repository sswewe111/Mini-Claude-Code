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
from utils.logger_handler import logger
from utils.config_handler import compact_config
from state.agent_state import CompactState

#导入提示词
from system_prompt import SYSTEM_TEST,SYSTEM_COMPACT,SYSTEM_PERMISSION,SYSTEM_HOOK 
#导入工具配置
from tools_configs import TOOLS,TASK
#导入agent state
from state.agent_state import LoopState
#导入utils里的相关函数
from utils.path_sandbox import safe_path
from utils.normalize_messages import normalize_messages
from utils.message_log import save_message_log
from utils.permission_check import PermissionManager
#导入工具函数映射表
from tools_handlers import TOOL_HANDLERS
from tools.compact_tools import micro_compact,estimate_context_size,compact_history

#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

#系统提示词
SYSTEM =SYSTEM_HOOK
#工具配置
TOOLS = TOOLS+TASK
#工具名映射到处理函数
TOOL_HANDLERS = TOOL_HANDLERS 

def agent_loop(state: LoopState,compact: CompactState,perms: PermissionManager):
    while True:
        
        #判断工具使用是否超过阈值，如果超过就压缩
        state.messages[:] = micro_compact(state.messages)
        if estimate_context_size(state.messages) > compact_config["CONTEXT_LIMIT"]:
            state.messages[:] = compact_history(state.messages, compact)

        #使用消息规范化函数将消息列表转换为模型输入格式，并调用模型生成回复
        response = client.chat.completions.create(
            model=MODEL,
            messages=normalize_messages([
                {"role": "system", "content": SYSTEM},
                *state.messages,
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

        save_message_log(
            message=assistant_record,
            token=response.usage,
        )

        state.messages.append(assistant_record)
        
        #如果没有调用工具就结束循环
        if not assistant_message.tool_calls:
            return
         
        for tool_call in assistant_message.tool_calls:
            function = tool_call.function
            tool_name = function.name #获取工具名
            tool_args = json.loads(function.arguments or "{}") #获取工具参数，可能没有参数则默认为空字典

            


            #进行权限检查
            decision = perms.check(tool_name, tool_args)
            if decision["behavior"] == "deny":
                logger.info(f"工具调用被拒绝: {tool_name}")
                output = f"Permission denied: {decision['reason']}"

            elif decision["behavior"] == "ask":
                logger.info(f"需要用户确认: {tool_name}")
                if perms.ask_user(tool_name, tool_args):
                    logger.info(f"用户确认了工具调用: {tool_name}")
                    handler = TOOL_HANDLERS.get(tool_name)
                    if tool_name == "compact":
                        output = handler(**tool_args,state=compact,messages=state.messages) if handler else f"Unknown tool: {tool_name}"
                    elif tool_name == "read_file":
                        output = handler(**tool_args,state=compact,tool_call_id=tool_call.id) if handler else f"Unknown tool: {tool_name}"
                    else:
                        output = handler(**tool_args,tool_call_id=tool_call.id) if handler else f"Unknown tool: {tool_name}"
                else:
                     logger.info(f"用户拒绝了工具调用: {tool_name}")
                     output = f"Permission denied by user for {tool_name}"

            else:# allow
                logger.info(f"工具未被拒绝，也不需要询问用户，直接调用: {tool_name}")
                handler = TOOL_HANDLERS.get(tool_name)
                if tool_name == "compact":
                    output = handler(**tool_args,state=compact,messages=state.messages) if handler else f"Unknown tool: {tool_name}"
                elif tool_name == "read_file":
                    output = handler(**tool_args,state=compact,tool_call_id=tool_call.id) if handler else f"Unknown tool: {tool_name}"
                else:
                    output = handler(**tool_args,tool_call_id=tool_call.id) if handler else f"Unknown tool: {tool_name}"


            tool_record = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            }

            state.messages.append(tool_record)

            save_message_log(
                message=tool_record,
                token=None,
            )
        


if __name__ == "__main__":
    
    history = []
    recent_files = []
    query="我想要知道当前目录下的文件，并到找到一个read_file.txt文件，请总结50字的内容给我。"
    #query="请帮我删除test文件夹"
    history.append({"role": "user", "content": query})
    state = LoopState(messages=history)
    compact=CompactState(recent_files=recent_files)
    perms = PermissionManager(mode="auto")
    agent_loop(state, compact, perms)

    for messages in history:
        print("--" * 10)
        print(f"消息角色：{messages['role']}: {messages['content']}")
        print("--" * 10)

        