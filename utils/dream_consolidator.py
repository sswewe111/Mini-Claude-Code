from pathlib import Path
import re
WORKDIR = Path.cwd()
from utils.config_handler import memory_config
from utils.logger_handler import logger
class DreamConsolidator:

    COOLDOWN_SECONDS = memory_config["COOLDOWN_SECONDS"]
    SCAN_THROTTLE_SECONDS = memory_config["SCAN_THROTTLE_SECONDS"]
    MIN_SESSION_COUNT = memory_config["MIN_SESSION_COUNT"]
    LOCK_STALE_SECONDS = memory_config["LOCK_STALE_SECONDS"]

    """当前只是阶段描述，没有真正执行合并或删除"""
    PHASES = [
        "Orient: scan MEMORY.md index for structure and categories",
        "Gather: read individual memory files for full content",
        "Consolidate: merge related memories, remove stale entries",
        "Prune: enforce 200-line limit on MEMORY.md index",
    ]

    def __init__(self, memory_dir: Path = None):
        self.memory_dir = memory_dir or WORKDIR / memory_config["MEMORY_DIR"]
        self.lock_file = self.memory_dir / ".dream_lock"
        self.enabled = True
        self.mode = "default"
        self.last_consolidation_time = 0.0
        self.last_scan_time = 0.0
        self.session_count = 0
    
    """
    核心 gate 检查函数,
    按顺序检查 7 个条件，只要一个失败，就返回 False 和失败原因字符串。
    如果全部通过，返回 True 和成功字符串。
    """
    def should_consolidate(self) -> tuple[bool, str]:
        import time
        now = time.time()
        # Gate 1: Gate 1：是否启用：
        if not self.enabled:
            return False, "Gate 1: consolidation is disabled"
        # Gate 2: 记忆目录是否存在，并且有具体记忆文件：
        if not self.memory_dir.exists():
            return False, "Gate 2: memory directory does not exist"
        memory_files = list(self.memory_dir.glob("*.md"))
        # Exclude MEMORY.md itself from the count
        memory_files = [f for f in memory_files if f.name != "MEMORY.md"]
        if not memory_files:
            return False, "Gate 2: no memory files found"
        # Gate 3: 不能在 plan mode 下整理
        if self.mode == "plan":
            return False, "Gate 3: plan mode does not allow consolidation"
        # Gate 4: 距离上次整理必须超过 24 小时
        time_since_last = now - self.last_consolidation_time
        if time_since_last < self.COOLDOWN_SECONDS:
            remaining = int(self.COOLDOWN_SECONDS - time_since_last)
            return False, f"Gate 4: cooldown active, {remaining}s remaining"
        # Gate 5: 距离上次扫描尝试必须超过 10 分钟：
        time_since_scan = now - self.last_scan_time
        if time_since_scan < self.SCAN_THROTTLE_SECONDS:
            remaining = int(self.SCAN_THROTTLE_SECONDS - time_since_scan)
            return False, f"Gate 5: scan throttle active, {remaining}s remaining"
        # Gate 6: 至少 5 个 session
        if self.session_count < self.MIN_SESSION_COUNT:
            return False, f"Gate 6: only {self.session_count} sessions, need {self.MIN_SESSION_COUNT}"
        # Gate 7: 获取锁
        if not self._acquire_lock():
            return False, "Gate 7: lock held by another process"
        return True, "All 7 gates passed"
    
    """
    执行整理的入口
    """
    def consolidate(self) -> list[str]:
        """
        Run the 4-phase consolidation process.
        The teaching version returns phase descriptions to make the flow
        visible without requiring an extra LLM pass here.
        """
        import time
        can_run, reason = self.should_consolidate()
        #如果不能运行，就打印原因并返回空列表
        if not can_run:
            print(f"[Dream] Cannot consolidate: {reason}")
            return []
        print("[Dream] Starting consolidation...")
        self.last_scan_time = time.time()
        completed_phases = []
        #遍历 4 个阶段
        for i, phase in enumerate(self.PHASES, 1):
            print(f"[Dream] Phase {i}/4: {phase}")
            completed_phases.append(phase)
        self.last_consolidation_time = time.time()
        self._release_lock()
        logger.info(f"[Dream] Consolidation complete: {len(completed_phases)} phases executed")
        return completed_phases
    
    """用于获取 PID 锁"""
    def _acquire_lock(self) -> bool:
        """
        Acquire a PID-based lock file. Returns False if locked by another
        live process. Stale locks (older than LOCK_STALE_SECONDS) are removed.
        """
        import time
        if self.lock_file.exists():
            try:
                lock_data = self.lock_file.read_text().strip()
                pid_str, timestamp_str = lock_data.split(":", 1)
                pid = int(pid_str)
                lock_time = float(timestamp_str)
                # Check if lock is stale
                if (time.time() - lock_time) > self.LOCK_STALE_SECONDS:
                    print(f"[Dream] Removing stale lock from PID {pid}")
                    self.lock_file.unlink()
                else:
                    # Check if owning process is still alive
                    try:
                        os.kill(pid, 0)
                        return False  # process alive, lock is valid
                    except OSError:
                        print(f"[Dream] Removing lock from dead PID {pid}")
                        self.lock_file.unlink()
            except (ValueError, OSError):
                # Corrupted lock file, remove it
                self.lock_file.unlink(missing_ok=True)
        # Write new lock
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(f"{os.getpid()}:{time.time()}")
            return True
        except OSError:
            return False
        
    """用于释放锁"""
    def _release_lock(self):
        """Release the lock file if we own it."""
        try:
            if self.lock_file.exists():
                lock_data = self.lock_file.read_text().strip()
                pid_str = lock_data.split(":")[0]
                if int(pid_str) == os.getpid():
                    self.lock_file.unlink()
        except (ValueError, OSError):
            pass