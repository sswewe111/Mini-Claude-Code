import json
import os
from pathlib import Path
import threading
import time

from utils.message_log import save_message_log
from utils.normalize_messages import normalize_messages
WORKDIR = Path.cwd()
TEAM_DIR = WORKDIR / ".team"

from tools.message_bus import BUS

from openai import APIError, OpenAI
from dotenv import load_dotenv
from utils.logger_handler import logger
from state.agent_state import CompactState
from manager.sub_tools.tools_config import TEAMMATE_TASK
from manager.sub_tools.tools_handlers import TOOL_HANDLERS
from tools.auto_tools import ensure_identity_context,scan_unclaimed_tasks,claim_task
#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

POLL_INTERVAL = 5
IDLE_TIMEOUT = 120



#定义一些工具函数的映射，这些工具函数会被 teammate 的 agent loop 调用

TOOL_HANDLERS=TOOL_HANDLERS
TEAMMATE_TASK=TEAMMATE_TASK

"""
TeammateManager：负责“队友生命周期管理”，包括注册 teammate、保存状态、启动线程、执行 teammate 自己的 agent loop。
1.维护 .team/config.json。
2.记录 teammate 的名字、角色、状态。
3.创建 teammate 线程。
4.运行每个 teammate 的独立 agent loop。
5.提供 teammate 可用的工具。
6.调度 teammate 的工具调用。
"""
class TeammateManager:
    
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}
    
    #如果 .team/config.json 存在，就读取它。如果不存在，就返回默认配置：
    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}
    
    #把当前配置写回 .team/config.json。ndent=2 只是为了格式化 JSON，方便人类阅读。
    def _save_config(self):
        self.config_path.write_text(json.dumps(self.config, indent=2),encoding="utf-8")

    # 根据名字查找 teammate。如果找到了，返回成员 dict {"name": "alice", "role": "coder", "status": "idle"}
    def _find_member(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None
    
    """
    用于更新队友的状态
    """
    def _set_status(self, name: str, status: str):
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()
    
    """
    启动一个 teammate。
    1.name：teammate 名字，比如 "alice"。
    2.role：角色，比如 "coder"、"reviewer"。
    3.prompt：给 teammate 的初始任务。
    """
    def spawn(self, name: str, role: str, prompt: str,state: CompactState = None) -> str:
        logger.info(f"Spawning teammate '{name}' with role '{role}'")
        member = self._find_member(name)#先查找是否已经存在该成员
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:#如果成员不存在，就创建新成员
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt,state),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"
    
    # 这是每个 teammate 独立运行的 agent loop。
    def _teammate_loop(self, name: str, role: str, prompt: str,state: CompactState = None):
        logger.info(f"Teammate '{name}' started with role '{role}' ")
        team_name=self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            f"Use idle tool when you have no more work. You will auto-claim new tasks."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = TEAMMATE_TASK
        
        for _ in range(50):
            inbox = BUS.read_inbox(name)
            for msg in inbox:
                # 如果得到关机需求，将队友关机
                if msg.get("type") == "shutdown_request":
                    self._set_status(name, "shutdown")
                    return
                messages.append({"role": "user", "content": json.dumps(msg)})
            
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=normalize_messages([
                        {"role": "system", "content": sys_prompt},
                        *messages,
                    ]),
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=80000,
                )
            except Exception:
                self._set_status(name, "idle")
                return
            assistant_message = response.choices[0].message
            assistant_record = {
                "role": "assistant",
                "content": assistant_message.content,
            }
            if assistant_message.tool_calls:
                assistant_record["tool_calls"] = [
                    tool_call.model_dump() for tool_call in assistant_message.tool_calls 
                ]
            messages.append(assistant_record)
            save_message_log(
                message=assistant_record,
                token=response.usage,
            )
            

            #如果没有调用工具就结束循环
            if not assistant_message.tool_calls:
                break
            idle_requested = False
            for tool_call in assistant_message.tool_calls:
                function = tool_call.function
                tool_name = function.name #获取工具名
                tool_args = json.loads(function.arguments or "{}") #获取工具参数，可能没有参数则默认为空字典

                handler = TOOL_HANDLERS.get(tool_name)

                #如果调用idle工具，就进入idle模式，工作就结束了
                if tool_name == "idle":
                    idle_requested = True
                    output = "Entering idle phase. Will poll for new tasks."
                elif tool_name=="claim_task":
                    role=self._find_member(name).get("role") if self._find_member(name) else None,
                    output = handler(args=tool_args,sender=name,role=role) if handler else f"Unknown tool: {tool_name}"
                elif tool_name == "shutdown_response":
                    output = handler(args=tool_args,tool_call_id=tool_call.id,sender=name) if handler else f"Unknown tool: {tool_name}"
                else:
                    output = handler(**tool_args,tool_call_id=tool_call.id,sender=name,state=state) if handler else f"Unknown tool: {tool_name}"

                tool_record = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output,
                }

            messages.append(tool_record)

            save_message_log(
                message=tool_record,
                token=None,
            )

            #判断如果工具调用了 idle，就进入 idle 模式，定期检查 inbox 和未认领任务，并自动认领新任务。如果工具调用了 shutdown，就关机。否则继续循环。
            if idle_requested:
                break
        
        #当队友空闲时开始等待新任务
        self._set_status(name, "idle")
        resume = False
        polls = IDLE_TIMEOUT // max(POLL_INTERVAL, 1)
        for _ in range(polls):
            time.sleep(POLL_INTERVAL)
            #1.读取队友邮箱消息
            inbox = BUS.read_inbox(name)
            if inbox:
                ensure_identity_context(messages, name, role, team_name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                resume = True
                break
            # 2.扫描未认领任务
            unclaimed = scan_unclaimed_tasks(role)
            if unclaimed:
                task = unclaimed[0]
                claim_result = claim_task(
                    task["id"], name, role=role, source="auto"
                )
                if claim_result.startswith("Error:"):
                    continue
                task_prompt = (
                    f"<auto-claimed>Task #{task['id']}: {task['subject']}\n"
                    f"{task.get('description', '')}</auto-claimed>"
                )
                ensure_identity_context(messages, name, role, team_name)
                messages.append({"role": "user", "content": task_prompt})
                messages.append({"role": "assistant", "content": f"{claim_result}. Working on it."})
                resume = True
                break
        #空闲超时处理
        if not resume:
            self._set_status(name, "shutdown")
            return
        #恢复工作状态
        self._set_status(name, "working")

    
    
    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)
    
    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]
    
TEAM = TeammateManager(TEAM_DIR)