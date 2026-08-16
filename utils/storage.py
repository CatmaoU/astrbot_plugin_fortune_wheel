import os
import json
import tempfile
from typing import Any, Dict


def get_plugin_data_dir(plugin_name: str = "astrbot_plugin_fortune_wheel", fallback_dir: str = "") -> str:
    """返回插件持久化数据目录（data/plugin_data/<plugin_name>/）。

    文档规范：持久化数据应存储于 data 目录而非插件自身目录，
    防止更新/重装插件时数据被覆盖（参见 storage.html）。
    """
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        base = get_astrbot_data_path()
        return os.path.join(base, "plugin_data", plugin_name)
    except Exception:
        # 回退：无法获取 AstrBot 数据目录时退回到插件 cache 目录
        return fallback_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache")


def atomic_write_json(path: str, data: Any) -> None:
    """原子写 JSON：先写临时文件再 os.replace，避免写一半崩溃导致文件损坏。"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def safe_read_json(path: str, default: Any = None) -> Any:
    """安全读 JSON；文件缺失或损坏时返回 default（不会抛异常导致插件崩溃）。"""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception:
        return default
