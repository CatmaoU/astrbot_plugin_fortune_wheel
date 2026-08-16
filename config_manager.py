import os
import json
from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_fortune_wheel"


class ConfigManager:
    """AstrBotConfig 的薄封装。

    依据官方文档（plugin-config.html）：
    AstrBot 检测到 _conf_schema.json 后会自动把配置注入插件 __init__ 的 config 参数，
    因此本类不再自行解析/缓存配置文件，只负责：
      1. 在 config 未注入时从磁盘兜底加载；
      2. 为 /重载配置 提供从磁盘重读并原地更新的能力。
    """

    def __init__(self, config=None, plugin_dir: str = ""):
        self.config = config if isinstance(config, dict) else {}
        self.plugin_dir = plugin_dir or ""
        self.config_path = self._resolve_config_path()
        self.ensure_loaded()

    def _resolve_config_path(self) -> str:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            base = get_astrbot_data_path()
            return os.path.join(base, "config", f"{PLUGIN_NAME}_config.json")
        except Exception:
            pass
        # 兜底：从插件目录向上查找 data/config 目录
        current = self.plugin_dir
        for _ in range(10):
            parent = os.path.dirname(current)
            if parent == current:
                break
            if os.path.isdir(os.path.join(parent, "data")):
                return os.path.join(parent, "data", "config", f"{PLUGIN_NAME}_config.json")
            current = parent
        return ""

    def ensure_loaded(self):
        """若未注入配置且磁盘上存在配置文件，则从磁盘加载。"""
        if self.config:
            return
        self.reload_config()

    def load_config(self) -> dict:
        return self.config

    def reload_config(self) -> dict:
        """从磁盘重新读取配置并原地更新 self.config（失败时保留原配置）。"""
        if not self.config_path or not os.path.exists(self.config_path):
            return self.config
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.config.clear()
                self.config.update(data)
        except Exception as e:
            logger.error(f"重载配置失败: {e}")
        return self.config
