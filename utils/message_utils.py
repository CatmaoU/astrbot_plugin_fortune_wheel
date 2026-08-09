import random

class MessageManager:
    def __init__(self, config):
        self.templates = config.get("message_templates", {})
    
    def get_message(self, key: str, **kwargs) -> str:
        """
        获取指定 key 的消息模板。
        如果模板是列表，则随机选择一条；
        如果模板是字符串，则直接使用；
        否则返回空字符串。
        用 kwargs 替换占位符。
        """
        template = self.templates.get(key)
        if template is None:
            return ""
        
        # 处理列表（多条随机）
        if isinstance(template, list):
            if not template:
                return ""
            template = random.choice(template)
        elif not isinstance(template, str):
            return ""
        
        # 替换占位符
        try:
            return template.format(**kwargs)
        except KeyError as e:
            from astrbot.api import logger
            logger.warning(f"消息模板缺少占位符: {e}, key={key}")
            return template