import asyncio
import time
from astrbot.api import logger
from astrbot.api.message_components import At
from ..modules.permission_utils import is_user_admin, is_bot_admin

class VoteMixin:
    """投票解禁功能"""
    
    async def admin_pardon_logic(self, event):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return
        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()

        sender_is_admin = await is_user_admin(event.bot, group_id, sender_id, self.global_admins)

        target_id = None
        for comp in event.message_obj.message:
            if isinstance(comp, At):
                target_id = comp.qq
                break

        if target_id:
            if sender_is_admin:
                target_name = str(target_id)
                try:
                    info = await event.bot.call_action(
                        "get_group_member_info",
                        group_id=group_id,
                        user_id=target_id,
                        no_cache=True
                    )
                    target_name = info.get('nickname') or info.get('card') or str(target_id)
                except Exception:
                    pass
                success, err = await self._execute_unmute(event, group_id, target_id)
                if success:
                    yield event.plain_result(self.get_message("admin_unmute_success", target=target_name, default="已成功解除 @{target} 的禁言喵～"))
                else:
                    yield event.plain_result(self.get_message("admin_unmute_fail", error=err, default="解除禁言失败喵：{error}"))
                return
            else:
                yield event.plain_result(self.get_message("pardon_admin_only", default="只有管理员才能使用 @ 用户直接解禁，请使用 `/放过 [序号]` 发起投票喵～"))
                return

        args = event.message_str.strip().split()
        params = args[1:] if len(args) > 1 else []
        self_id = event.get_self_id()
        if not self_id:
            yield event.plain_result(self.get_message("refresh_cache_no_self", default="无法获取机器人自身信息喵～"))
            return
        bot_is_admin = await is_bot_admin(event.bot, group_id, self_id)

        if len(params) == 0:
            if not bot_is_admin:
                yield event.plain_result(self.get_message("pardon_bot_no_admin", default="机器人没有本群管理员权限，无法获取禁言列表喵～\n您可以联系管理员手动解禁，或使用 `@用户` 方式（仅管理员）"))
                return
            muted_users = await self.cache_mgr.get_muted(group_id)
            if not muted_users:
                await self.cache_mgr.sync_from_protocol(event.bot, group_id)
                muted_users = await self.cache_mgr.get_muted(group_id)
            if not muted_users:
                yield event.plain_result(self.get_message("petition_no_muted", default="当前群组内没有被禁言的用户喵～"))
                return
            lines = [self.get_message("pardon_list_title", default="放过列表：")]
            for idx, u in enumerate(muted_users, 1):
                start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["start_time"]))
                end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["expire_time"]))
                lines.append(f"{idx}. {u['nickname']} ({u['user_id']}) 开始: {start_str} 结束: {end_str}")
            lines.append("\n" + self.get_message("pardon_list_tip", default="发送 `/放过 [序号]` 发起投票解禁喵～"))
            yield event.plain_result("\n".join(lines))
            return

        target_input = params[0]
        if not target_input.isdigit():
            yield event.plain_result(self.get_message("pardon_invalid_param", default="参数无效，请提供序号喵～"))
            return
        choice = int(target_input)
        muted_users = await self.cache_mgr.get_muted(group_id)
        if not muted_users:
            if bot_is_admin:
                await self.cache_mgr.sync_from_protocol(event.bot, group_id)
                muted_users = await self.cache_mgr.get_muted(group_id)
            else:
                yield event.plain_result(self.get_message("pardon_bot_no_admin", default="机器人无权限获取群成员列表，请管理员手动解禁喵～"))
                return
        if choice < 1 or choice > len(muted_users):
            yield event.plain_result(self.get_message("pardon_out_of_range", max=len(muted_users), default="序号超出范围，请输入 1-{max} 喵～"))
            return
        target_user = muted_users[choice - 1]
        target_id = target_user["user_id"]
        target_name = target_user["nickname"]

        if sender_is_admin:
            success, err = await self._execute_unmute(event, group_id, target_id)
            if success:
                yield event.plain_result(self.get_message("admin_unmute_success", target=target_name, default="已成功解除 @{target} 的禁言喵～"))
            else:
                yield event.plain_result(self.get_message("admin_unmute_fail", error=err, default="解除禁言失败喵：{error}"))
            return

        self.vote_mgr.clean_expired()
        if not self.vote_mgr.create_vote(group_id, target_id, target_name, sender_id, sender_name):
            yield event.plain_result(self.get_message("vote_already_exist", default="该用户已有进行中的投票，请耐心等待喵～"))
            return

        initiator_mention = f"@{sender_name}" if sender_name else f"@{sender_id}"
        target_mention = f"@{target_name}" if target_name else f"@{target_id}"
        duration_sec = self.vote_mgr.duration_seconds
        yield event.plain_result(self.get_message("vote_initiator",
            initiator=initiator_mention,
            target=target_mention,
            duration=duration_sec,
            default="用户 {initiator} 发起了解禁 {target} 的投票！\n请群友回复 `/同意` 或 `/不同意` 进行表决\n（{duration}秒后自动截止）"
        ))
        asyncio.create_task(self._vote_checker(group_id, target_id, event))

    async def _vote_checker(self, group_id, target_id, event):
        await asyncio.sleep(self.vote_mgr.duration_seconds)
        vote_data = self.vote_mgr.pop_vote(group_id, target_id)
        if vote_data is None:
            return
        muted_list = await self.cache_mgr.get_muted(group_id)
        if target_id not in [u["user_id"] for u in muted_list]:
            msg = self.get_message("vote_already_unmuted", target=target_id, default="投票结束，但用户 {target} 已被解禁，无需重复操作喵～")
            try:
                await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
            except Exception as e:
                logger.error(f"发送投票结果失败: {e}")
            return
        agree = len(vote_data["agree_set"])
        disagree = len(vote_data["disagree_set"])
        target_name = vote_data["target_name"]
        required = self.vote_mgr.required_agree

        if agree >= required and agree > disagree:
            success, err = await self._execute_unmute(event, group_id, target_id)
            if success:
                msg = self.get_message("vote_passed_end",
                    agree=agree, disagree=disagree,
                    target=target_name, id=target_id,
                    default="投票结束（同意 {agree} 票，不同意 {disagree} 票），达到最低票数且同意多于反对，已解除 @{target} ({id}) 的禁言喵～"
                )
            else:
                msg = self.get_message("admin_unmute_fail", error=err, default="解禁执行失败喵：{error}，请管理员手动处理喵～")
        else:
            reasons = []
            if agree < required:
                reasons.append(f"同意票未达到最低要求（{agree}/{required}）")
            if agree <= disagree:
                reasons.append("同意票未超过反对票")
            reasons_str = '，'.join(reasons)
            msg = self.get_message("vote_failed_end",
                agree=agree, disagree=disagree,
                reasons=reasons_str,
                target=target_name,
                default="投票结束（同意 {agree} 票，不同意 {disagree} 票），{reasons}，未解禁 {target} 喵～"
            )
        try:
            await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
        except Exception as e:
            logger.error(f"发送投票结果失败: {e}")

    async def vote_agree_logic(self, event):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return
        sender_id = event.get_sender_id()
        self.vote_mgr.clean_expired()
        for key, vote in self.vote_mgr.votes.items():
            if key[0] == group_id:
                target_id = key[1]
                result = self.vote_mgr.add_vote(group_id, target_id, sender_id, "agree")
                if result is None:
                    yield event.plain_result(self.get_message("vote_expired", default="投票已过期或不存在喵～"))
                elif result == "已投过票":
                    yield event.plain_result(self.get_message("vote_already_voted", default="您已对此投票表达过意见喵～"))
                elif result == "passed":
                    target_name = vote["target_name"]
                    agree_count = len(vote["agree_set"])
                    disagree_count = len(vote["disagree_set"])
                    success, err = await self._execute_unmute(event, group_id, target_id)
                    if success:
                        yield event.plain_result(self.get_message("vote_passed_immediate",
                            agree=agree_count, disagree=disagree_count,
                            target=target_name, id=target_id,
                            default="投票通过（同意数 {agree} ＞ {disagree} 票）！已解除 @{target} ({id}) 的禁言喵～"
                        ))
                    else:
                        yield event.plain_result(self.get_message("admin_unmute_fail", error=err, default="解禁执行失败喵：{error}，请管理员手动处理喵～"))
                    return
                else:
                    yield event.plain_result(self.get_message("vote_agree_success",
                        target=vote["target_name"],
                        result=result,
                        default="您已同意解禁 @{target} ({result})"
                    ))
                return
        yield event.plain_result(self.get_message("vote_no_vote", default="当前没有进行中的投票喵～"))

    async def vote_disagree_logic(self, event):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return
        sender_id = event.get_sender_id()
        self.vote_mgr.clean_expired()
        for key, vote in self.vote_mgr.votes.items():
            if key[0] == group_id:
                target_id = key[1]
                result = self.vote_mgr.add_vote(group_id, target_id, sender_id, "disagree")
                if result is None:
                    yield event.plain_result(self.get_message("vote_expired", default="投票已过期或不存在喵～"))
                elif result == "已投过票":
                    yield event.plain_result(self.get_message("vote_already_voted", default="您已对此投票表达过意见喵～"))
                else:
                    yield event.plain_result(self.get_message("vote_disagree_success",
                        target=vote["target_name"],
                        result=result,
                        default="您已拒绝解禁 @{target} ({result})"
                    ))
                return
        yield event.plain_result(self.get_message("vote_no_vote", default="当前没有进行中的投票喵～"))