import os
import json
from astrbot.api import logger

class HelpMixin:
    def _load_help(self) -> str:
        """直接从 helps.json 加载帮助信息"""
        help_path = os.path.join(self.plugin_dir, "helps.json")
        
        if not os.path.exists(help_path):
            logger.warning("helps.json 不存在，请检查插件安装")
            return "帮助文件缺失，请重新安装插件喵～"
        
        try:
            with open(help_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self._format_help(data)
        except json.JSONDecodeError as e:
            logger.error(f"帮助文件格式错误: {e}")
            return "帮助文件格式错误，请检查 helps.json 喵～"
        except Exception as e:
            logger.error(f"加载帮助文件失败: {e}")
            return "帮助信息加载失败喵～"

    def _format_help(self, data: dict) -> str:
        lines = [data.get("title", "大礼包使用帮助")]
        lines.append("")
        for section in data.get("sections", []):
            lines.append(section.get("title", ""))
            for item in section.get("items", []):
                lines.append(f"  {item.get('cmd', '')}：{item.get('desc', '')}")
            lines.append("")
        footer = data.get("footer", "")
        if footer:
            lines.append(footer)
        return "\n".join(lines)