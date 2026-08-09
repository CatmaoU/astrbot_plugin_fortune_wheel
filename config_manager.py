import os
import json
import time
from astrbot.api import logger

class ConfigManager:
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        cache_dir = os.path.join(self.plugin_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_json_path = os.path.join(cache_dir, "cache_config.json")
        self.cache_txt_path = os.path.join(cache_dir, "cache_config.txt")

        self._migrate_old_cache()

        plugin_name = os.path.basename(plugin_dir)
        self.plugin_name = plugin_name

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
            old_config_name = "astrbot_plugin_gift_lottery_config.json"
            old_path = os.path.join(self.core_root, "data", "config", old_config_name)
            new_config_name = f"{self.plugin_name}_config.json"
            new_path = os.path.join(self.core_root, "data", "config", new_config_name)

            if os.path.exists(old_path):
                self.config_json_path = old_path
                logger.info(f"使用旧配置文件: {self.config_json_path}")
            else:
                self.config_json_path = new_path
                logger.info(f"使用当前插件配置文件: {self.config_json_path}")
        else:
            logger.error("无法定位 data/config 目录！")

        self._auto_sync_on_init()

    def _migrate_old_cache(self):
        if os.path.exists(self.cache_txt_path) and not os.path.exists(self.cache_json_path):
            try:
                os.rename(self.cache_txt_path, self.cache_json_path)
                logger.info(f"[配置] 已将旧缓存文件 {self.cache_txt_path} 迁移为 {self.cache_json_path}")
            except Exception as e:
                logger.error(f"[配置] 迁移缓存文件失败: {e}")

    def _auto_sync_on_init(self):
        if not os.path.exists(self.config_json_path):
            logger.warning("主配置文件不存在，无法生成缓存。")
            return

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
        if not os.path.exists(self.config_json_path) or not os.path.exists(self.cache_json_path):
            self._auto_sync_on_init()
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
        if not os.path.exists(self.cache_json_path):
            self._auto_sync_on_init()
        if not os.path.exists(self.cache_json_path):
            return {}
        try:
            with open(self.cache_json_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get("config", {})
        except:
            return {}

    # ★ 新增 reload_config
    def reload_config(self):
        """重新加载配置并同步缓存，返回最新配置字典"""
        self.sync_json_to_txt()
        return self.load_config()