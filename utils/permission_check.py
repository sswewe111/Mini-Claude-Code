from fnmatch import fnmatch
import json

from utils.bash_check import bash_validator
from utils.config_handler import permission_config
from utils.logger_handler import logger

MODES = permission_config["modes"]
READ_ONLY_TOOLS = set(permission_config["read_only_tools"])
WRITE_TOOLS = set(permission_config["write_tools"])

DEFAULT_RULES = permission_config["default_rules"]

class PermissionManager:
    """
    Manages permission decisions for tool calls.
    Pipeline: deny_rules -> mode_check -> allow_rules -> ask_user
    The teaching version keeps the decision path short on purpose so readers
    can implement it themselves before adding more advanced policy layers.
    """
    def __init__(self, mode: str = "default", rules: list = None):
        #判断权限是否在配置里
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}. Choose from {MODES}")
        self.mode = mode
        #是否传入权限规则，不传入就使用默认规则
        self.rules = rules or list(DEFAULT_RULES)
        #记录当前已经连续拒绝了多少次工具调用
        self.consecutive_denials = 0
        # 设置最大连续拒绝次数阈值
        self.max_consecutive_denials = 3

    """
    输入：
        tool_name：工具名称
        tool_input：工具输入
    输出：
        {"behavior": "allow"|"deny"|"ask", "reason": str}
    """    
    def check(self, tool_name: str, tool_input: dict) -> dict:
        # Step 0: 权限系统检查
        if tool_name == "bash":
            logger.info("执行 Bash 工具调用，进行安全检查")
            command = tool_input.get("command", "")
            failures = bash_validator.validate(command)
            if failures:
                severe = {
                    "cmd_delete",
                    "cmd_recursive_delete",
                    "cmd_remove_directory",
                    "cmd_remove_directory_tree",
                    "powershell_remove_item",
                    "powershell_remove_item_recursive",
                    "powershell_remove_item_force",
                    "unix_style_delete",
                    "unix_style_recursive_delete",
                }

                severe_hits = [f for f in failures if f[0] in severe]
                if severe_hits:
                    logger.info("发现严重安全问题，直接拒绝")
                    desc = bash_validator.describe_failures(command)
                    return {"behavior": "deny",
                            "reason": f"Bash validator: {desc}"}
                #一般情况下的安全问题，需要用户确认
                logger.info("发现一般安全问题，需要用户确认")
                desc = bash_validator.describe_failures(command)
                return {"behavior": "ask","reason": f"Bash validator flagged: {desc}"}
        # Step 1: 如果命令匹配到 deny 规则，直接拒绝
        logger.info("deny rules 拒绝规则检查")
        for rule in self.rules:
            if rule["behavior"] != "deny":
                #logger.debug(f"Rule {rule} 不是 deny rule, 通过.")
                continue
            if self._matches(rule, tool_name, tool_input):
                #logger.info(f"Tool {tool_name} 被拒绝规则组织: {rule}")
                return {"behavior": "deny","reason": f"Blocked by deny rule: {rule}"}
        #logger.info("通过 deny rule 检查，继续下一步：模式检查")
        # Step 2: 模式检查
        logger.info(f"mode: {self.mode} 进行模式检查")
        if self.mode == "plan":
            # Plan mode: 拒绝所有写操作，允许读取
            if tool_name in WRITE_TOOLS:
                #logger.info(f"mode: {self.mode} 只能读文件")
                return {"behavior": "deny","reason": "Plan mode: write operations are blocked"}
            #logger.info(f"mode: {self.mode} 执行通过")
            return {"behavior": "allow", "reason": "Plan mode: read-only allowed"}
        if self.mode == "auto":
            # Auto mode: 自动允许只读工具，对写操作进行询问
            if tool_name in READ_ONLY_TOOLS or tool_name == "read_file":
                #logger.info(f"mode: {self.mode} 自动读取文件")
                return {"behavior": "allow","reason": "Auto mode: read-only tool auto-approved"}
            pass
        # Step 3: 允许规则
        logger.info("allow rules 允许规则检查")
        for rule in self.rules:
            if rule["behavior"] != "allow":
                #logger.debug(f"Rule {rule} 不是 allow rule, 继续执行.")
                continue
            if self._matches(rule, tool_name, tool_input):
                #logger.info(f"Rule {rule} 匹配到允许规则，就直接执行")
                self.consecutive_denials = 0
                return {"behavior": "allow","reason": f"Matched allow rule: {rule}"}
        # Step 4: 询问用户
        #logger.info(f"没有找到匹配的规则 {tool_name}, ask user 请求用户确认")
        return {"behavior": "ask","reason": f"No rule matched for {tool_name}, asking user"}
    
    
    """
    判断一条规则是否匹配当前工具调用
    输入：
        rule：规则字典
        tool_name：工具名称
        tool_input：工具输入
    输出：
        bool：是否匹配
    """
    def _matches(self, rule: dict, tool_name: str, tool_input: dict) -> bool:
        # 如果工具不在规则内，返回False
        if rule.get("tool") and rule["tool"] != "*":
            if rule["tool"] != tool_name:
                return False
        # 如果有路径就判断路径是否匹配
        if "path" in rule and rule["path"] != "*":
            path = tool_input.get("path", "")
            if not fnmatch(path, rule["path"]):
                return False
        # 判断命令是否匹配
        if "content" in rule:
            command = tool_input.get("command", "")
            if not fnmatch(command, rule["content"]):
                return False
        return True
    
    def ask_user(self, tool_name: str, tool_input: dict) -> bool:
        """Interactive approval prompt. Returns True if approved."""
        preview = json.dumps(tool_input, ensure_ascii=False)[:200]
        print(f"\n  [Permission] {tool_name}: {preview}")
        try:
            answer = input("  Allow? (y/n/always): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer == "always":
            # Add permanent allow rule for this tool
            self.rules.append({"tool": tool_name, "path": "*", "behavior": "allow"})
            self.consecutive_denials = 0
            return True
        if answer in ("y", "yes"):
            self.consecutive_denials = 0
            return True
        # Track denials for circuit breaker
        self.consecutive_denials += 1
        if self.consecutive_denials >= self.max_consecutive_denials:
            print(f"  [{self.consecutive_denials} consecutive denials -- "
                  "consider switching to plan mode]")
        return False