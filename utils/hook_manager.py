"""
用户输入
  ↓
大模型推理
  ↓
模型请求工具
  ↓
PreToolUse Hook：检查 / 拦截 / 注入
  ↓
执行工具
  ↓
PostToolUse Hook：审查 / 记录 / 追加上下文
  ↓
工具结果返回模型
  ↓
模型继续推理或输出最终答案
"""

import json
import os
from pathlib import Path
import subprocess
WORKDIR = Path.cwd()
from utils.logger_handler import logger

"""
Hook 事件	     触发时机	     作用
SessionStart	程序启动后	     可以做初始化检查、打印提示、加载环境
PreToolUse	    工具执行前	     可以拦截危险命令、修改输入、注入提示
PostToolUse	    工具执行后	     可以检查输出、追加说明、记录日志
"""
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "SessionStart")
#定义 Hook 命令最大执行时间为 30 秒
HOOK_TIMEOUT = 30
#工作区信任标记。钩子只在该文件存在（或SDK模式）时运行。
TRUST_MARKER = WORKDIR / ".claude" / ".claude_trusted"

"""
HookManager 是这段代码的核心类，用来管理 Hook
1.从 .hooks.json 读取 Hook 配置；
2.检查当前工作区是否可信；
3.在指定事件发生时执行对应 Hook 命令。
"""
class HookManager:
    """
    参数	        作用
    config_path	    Hook 配置文件路径
    sdk_mode	    是否为 SDK 模式
    """
    def __init__(self, 
                 config_path: Path = None, 
                 sdk_mode: bool = False):
        
        self.hooks = {"PreToolUse": [], "PostToolUse": [], "SessionStart": []}
        self._sdk_mode = sdk_mode
        config_path = config_path or (WORKDIR / ".hooks.json")
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                for event in HOOK_EVENTS:
                    # 从配置中读取对应事件的 Hook 列表
                    self.hooks[event] = config.get("hooks", {}).get(event, [])
                logger.info(f"Hook configuration loaded from {config_path}")
            except Exception as e:
                logger.error(f"Failed to load hook configuration: {e}")
    
    def _check_workspace_trust(self) -> bool:
        """
        定义一个内部方法，用来判断当前工作区是否可信
        返回值是布尔值：
            True：可信
            False：不可信
        """
        if self._sdk_mode:
            return True
        return TRUST_MARKER.exists()
    

    def run_hooks(self, event: str, context: dict = None) -> dict:
        """
        定义运行 Hook 的方法。
        参数	  作用
        event	  Hook 事件名
        context	  当前工具调用上下文
        返回：一个字典，包含以下可能的键：
            blocked: 是否被 Hook 阻止执行工具（布尔值）
            messages: 表示要注入给 Agent 的消息。
        """
        result = {"blocked": False, "messages": []}
        # 如果不可信，直接返回默认结果，不执行任何 Hook
        if not self._check_workspace_trust():
            return result
        #取出当前事件对应的 Hook 列表。
        hooks = self.hooks.get(event, [])
        for hook_def in hooks:
            #hook_def是一个字典：{"matcher": "xxx","command": "xxxx"}
            matcher = hook_def.get("matcher")
            if matcher and context:
                tool_name = context.get("tool_name", "")
                # 判断当前 Hook 是否匹配这个工具
                if matcher != "*" and matcher != tool_name:
                    continue
            command = hook_def.get("command", "")
            if not command:
                continue
            # Build environment with hook context
            env = dict(os.environ)
            if context:
                env["HOOK_EVENT"] = event #把当前 Hook 事件名写入环境变量。
                env["HOOK_TOOL_NAME"] = context.get("tool_name", "")#把当前工具名写入环境变量
                env["HOOK_TOOL_INPUT"] = json.dumps(
                    context.get("tool_input", {}), ensure_ascii=False)[:10000]#把工具输入参数转换成 JSON 字符串，并写入环境变量。
                if "tool_output" in context:
                    env["HOOK_TOOL_OUTPUT"] = str(context["tool_output"])[:10000]#把工具输出写入环境变量
            try:
                r = subprocess.run(
                    command, shell=True, 
                    cwd=WORKDIR, 
                    env=env,
                    capture_output=True, 
                    text=True, 
                    timeout=HOOK_TIMEOUT,
                    encoding="utf-8",
                    errors="replace",
                )
                #如果 Hook 命令退出码是 0，表示正常通过
                if r.returncode == 0:
                    #如果 Hook 命令退出码是 0，表示正常通过， 打印 Hook 输出的前 100 个字符
                    if r.stdout.strip():
                        logger.info(f"  [hook:{event}] {r.stdout.strip()[:100]}")
                    try:
                        hook_output = json.loads(r.stdout) # 解析 Hook 输出
                        #如果 Hook 输出中包含 updatedInput 字段，并且当前有上下文。把上下文里的工具输入替换为 Hook 提供的新输入。
                        if "updatedInput" in hook_output and context:
                            context["tool_input"] = hook_output["updatedInput"]
                        #如果 Hook 输出中包含额外上下文。把额外上下文加入返回结果的 messages 列表
                        if "additionalContext" in hook_output:
                            result["messages"].append(hook_output["additionalContext"])
                        if "permissionDecision" in hook_output:
                            #如果 Hook 输出中包含权限决策。把权限决策保存到结果中。
                            result["permission_override"] = (hook_output["permissionDecision"])
                    except (json.JSONDecodeError, TypeError):
                        pass  
                #如果 Hook 命令退出码为 1，表示阻止执行。
                elif r.returncode == 1:
                    result["blocked"] = True
                    reason = r.stderr.strip() or "Blocked by hook"
                    result["block_reason"] = reason
                    logger.warning(f"  [hook:{event}] BLOCKED: {reason[:200]}")
                # 如果 Hook 命令退出码为 2，表示注入消息
                elif r.returncode == 2:
                    msg = r.stderr.strip()
                    if msg:
                        result["messages"].append(msg)
                        logger.warning(f"  [hook:{event}] INJECT: {msg[:200]}")
            except subprocess.TimeoutExpired:
                #如果 Hook 命令执行超过 30 秒
                logger.warning(f"  [hook:{event}] Timeout ({HOOK_TIMEOUT}s)")
            except Exception as e:
                logger.error(f"  [hook:{event}] Error: {e}")
        return result