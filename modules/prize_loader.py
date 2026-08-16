import time
from ..utils.prize_utils import parse_range

_cached_prizes = None
_cached_time = 0
_cache_ttl = 30  # 缓存有效期（秒）


def load_prizes(config: dict):
    """从配置字典加载奖池，支持短时缓存。

    配置已由 AstrBot 注入（AstrBotConfig），无需再读文件。
    """
    global _cached_prizes, _cached_time
    now = time.time()
    if _cached_prizes is not None and (now - _cached_time) < _cache_ttl:
        return _cached_prizes

    raw_items = config.get("wheel_items", []) or []
    enable_participation = config.get("enable_participation_prize", True)

    prizes, weights, prize_durations = [], [], {}
    for item in raw_items:
        name = ""
        weight = 0.0
        if isinstance(item, dict):
            name = item.get('prize', '').strip()
            try:
                weight = float(item.get('weight', 0))
            except (TypeError, ValueError):
                continue
        elif isinstance(item, str) and ":" in item:
            parts = item.split(":", 1)
            name = parts[0].strip()
            try:
                weight = float(parts[1].strip())
            except (TypeError, ValueError):
                continue
        else:
            continue
        if not name:
            continue
        min_m, max_m, unit = parse_range(name)
        if unit is not None:
            if not enable_participation and min_m == 0 and max_m == 0:
                continue
            prizes.append(name)
            weights.append(weight)
            prize_durations[name] = (min_m, max_m)

    _cached_prizes = (prizes, weights, prize_durations)
    _cached_time = now
    return prizes, weights, prize_durations
