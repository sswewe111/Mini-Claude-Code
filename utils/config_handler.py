import yaml
from utils.path_sandbox import safe_path

"""
加载Todo_Manager的配置文件，返回一个字典对象。
"""
def load_todo_manager_config(config_file=safe_path("configs/todo_manager.yml"),encoding="utf-8"):   
    with open(safe_path(config_file), 'r',encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

"""
加载上下文压缩的的配置文件，返回一个字典对象。
"""
def load_compact_config(config_file=safe_path("configs/compact_config.yml"),encoding="utf-8"):   
    with open(safe_path(config_file), 'r',encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

"""
加载权限检查的配置文件，返回一个字典对象。
"""
def load_permission_config(config_file=safe_path("configs/permission_config.yml"),encoding="utf-8"):   
    with open(safe_path(config_file), 'r',encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

"""
加载记忆保持的配置文件，返回一个字典对象。
"""
def load_memory_config(config_file=safe_path("configs/memory_config.yml"),encoding="utf-8"):   
    with open(safe_path(config_file), 'r',encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

"""
加载错误恢复的配置文件，返回一个字典对象。
"""
def load_recovery_config(config_file=safe_path("configs/recovery_config.yml"),encoding="utf-8"):   
    with open(safe_path(config_file), 'r',encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

todo_manager_config = load_todo_manager_config()
compact_config = load_compact_config()
permission_config = load_permission_config()
memory_config = load_memory_config()
recovery_config = load_recovery_config()