import json
import time

from state.agent_state import CompactState
from utils.config_handler import compact_config
from utils.logger_handler import logger
from pathlib import Path
WORKDIR = Path.cwd()
from openai import OpenAI
from dotenv import load_dotenv
import os
#导入模型的url和token
load_dotenv(override=True)
client = OpenAI(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
MODEL = os.environ["MODEL_ID"]

#计算message的上下文大小
def estimate_context_size(messages: list) -> int:
    return len(str(messages))

# 跟踪最近访问的文件
def track_recent_file(state: CompactState, path: str) -> None:
    if path in state.recent_files:
        state.recent_files.remove(path)
    state.recent_files.append(path)
    # 保持最近访问的文件列表不超过5个
    if len(state.recent_files) > 5:
        state.recent_files[:] = state.recent_files[-5:]

# 将大型工具输出持久化到磁盘
def persist_large_output(tool_use_id: str, output: str) -> str:
    # 如果输出长度不超过阈值，则直接返回
    if len(output) <= compact_config["PERSIST_THRESHOLD"]:
        return output
    compact_tool_path=WORKDIR / compact_config["TOOL_RESULTS_DIR"]
    compact_tool_path.mkdir(parents=True, exist_ok=True)
    #根据工具使用ID生成存储路径
    stored_path = compact_tool_path / f"{tool_use_id}.txt"
    if not stored_path.exists():
        stored_path.write_text(output, encoding="utf-8")
    preview = output[:compact_config["PREVIEW_CHARS"]]
    rel_path = stored_path.relative_to(WORKDIR)
    return (
        "<persisted-output>\n"
        f"Full output saved to: {rel_path}\n"
        "Preview:\n"
        f"{preview}\n"
        "</persisted-output>"
    )

#从历史消息中找出所有工具执行结果,也就是工具结果所在的消息位置、块位置和块本身
def collect_tool_result_blocks(messages: list) -> list[tuple[int, dict]]:
    """Collect OpenAI tool result messages.

    OpenAI format tool mesaage:
    {
        "role": "tool",
        "tool_call_id": "...",
        "content": "..."
    }
    """
    blocks = []
    for message_index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        if not isinstance(message, dict):
            continue
        blocks.append((message_index, message))

    return blocks


#工具压缩函数
def micro_compact(messages: list) -> list:
    #找出所有工具执行结果
    tool_results = collect_tool_result_blocks(messages)
    # 如果工具结果数量不超过阈值，则直接返回
    if len(tool_results) <= compact_config["KEEP_RECENT_TOOL_RESULTS"]:
        return messages
    # 否则，压缩较早的工具结果
    for  _, message in tool_results[:-compact_config["KEEP_RECENT_TOOL_RESULTS"]]:
        content = message.get("content", "")
        if not isinstance(content, str) or len(content) <= 120:
            continue
        message["content"] = "[Earlier tool result compacted. Re-run the tool if you need full detail.]"
    return messages

#把完整对话历史保存到指定目录下
def write_transcript(messages: list) -> Path:
    transcript_dir = WORKDIR / compact_config["TRANSCRIPT_DIR"]
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as handle:
        for message in messages:
            handle.write(json.dumps(message, default=str) + "\n")
    return path

#调用大模型对对话历史进行总结
def summarize_history(messages: list) -> str:
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve:\n"
        "1. The current goal\n"
        "2. Important findings and decisions\n"
        "3. Files read or changed\n"
        "4. Remaining work\n"
        "5. User constraints and preferences\n"
        "Be compact but concrete.\n\n"
        f"{conversation}"
    )

    response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8000,
        )
    return response.choices[0].message.content.strip()

#数负责执行完整的上下文压缩
def compact_history(messages: list, state: CompactState, focus: str | None = None) -> list:
    logger.info("开始进行上下文压缩")
    #1.将完整对话历史保存到磁盘,便于追溯
    transcript_path = write_transcript(messages)
    logger.info(f"[transcript saved: {transcript_path}]")
    #2.调用大模型对对话历史进行总结
    summary = summarize_history(messages)
    #3.判断是否有重点内容需要保留
    if focus:
        summary += f"\n\nFocus to preserve next: {focus}"
    #4.判断是否需要保留最近的文件
    if state.recent_files:
        recent_lines = "\n".join(f"- {path}" for path in state.recent_files)
        summary += f"\n\nRecent files to reopen if needed:\n{recent_lines}"
    #5.更新状态
    state.has_compacted = True
    #6.保存总结结果
    state.last_summary = summary
    return [{
        "role": "user",
        "content": (
            "This conversation was compacted so the agent can continue working.\n\n"
            f"{summary}"
        ),
    }]