import os
import json
import time
from astrbot.api import logger

class ConfigManager:
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        # 缓存目录和文件
        cache_dir = os.path.join(self.plugin_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_json_path = os.path.join(cache_dir, "cache_config.json")
        self.cache_txt_path = os.path.join(cache_dir, "cache_config.txt")  # 旧路径，用于迁移

        # 自动迁移旧文件（如果存在）
        self._migrate_old_cache()

        # 获取插件名称（从目录名提取，或自定义）
        plugin_name = os.path.basename(plugin_dir)
        # 如果目录名不是标准格式，可以尝试从 metadata 读取，但简单起见就用目录名
        # 但为了兼容旧配置，检测是否存在旧命名的配置，若存在则使用旧名
        # 否则使用当前插件名
        self.plugin_name = plugin_name

        # 寻找 Core Root
        current_dir = plugin_dir
        self.core_root = None
        for _ in range(10):
            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            if os.path.isdir(os.path.join(parent, "data")):
                self.core_root = parent
                break
            current_dir = parent

        self.config_json_path = ""
        if self.core_root:
            # 先尝试使用旧名称配置文件（兼容之前版本）
            old_config_name = "astrbot_plugin_gift_lottery_config.json"
            old_path = os.path.join(self.core_root, "data", "config", old_config_name)
            new_config_name = f"{self.plugin_name}_config.json"
            new_path = os.path.join(self.core_root, "data", "config", new_config_name)

            # 如果旧配置存在，则使用旧配置（优先）
            if os.path.exists(old_path):
                self.config_json_path = old_path
                logger.info(f"使用旧配置文件: {self.config_json_path}")
            else:
                self.config_json_path = new_path
                logger.info(f"使用当前插件配置文件: {self.config_json_path}")
        else:
            logger.error("无法定位 data/config 目录！")

        # ★ 关键：加载时自动同步配置到缓存（若主配置存在）
        self._auto_sync_on_init()

    def _migrate_old_cache(self):
        """如果旧的 cache_config.txt 存在，自动重命名为 cache_config.json"""
        if os.path.exists(self.cache_txt_path) and not os.path.exists(self.cache_json_path):
            try:
                os.rename(self.cache_txt_path, self.cache_json_path)
                logger.info(f"[配置] 已将旧缓存文件 {self.cache_txt_path} 迁移为 {self.cache_json_path}")
            except Exception as e:
                logger.error(f"[配置] 迁移缓存文件失败: {e}")

    def _auto_sync_on_init(self):
        """在初始化时自动同步配置到缓存（若主配置文件存在且缓存不存在或过期）"""
        if not os.path.exists(self.config_json_path):
            logger.warning("主配置文件不存在，无法生成缓存。")
            return

        # 如果缓存文件不存在，或修改时间早于主配置，则同步
        need_sync = True
        if os.path.exists(self.cache_json_path):
            try:
                with open(self.cache_json_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                cached_mtime = cache.get("modify_time", 0.0)
                real_mtime = os.path.getmtime(self.config_json_path)
                if real_mtime <= cached_mtime:
                    need_sync = False
            except:
                need_sync = True

        if need_sync:
            self.sync_json_to_txt()
            logger.info("[配置] 自动生成/更新配置缓存完成。")

    def sync_json_to_txt(self):
        """同步 JSON 配置到缓存 JSON（原方法名保留，但实际写入 JSON 文件）"""
        if not os.path.exists(self.config_json_path):
            logger.warning("data/config 中的配置文件不存在！")
            return

        cache_data = {"modify_time": 0.0, "config": {}, "raw_json_text": ""}
        try:
            cache_data["modify_time"] = os.path.getmtime(self.config_json_path)
            with open(self.config_json_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if raw.startswith('\ufeff'):
                raw = raw.lstrip('\ufeff')
            cache_data["raw_json_text"] = raw
            cache_data["config"] = json.loads(raw)
            logger.info("成功读取并解析原始 JSON 配置")
        except Exception as e:
            logger.error(f"读取 JSON 失败: {e}")
            cache_data["config"] = {}

        try:
            with open(self.cache_json_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"写入缓存 JSON 失败: {e}")

    def check_and_sync(self):
        """检查 JSON 是否有更新，有则重新同步（外部调用）"""
        if not os.path.exists(self.config_json_path) or not os.path.exists(self.cache_json_path):
            self._auto_sync_on_init()  # 直接触发自动同步
            return True

        try:
            with open(self.cache_json_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            txt_mtime = cache.get("modify_time", 0.0)
            real_mtime = os.path.getmtime(self.config_json_path)
            if real_mtime > txt_mtime:
                self.sync_json_to_txt()
                return True
        except:
            self.sync_json_to_txt()
            return True
        return False

    def load_config(self):
        """从缓存 JSON 读取配置"""
        if not os.path.exists(self.cache_json_path):
            # 尝试生成缓存
            self._auto_sync_on_init()
        if not os.path.exists(self.cache_json_path):
            return {}
        try:
            with open(self.cache_json_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get("config", {})
        except:
            return {}