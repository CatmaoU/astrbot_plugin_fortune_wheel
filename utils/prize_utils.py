import re

def parse_range(name: str):
    """解析配置名称，返回 (最小分钟, 最大分钟, 单位)"""
    name = name.strip()
    name_lower = name.lower()
    
    # 识别“重在参与”和0分钟
    if name in ("0", "0分钟", "重在参与", "0-0", "0-0分钟") or name_lower in ("重在参与", "0", "0分钟", "0-0", "0-0分钟"):
        return 0, 0, 1
    
    unit_multiplier = 1
    if "天" in name_lower:
        unit_multiplier = 1440
    elif "小时" in name_lower or "时" in name_lower:
        unit_multiplier = 60
    elif "分钟" in name_lower or "分" in name_lower:
        unit_multiplier = 1
    else:
        if re.fullmatch(r'\d+', name):
            val = int(name)
            return val, val, 1
        if re.fullmatch(r'\d+-\d+', name):
            parts = name.split("-")
            return int(parts[0]), int(parts[1]), 1
        return 0, 0, None

    match = re.search(r'(\d+)-(\d+)', name)
    if match:
        min_val = int(match.group(1))
        max_val = int(match.group(2))
        return min_val * unit_multiplier, max_val * unit_multiplier, unit_multiplier

    match = re.search(r'(\d+)', name)
    if match:
        val = int(match.group(1))
        return val * unit_multiplier, val * unit_multiplier, unit_multiplier
    return 0, 0, None

def normalize_weights(prizes: list, weights: list) -> list:
    return weights

def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    elif minutes < 1440:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours} 小时 {mins} 分钟" if mins else f"{hours} 小时"
    else:
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        mins = minutes % 60
        parts = [f"{days} 天"]
        if hours: parts.append(f"{hours} 小时")
        if mins: parts.append(f"{mins} 分钟")
        return " ".join(parts)