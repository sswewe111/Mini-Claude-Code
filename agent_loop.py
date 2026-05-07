import os
import json
import time
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
from pathlib import Path

WORKDIR = Path.cwd()
from openai import APIError, OpenAI
from dotenv import load_dotenv
from utils.logger_handler import logger
from utils.config_handler import compact_config,recovery_config
from state.agent_state import CompactState

#导入工具配置
from tools_configs import TOOLS,TASK,TASK_MANAGER,TEAM_TASK,WORKTREE_TASK
#导入agent state
from state.agent_state import LoopState
#导入utils里的相关函数
from utils.path_sandbox import safe_path
from utils.normalize_messages import normalize_messages
from utils.message_log import save_message_log
from utils.build_system_prompt import build_system_prompt

#导入工具函数映射表
from tools_handlers import TOOL_HANDLERS
from tools.compact_tools import micro_compact,estimate_context_size,compact_history

from manager.memory_manager import memory_mgr
from manager.system_prompt_builder_manager import SystemPromptBuilder
from manager.recovery_manager import auto_compact,backoff_delay
from manager.background_manager import BG
from manager.cron_scheduler_manager import scheduler
from tools.message_bus import BUS

#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

#工具配置
TOOLS = TOOLS+TASK+WORKTREE_TASK+TEAM_TASK
#工具名映射到处理函数
TOOL_HANDLERS = TOOL_HANDLERS 
#动态构建系统提示词
prompt_builder = SystemPromptBuilder(workdir=WORKDIR, tools=TOOLS)

def agent_loop(state: LoopState,compact: CompactState):
    max_output_recovery_count = 0
    while True:
        #每轮循环开始时，先检查是否需要读取队友的写在邮箱的消息，如果有就把消息内容追加到消息列表中
        inbox = BUS.read_inbox("lead")
        if inbox:
            state.messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })

        #每轮循环开始时，先检查是否有定时任务需要执行，如果有就把结果追加到消息列表中
        notifications = scheduler.drain_notifications()
        for note in notifications:
            print(f"[Cron notification] {note[:100]}")
            state.messages.append({"role": "user", "content": note})

        #每轮循环开始时，先检查后台任务的完成通知，并把通知内容追加到消息列表中
        notifs = BG.drain_notifications()
        if notifs and state.messages:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['preview']} "
                f"(output_file={n['output_file']})"
                for n in notifs
            )
            state.messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})

        #动态构建系统提示词
        system=prompt_builder.build()
        #判断工具使用是否超过阈值，如果超过就压缩
        state.messages[:] = micro_compact(state.messages)
        if estimate_context_size(state.messages) > compact_config["CONTEXT_LIMIT"]:
            state.messages[:] = compact_history(state.messages, compact)

        # 错误恢复
        response = None
        for attempt in range(recovery_config.get("MAX_RECOVERY_ATTEMPTS", 3) + 1):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=normalize_messages([
                        {"role": "system", "content": system},
                        *state.messages,
                    ]),
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=80000,
                )
                break  # 成功则跳出重试循环
            except APIError as e:
                error_body = str(e).lower()
                # Strategy 2: 上下文太长时，先压缩再重试
                if "overlong_prompt" in error_body or ("prompt" in error_body and "long" in error_body):
                    print(f"[Recovery] Prompt too long. Compacting... (attempt {attempt + 1})")
                    state.messages[:] = auto_compact(state.messages)
                    continue
                # Strategy 3: 连接抖动时，退避重试
                if attempt < recovery_config.get("MAX_RECOVERY_ATTEMPTS", 3):
                    delay = backoff_delay(attempt)
                    print(f"[Recovery] API error: {e}. "
                          f"Retrying in {delay:.1f}s (attempt {attempt + 1}/{recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)})")
                    time.sleep(delay)
                    continue
                print(f"[Error] API call failed after {recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)} retries: {e}")
                return
            except (ConnectionError, TimeoutError, OSError) as e:
                # Strategy 3: 连接抖动时，退避重试
                if attempt < recovery_config.get("MAX_RECOVERY_ATTEMPTS", 3):
                    delay = backoff_delay(attempt)
                    print(f"[Recovery] Connection error: {e}. "
                          f"Retrying in {delay:.1f}s (attempt {attempt + 1}/{recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)})")
                    time.sleep(delay)
                    continue
                print(f"[Error] Connection failed after {recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)} retries: {e}")
                return

        if response is None:
            logger.error("[Error] No response received.")
            return
        

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

         # -- Strategy 1: 输出被截断时，做续写 --
        finish_reason = response.choices[0].finish_reason
        print(f"模型停止原因:{finish_reason}")
        if finish_reason == "length":
            max_output_recovery_count += 1
            if max_output_recovery_count <= recovery_config.get("MAX_RECOVERY_ATTEMPTS", 3):
                print(
                    f"[Recovery] max_tokens hit "
                    f"({max_output_recovery_count}/{recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)}). "
                    "Injecting continuation..."
                )
                state.messages.append({
                    "role": "user",
                    "content": recovery_config["CONTINUATION_MESSAGE"],
                })
                continue
            else:
                print(
                    f"[Error] max_tokens recovery exhausted "
                    f"({recovery_config.get('MAX_RECOVERY_ATTEMPTS', 3)} attempts). Stopping."
                )
                return

        max_output_recovery_count = 0

        #如果没有调用工具就结束循环
        if not assistant_message.tool_calls:
            return
         
        for tool_call in assistant_message.tool_calls:
            function = tool_call.function
            tool_name = function.name #获取工具名
            tool_args = json.loads(function.arguments or "{}") #获取工具参数，可能没有参数则默认为空字典

            handler = TOOL_HANDLERS.get(tool_name)
            if tool_name == "compact":
                output = handler(**tool_args,state=compact,messages=state.messages) if handler else f"Unknown tool: {tool_name}"
            elif tool_name == "read_file" or tool_name == "task" :
                output = handler(**tool_args,state=compact,tool_call_id=tool_call.id) if handler else f"Unknown tool: {tool_name}"
            elif tool_name == "spawn_teammate":
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
    
    # 加载现存的历史记忆
    memory_mgr.load_all()
    mem_count = len(memory_mgr.memories)
    print(f"Loaded {mem_count} memories into memory manager.")
    if mem_count:
        print(f"[{mem_count} memories loaded into context]")
    else:
        print("[No existing memories. The agent can create them with save_memory.]")

    history = []
    recent_files = []
    #query="程序运行在windows系统上，我喜欢使用bash命令查看目录和阅读txt文件，请帮我总结data/read_file.txt的内容，并保存长期记忆"
    query="请设置两个teammate，teammate1用bash命令查看当前目录，teammate2阅读txt文件并总结data/read_file.txt的内容，上述任务最后发送给lead。最后由lead先介绍当前目录，再给我data/read_file.txt的总结。lead最后将两个teammate关闭"
    history.append({"role": "user", "content": query})
    state = LoopState(messages=history)
    compact=CompactState(recent_files=recent_files)
    agent_loop(state, compact)

    for messages in history:
        print("==--==" * 10)
        print(f"消息角色：{messages['role']}: {messages['content']}")
        print("==--==" * 10)

        