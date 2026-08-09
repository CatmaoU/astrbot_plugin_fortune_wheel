from typing import Optional, List
from functools import wraps
from astrbot.api import logger

async def is_user_admin(bot, group_id: int, user_id: int, global_admins: Optional[List] = None) -> bool:
    if global_admins and str(user_id) in [str(admin) for admin in global_admins]:
        return True
    try:
        info = await bot.call_action(
            "get_group_member_info",
            group_id=group_id,
            user_id=user_id,
            no_cache=True
        )
        role = info.get("role", "member")
        return role in ("owner", "admin")
    except Exception:
        return False

async def is_bot_admin(bot, group_id: int, self_id: Optional[str] = None) -> bool:
    if self_id is None:
        try:
            login_info = await bot.call_action("get_login_info")
            self_id = str(login_info.get("user_id"))
        except Exception:
            return False
    if not self_id:
        return False
    try:
        info = await bot.call_action(
            "get_group_member_info",
            group_id=group_id,
            user_id=int(self_id),
            no_cache=True
        )
        role = info.get("role", "member")
        return role in ("owner", "admin")
    except Exception:
        return False

# ★ 群组黑白名单检查
def check_group_permission(group_id: int, mode: str, group_list: List[int]) -> bool:
    # 兼容中英文
    if mode in ("whitelist", "白名单"):
        return group_id in group_list
    elif mode in ("blacklist", "黑名单"):
        return group_id not in group_list
    else:
        return True  # 未知模式默认允许

def require_permission(global_admins_getter):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, event, *args, **kwargs):
            group_id = event.message_obj.group_id
            user_id = event.get_sender_id()
            if not group_id:
                # 私聊只检查全局管理员
                global_admins = global_admins_getter(self) if callable(global_admins_getter) else []
                if str(user_id) not in [str(admin) for admin in global_admins]:
                    yield event.plain_result("❌ 此指令仅限管理员使用喵～")
                    return
            else:
                # 检查群组黑白名单
                raw_cfg = self.config_manager.load_config()
                mode = raw_cfg.get("group_mode", "blacklist")
                group_list = raw_cfg.get("group_list", [])
                if not check_group_permission(group_id, mode, group_list):
                    yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
                    return

                global_admins = global_admins_getter(self) if callable(global_admins_getter) else []
                if not await is_user_admin(event.bot, group_id, user_id, global_admins):
                    yield event.plain_result("❌ 此指令仅限管理员使用喵～")
                    return
            async for msg in func(self, event, *args, **kwargs):
                yield msg
        return wrapper
    return decorator