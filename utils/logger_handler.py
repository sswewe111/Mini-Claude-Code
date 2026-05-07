import datetime
import logging
import os

from utils.path_sandbox import safe_path

#日志保存的根目录
LOG_ROOT = safe_path("logs")

#确保日志的目录存在
os.makedirs(LOG_ROOT, exist_ok=True)

#日志的格式配置
DEFAULT_LOG_FORMAT = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s-%(filename)s:%(lineno)d - %(message)s'
)

LOG_INTERVAL_MINUTES = 5


def get_interval_log_file(name, log_time=None, interval_minutes=LOG_INTERVAL_MINUTES):
    log_time = log_time or datetime.datetime.now()
    interval_minute = (log_time.minute // interval_minutes) * interval_minutes
    interval_time = log_time.replace(minute=interval_minute, second=0, microsecond=0)
    return os.path.join(LOG_ROOT, f"{name}_{interval_time.strftime('%Y-%m-%d_%H-%M')}.log")


class IntervalFileHandler(logging.FileHandler):
    def __init__(self, name, interval_minutes=LOG_INTERVAL_MINUTES, encoding="utf-8"):
        self.name_prefix = name
        self.interval_minutes = interval_minutes
        self.current_interval = self._get_interval(datetime.datetime.now())
        super().__init__(
            get_interval_log_file(self.name_prefix, self.current_interval, self.interval_minutes),
            encoding=encoding,
        )

    def _get_interval(self, log_time):
        interval_minute = (log_time.minute // self.interval_minutes) * self.interval_minutes
        return log_time.replace(minute=interval_minute, second=0, microsecond=0)

    def _switch_file_if_needed(self, record):
        record_time = datetime.datetime.fromtimestamp(record.created)
        record_interval = self._get_interval(record_time)
        if record_interval == self.current_interval:
            return

        self.current_interval = record_interval
        if self.stream:
            self.stream.flush()
            self.stream.close()
            self.stream = None

        self.baseFilename = os.path.abspath(
            get_interval_log_file(self.name_prefix, self.current_interval, self.interval_minutes)
        )
        self.stream = self._open()

    def emit(self, record):
        self.acquire()
        try:
            self._switch_file_if_needed(record)
            super().emit(record)
        finally:
            self.release()

def get_logger(
    name="agent",
    console_level=logging.INFO,#日志的输出级别，默认为INFO
    file_level=logging.DEBUG, #日志文件的输出级别，默认为DEBUG
    log_file=None,
):
    logger=logging.getLogger(name)
    logger.setLevel(logging.DEBUG) #设置日志记录器的最低级别为DEBUG，这样所有级别的日志都会被处理

    #避免重复添加Handler
    if logger.handlers:
        return logger

    #控制台Handler
    console_handler=logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)
    logger.addHandler(console_handler)

    #文件Handler
    if log_file:
        #根据当前日期自动生成日志文件名，格式为：name_YYYY-MM-DD.log
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
    
    else:
        file_handler = IntervalFileHandler(name, interval_minutes=LOG_INTERVAL_MINUTES, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)
    logger.addHandler(file_handler)

    return logger

#快捷获取日志器的函数
logger=get_logger()

if __name__ == '__main__':
    logger.info("信息日志")
    logger.error("错误日志")
    logger.warning("警告日志")
    logger.debug("调试日志")
