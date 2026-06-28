# Mini Claude Code

Mini Claude Code 是一个用于学习和复刻 Claude Code 核心机制的 Python 项目。它不是一个完整的商业级 CLI，而是把 Agent 主循环、工具调用、路径沙箱、计划管理、子代理、技能、记忆、上下文压缩、权限、Hook、任务系统、后台任务、定时调度、团队协作、Worktree 隔离以及 MCP/插件等能力拆开实现，方便逐章理解和二次开发。

项目学习参考：[shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)

## 项目目标

这个仓库关注的是“代码智能体运行时”本身，而不是某一个具体业务应用。核心目标包括：

- 用最小可读代码实现 Agent Loop：模型产生工具调用，宿主程序执行工具，再把结果写回上下文继续推理。
- 把工具系统从简单的读写文件、执行命令，逐步扩展到任务、团队、后台运行、定时调度和 MCP 外部工具。
- 演示 Claude Code 类产品中常见的工程机制：权限检查、上下文压缩、记忆注入、技能加载、Worktree 隔离和协议化协作。
- 用 `docs/` 中的章节文档对应代码模块，形成“概念 -> 代码 -> 流程”的学习路径。

## 核心架构

主流程从 [agent_loop.py](agent_loop.py) 进入：

1. 加载 `.env` 中的模型配置，使用 OpenAI SDK 的 Chat Completions 兼容接口调用模型。
2. 动态构建 system prompt，注入工具列表、技能摘要、长期记忆、`CLAUDE.md` 指令和运行时上下文。
3. 调用模型并读取 assistant 消息。
4. 如果模型没有请求工具，循环结束。
5. 如果模型请求工具，根据工具名在 `TOOL_HANDLERS` 中找到处理函数并执行。
6. 将工具执行结果以 `tool` 消息写回 `messages`，进入下一轮模型调用。
7. 每轮循环前处理队友消息、后台任务通知、定时任务通知，并在上下文过长时触发压缩。

简化流程如下：

```text
user input
  -> build system prompt
  -> model call
  -> assistant text: finish
  -> assistant tool_call
       -> local handler / manager / MCP router
       -> tool_result
       -> append messages
       -> next model call
```

## 主要功能

### Agent 循环

[agent_loop.py](agent_loop.py) 实现主 Agent 的推理和工具执行循环。它负责：

- 调用模型；
- 维护 `messages`；
- 分发工具调用；
- 保存消息日志；
- 处理输出截断续写；
- 处理 API 错误、连接错误和上下文过长后的恢复。

相关文档：[docs/01.Agent循环.md](docs/01.Agent循环.md)

### 工具系统

工具定义集中在 [tools_configs.py](tools_configs.py)，工具分发集中在 [tools_handlers.py](tools_handlers.py)。当前内置工具覆盖：

- `bash`：在当前工作区执行 Windows shell 命令；
- `read_file` / `write_file` / `edit_file`：文件读取、写入和精确替换；
- `todo`：维护当前会话计划；
- `task`：启动一次隔离上下文的子代理；
- `load_skill`：按名称加载完整技能文档；
- `compact`：压缩历史上下文；
- `save_memory`：保存跨会话记忆；
- `background_run` / `check_background`：后台命令执行与状态查询；
- `cron_create` / `cron_delete` / `cron_list`：定时调度；
- `spawn_teammate` / `send_message` / `broadcast`：团队成员和消息通信；
- `task_create` / `task_update` / `task_list` / `task_get`：持久任务管理；
- `worktree_create` / `worktree_run` / `worktree_closeout`：Git worktree 隔离工作区管理。

相关文档：[docs/02.工具使用（路径沙箱、消息规范化）.md](docs/02.工具使用（路径沙箱、消息规范化）.md)

### 路径沙箱与消息规范化

[utils/path_sandbox.py](utils/path_sandbox.py) 用于限制文件访问路径，避免工具随意读写工作区外部文件。[utils/normalize_messages.py](utils/normalize_messages.py) 在每次模型调用前规范化消息结构，确保工具调用和工具结果能被模型接口正确接受。

### Todo 与任务系统

项目同时实现了两类任务概念：

- `todo`：当前会话内的轻量计划，适合多步骤推理和进度同步。
- `.tasks/` 持久任务：每个任务是 JSON 文件，支持状态、负责人、依赖关系和 worktree 绑定。

相关代码：

- [manager/todo_manager.py](manager/todo_manager.py)
- [manager/task_manager.py](manager/task_manager.py)

相关文档：

- [docs/03.代办写入—制定计划.md](docs/03.代办写入—制定计划.md)
- [docs/12.任务系统.md](docs/12.任务系统.md)

### 子代理与团队协作

子代理由 [subagent/read_agent.py](subagent/read_agent.py) 实现，适合一次性委派读取、分析或探索任务。

团队系统由 [manager/teammate_manager.py](manager/teammate_manager.py) 和 [tools/message_bus.py](tools/message_bus.py) 实现。它支持：

- 创建长期运行的 teammate；
- 为 teammate 分配角色和初始任务；
- 通过 inbox 发送消息；
- teammate 空闲后自动轮询新任务；
- 通过结构化协议处理关机、计划审批等请求。

相关文档：

- [docs/04.子代理—父智能体和子智能体.md](docs/04.子代理—父智能体和子智能体.md)
- [docs/15.Agent团队.md](docs/15.Agent团队.md)
- [docs/16.团队协议 .md](docs/16.团队协议%20.md)
- [docs/17.自主代理.md](docs/17.自主代理.md)

### 技能系统

技能位于 `skills/` 目录，每个技能以 `SKILL.md` 作为入口。系统会读取 frontmatter 中的 `name` 和 `description`，先把技能摘要注入 system prompt，只有当模型显式调用 `load_skill` 时才加载完整技能内容。

当前仓库包含文档、表格、演示文稿、PDF、前端设计和网页访问相关技能示例。

相关代码：[tools/skills_tools.py](tools/skills_tools.py)

相关文档：[docs/05.技能系统.md](docs/05.技能系统.md)

### 上下文压缩与错误恢复

[tools/compact_tools.py](tools/compact_tools.py) 提供上下文估算、工具输出压缩、大输出落盘、转录保存和历史总结能力。[manager/recovery_manager.py](manager/recovery_manager.py) 提供错误恢复策略，例如：

- prompt 过长时自动压缩；
- API 或网络错误时按退避策略重试；
- 模型输出达到 `max_tokens` 时注入续写提示；
- 大型工具结果保存到 `.task_outputs/tool-results/`。

相关文档：

- [docs/06.上下文压缩.md](docs/06.上下文压缩.md)
- [docs/11.错误恢复.md](docs/11.错误恢复.md)

### 权限与 Hook

权限配置位于 [configs/permission_config.yml](configs/permission_config.yml)。权限系统支持按工具、命令内容和路径进行 allow/deny 判断，并对危险命令做基础拦截。

Hook 系统由 [utils/hook_manager.py](utils/hook_manager.py) 实现，用于在关键执行点插入外部命令或校验逻辑。

相关文档：

- [docs/07.权限系统.md](docs/07.权限系统.md)
- [docs/08.Hook 系统.md](docs/08.Hook%20系统.md)

### 记忆系统

长期记忆由 [manager/memory_manager.py](manager/memory_manager.py) 管理，默认写入 `.memory/`。每条记忆是一个带 frontmatter 的 Markdown 文件，并通过 `MEMORY.md` 维护索引。

记忆适合保存跨会话仍有价值、且不容易从代码直接推导的信息，例如用户偏好、项目约定、历史反馈或外部资源位置。临时任务状态、源码结构、密钥不应写入记忆。

相关文档：[docs/09.记忆系统.md](docs/09.记忆系统.md)

### 动态系统提示词

[manager/system_prompt_builder_manager.py](manager/system_prompt_builder_manager.py) 将 system prompt 拆成多个 section：

- 核心行为指令；
- 可用工具列表；
- 技能摘要；
- 长期记忆；
- `CLAUDE.md` 指令；
- 当前日期、工作目录、模型和平台信息。

相关文档：[docs/10.系统提示词.md](docs/10.系统提示词.md)

### 后台任务与定时调度

[manager/background_manager.py](manager/background_manager.py) 支持把耗时命令放入后台线程执行，立即返回 `task_id`，完成后把摘要通知注入下一轮 Agent 上下文。

[manager/cron_scheduler_manager.py](manager/cron_scheduler_manager.py) 实现简单 cron 调度，支持一次性任务和持久化任务。

相关文档：

- [docs/13.后台任务.md](docs/13.后台任务.md)
- [docs/14.定时调度.md](docs/14.定时调度.md)

### Worktree 隔离

[manager/worktree_manager.py](manager/worktree_manager.py) 使用 Git worktree 为任务创建隔离工作区，并维护 `.worktrees/index.json`。它支持创建、进入、运行命令、查看状态、保留或移除 worktree，并将生命周期事件记录到事件总线。

相关文档：[docs/18.Worktree隔离.md](docs/18.Worktree隔离.md)

### MCP 与插件

`mcp/` 目录实现了一个教学版 MCP/插件接入层：

- [mcp/plugin_loader.py](mcp/plugin_loader.py)：扫描 `.claude-plugin/plugin.json`；
- [mcp/mcp_client.py](mcp/mcp_client.py)：启动并连接外部 MCP server；
- [mcp/mcp_tool_router.py](mcp/mcp_tool_router.py)：根据 `mcp__server__tool` 前缀路由工具调用；
- [mcp/build_tool.py](mcp/build_tool.py)：合并本地工具和 MCP 工具池；
- [mcp/gapability_permission_gate.py](mcp/gapability_permission_gate.py)：外部能力权限闸门。

相关文档：[docs/19.MCP与插件.md](docs/19.MCP与插件.md)

## 目录结构

```text
Mini Claude Code/
├── agent_loop.py              # 主 Agent 循环入口
├── system_prompt.py           # 基础 system prompt 片段
├── tools_configs.py           # 主 Agent 可见的工具 schema
├── tools_handlers.py          # 工具名到处理函数的分发映射
├── configs/                   # 权限、压缩、恢复、记忆、todo 等配置
├── docs/                      # 01-19 章节学习文档
├── manager/                   # 任务、记忆、团队、后台、调度、worktree 等管理器
├── mcp/                       # MCP/插件发现、连接、路由和权限闸门
├── skills/                    # 技能目录，每个技能包含 SKILL.md
├── state/                     # Agent 状态数据结构
├── subagent/                  # 子代理实现
├── tools/                     # 文件、bash、技能、压缩、消息、自动认领等工具实现
├── utils/                     # 路径沙箱、消息规范化、日志、权限、Hook 等通用能力
├── .memory/                   # 运行时长期记忆
├── .tasks/                    # 持久任务 JSON
├── .team/                     # 团队成员状态
├── .runtime-tasks/            # 后台任务状态和日志
├── .task_outputs/             # 大型工具输出落盘
└── .worktrees/                # Git worktree 索引和隔离工作区
```

## 环境准备

建议使用 Python 3.10+。

安装基础依赖：

```bash
pip install openai python-dotenv pyyaml
```

创建 `.env`：

```env
ANTHROPIC_BASE_URL=https://your-openai-compatible-endpoint/v1
ANTHROPIC_AUTH_TOKEN=your_api_key
MODEL_ID=your_model_id
```

变量名沿用了学习实现里的命名，但实际代码通过 `openai.OpenAI` 调用 OpenAI 兼容接口。

## 运行方式

当前 [agent_loop.py](agent_loop.py) 的 `__main__` 中包含硬编码示例 query。你可以直接修改该 query 后运行：

```bash
python agent_loop.py
```

如果要把它改造成交互式 CLI，可以在 `__main__` 中将示例 query 替换为 `input()`，再把用户输入写入 `LoopState(messages=[...])`。

## 配置说明

- [configs/compact_config.yml](configs/compact_config.yml)：上下文长度阈值、大输出落盘阈值、转录目录等。
- [configs/recovery_config.yml](configs/recovery_config.yml)：最大恢复次数、退避时间、输出截断续写提示。
- [configs/permission_config.yml](configs/permission_config.yml)：工具读写分类、命令 deny/allow 规则。
- [configs/memory_config.yml](configs/memory_config.yml)：记忆目录、索引文件、记忆类型和整理参数。
- [configs/todo_manager.yml](configs/todo_manager.yml)：todo 计划提醒相关配置。

## 文档索引

`docs/` 目录按功能演进顺序组织：

1. [Agent循环](docs/01.Agent循环.md)
2. [工具使用（路径沙箱、消息规范化）](docs/02.工具使用（路径沙箱、消息规范化）.md)
3. [代办写入—制定计划](docs/03.代办写入—制定计划.md)
4. [子代理—父智能体和子智能体](docs/04.子代理—父智能体和子智能体.md)
5. [技能系统](docs/05.技能系统.md)
6. [上下文压缩](docs/06.上下文压缩.md)
7. [权限系统](docs/07.权限系统.md)
8. [Hook 系统](docs/08.Hook%20系统.md)
9. [记忆系统](docs/09.记忆系统.md)
10. [系统提示词](docs/10.系统提示词.md)
11. [错误恢复](docs/11.错误恢复.md)
12. [任务系统](docs/12.任务系统.md)
13. [后台任务](docs/13.后台任务.md)
14. [定时调度](docs/14.定时调度.md)
15. [Agent团队](docs/15.Agent团队.md)
16. [团队协议](docs/16.团队协议%20.md)
17. [自主代理](docs/17.自主代理.md)
18. [Worktree隔离](docs/18.Worktree隔离.md)
19. [MCP与插件](docs/19.MCP与插件.md)

## 开发提示

- 新增工具时，通常需要同时修改 `tools_configs.py` 的 schema 和 `tools_handlers.py` 的分发映射。
- 新增持久状态时，优先放在独立 manager 中，并把运行时文件写入 `.tasks/`、`.team/`、`.runtime-tasks/`、`.memory/` 等明确目录。
- 新增技能时，在 `skills/<name>/SKILL.md` 中写入 frontmatter，至少包含 `name` 和 `description`。
- 涉及命令执行和文件写入时，应经过路径沙箱和权限系统，不要让外部工具绕过统一管道。
- 涉及并行或高风险任务时，优先使用任务系统和 worktree 隔离，再通过 closeout 决定保留或移除工作区。

## 当前状态

这是一个教学和实验性质的实现，代码中保留了大量学习过程痕迹。部分源码注释在当前环境中存在编码显示异常，但核心模块、配置文件和文档结构可以清晰反映系统设计。进一步产品化时，建议补充：

- 交互式 CLI；
- 依赖文件，例如 `requirements.txt` 或 `pyproject.toml`；
- 自动化测试；
- 更完整的权限审批流；
- 更严格的 MCP 协议兼容性和错误处理；
- 对后台线程、团队循环和 worktree 生命周期的集成测试。
