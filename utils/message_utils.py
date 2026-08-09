import random
from astrbot.api import logger

class MessageManager:
    def __init__(self, config):
        templates_config = config.get("message_templates", [])
        if isinstance(templates_config, list):
            self.templates = {}
            for item in templates_config:
                if isinstance(item, str) and ":" in item:
                    key, value = item.split(":", 1)
                    self.templates[key.strip()] = value.strip()
                else:
                    logger.warning(f"消息模板条目格式无效，已忽略: {item}")
        else:
            self.templates = templates_config if isinstance(templates_config, dict) else {}

    def get_message(self, key: str, default: str = "", **kwargs) -> str:
        template = self.templates.get(key)
        if template is None:
            return default
        if isinstance(template, list):
            if not template:
                return default
            template = random.choice(template)
        elif not isinstance(template, str):
            return default
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"消息模板缺少占位符: {e}, key={key}")
            return template