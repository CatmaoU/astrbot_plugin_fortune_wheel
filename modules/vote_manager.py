import time
from typing import Dict, Tuple, Optional

class VoteManager:
    def __init__(self, required_agree: int = 2, duration_seconds: int = 120):
        self.required_agree = required_agree
        self.duration_seconds = duration_seconds
        self.votes: Dict[Tuple[int, int], Dict] = {}  # key: (group_id, target_id)

    def create_vote(self, group_id: int, target_id: int, target_name: str,
                    initiator_id: int, initiator_name: str) -> bool:
        """创建投票，若已存在则返回 False"""
        key = (group_id, target_id)
        if key in self.votes:
            return False
        now = time.time()
        self.votes[key] = {
            "target_id": target_id,
            "target_name": target_name,
            "initiator_id": initiator_id,
            "initiator_name": initiator_name,
            "agree_set": set(),
            "disagree_set": set(),
            "expire_time": now + self.duration_seconds
        }
        return True

    def add_vote(self, group_id: int, target_id: int, voter_id: int, choice: str) -> Optional[str]:
        """
        投票，choice 为 'agree' 或 'disagree'
        返回状态信息：
            - "passed" 表示投票立即通过（同意票达到阈值）
            - 其他字符串表示当前票数情况
            - None 表示投票无效（已过期或不存在）
        """
        key = (group_id, target_id)
        vote = self.votes.get(key)
        if not vote:
            return None
        now = time.time()
        if vote["expire_time"] < now:
            del self.votes[key]
            return None
        if voter_id in vote["agree_set"] or voter_id in vote["disagree_set"]:
            return "已投过票"
        if choice == "agree":
            vote["agree_set"].add(voter_id)
        elif choice == "disagree":
            vote["disagree_set"].add(voter_id)
        else:
            return None

        agree = len(vote["agree_set"])
        disagree = len(vote["disagree_set"])

        # 同意票达到阈值立即通过
        if choice == "agree" and agree >= self.required_agree:
            del self.votes[key]
            return "passed"

        return f"同意 {agree} 票，不同意 {disagree} 票"

    def clean_expired(self):
        """清理过期投票"""
        now = time.time()
        for key in list(self.votes.keys()):
            if self.votes[key]["expire_time"] < now:
                del self.votes[key]

    def get_vote_info(self, group_id: int, target_id: int) -> Optional[Dict]:
        key = (group_id, target_id)
        return self.votes.get(key)

    def pop_vote(self, group_id: int, target_id: int) -> Optional[Dict]:
        """直接移除投票并返回数据（用于超时后的最终处理）"""
        key = (group_id, target_id)
        return self.votes.pop(key, None)