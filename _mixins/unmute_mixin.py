import asyncio
import time
from astrbot.api import logger
from ..modules.permission_utils import is_bot_admin

class UnmuteMixin:
    """全部解除功能：管理员一键解禁所有用户"""
    
    async def admin_unmute_all_logic(self, event):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return

        self_id = event.get_self_id()
        if not self_id:
            yield event.plain_result(self.get_message("refresh_cache_no_self", default="无法获取机器人自身信息喵～"))
            return

        bot_is_admin = await is_bot_admin(event.bot, group_id, self_id)
        if not bot_is_admin:
            yield event.plain_result(self.get_message("refresh_cache_bot_no_admin", default="机器人没有本群管理员权限，无法获取禁言列表喵～"))
            return

        await self.cache_mgr.sync_from_protocol(event.bot, group_id)

        raw_cache = self.cache_mgr._load_cache()
        gid = str(group_id)
        all_users = raw_cache.get(gid, [])
        current_time = int(time.time())
        muted_users = [u for u in all_users if u["expire_time"] > current_time]

        if not muted_users:
            yield event.plain_result(self.get_message("petition_no_muted", default="当前群组内没有被禁言的用户喵～"))
            return

        total = len(muted_users)
        yield event.plain_result(self.get_message("admin_unmute_all_start", total=total, default="正在解除 {total} 位用户的禁言喵～"))

        success_list = []
        fail_list = []

        for entry in muted_users:
            user_id = entry["user_id"]
            nickname = entry.get("nickname", f"用户{user_id}")
            try:
                success, err = await self._execute_unmute(event, group_id, user_id)
                if success:
                    success_list.append(nickname)
                else:
                    fail_list.append(f"{nickname}({err})")
                await asyncio.sleep(0.3)
            except Exception as e:
                fail_list.append(f"{nickname}({str(e)})")

        msg = self.get_message("admin_unmute_all_success", success=len(success_list), default="全部解除完成！成功 {success} 人喵～")
        if fail_list:
            msg += self.get_message("admin_unmute_all_fail", fail=len(fail_list), details=', '.join(fail_list), default="，失败 {fail} 人：{details}")
        yield event.plain_result(msg)