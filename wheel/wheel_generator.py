import random
import math
import os
import platform
import colorsys
from PIL import Image, ImageDraw, ImageFont

def generate_weighted_wheel_gif(options: list, weights: list, output_path: str, show_arrow: bool = True, duration_ms: int = 2500, easing: str = 'linear', loop: bool = True) -> str:
    # 过滤权重为0的选项
    filtered = [(o, w) for o, w in zip(options, weights) if w > 0]
    if not filtered:
        raise ValueError("所有奖品权重均为0，无法生成轮盘")
    options, weights = zip(*filtered)
    options = list(options)
    weights = list(weights)
    n = len(options)
    size = 540
    title_height = 45
    center_x = size // 2
    center_y = (size - title_height) // 2 + title_height
    radius = center_y - 40
    total_weight = sum(weights)

    min_w = min(weights)
    raw_angles = [1.0 + (w - min_w) / 10.0 for w in weights]
    total_raw = sum(raw_angles)
    final_angles = [a / total_raw * 360 for a in raw_angles]

    winner_index = random.choices(range(n), weights=weights, k=1)[0]

    physical_angles = []
    current_angle = 0
    for i in range(n):
        sector_angle = final_angles[i]
        start = current_angle
        end = current_angle + sector_angle
        center_angle = start + sector_angle / 2
        physical_angles.append((start, end, center_angle))
        current_angle = end

    target_start_angle, target_end_angle, target_center_angle = physical_angles[winner_index]
    
    final_rotation_needed = (270 - target_center_angle) % 360
    total_rotation = final_rotation_needed + 360 * 5

    def get_font(size):
        system = platform.system()
        font_paths = []
        if system == "Windows":
            font_paths = [("C:/Windows/Fonts/msyh.ttc", 0), ("C:/Windows/Fonts/simhei.ttf", None)]
        elif system == "Darwin":
            font_paths = [("/System/Library/Fonts/PingFang.ttc", 0), ("/System/Library/Fonts/STHeiti Light.ttc", 0)]
        else:
            font_paths = [("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", None)]
        for path, index in font_paths:
            if os.path.exists(path):
                try:
                    if index is not None:
                        return ImageFont.truetype(path, size, index=index)
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()
    
    font = get_font(20)
    font_title = get_font(24)

    base_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw_base = ImageDraw.Draw(base_img)
    sector_colors = []

    for i, opt in enumerate(options):
        start_deg, end_deg, angle_deg = physical_angles[i]
        
        rarity_ratio = weights[i] / max(weights)
        hue = (i / n) * 360
        saturation = 1.0 - rarity_ratio * 0.5
        value = 0.9 - rarity_ratio * 0.2
        
        r, g, b = colorsys.hsv_to_rgb(hue / 360, saturation, value)
        rgb_color = (int(r*255), int(g*255), int(b*255))
        sector_colors.append(rgb_color)
        
        hex_color = f"#{rgb_color[0]:02x}{rgb_color[1]:02x}{rgb_color[2]:02x}"
        
        draw_base.pieslice(
            [(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)],
            start=start_deg, end=end_deg,
            fill=hex_color, outline='black'
        )
        
        sector_angle = final_angles[i]
        if sector_angle >= 12:
            mid_rad = math.radians(angle_deg)
            text_x = center_x + radius * 0.6 * math.cos(mid_rad)
            text_y = center_y + radius * 0.6 * math.sin(mid_rad)

            txt_layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_layer)
            txt_draw.text((text_x, text_y), opt, font=font, fill='white', anchor='mm')
            rotated_text = txt_layer.rotate(-angle_deg, resample=Image.BICUBIC, center=(text_x, text_y))
            base_img.paste(rotated_text, (0, 0), mask=rotated_text)

    draw_base.ellipse([(center_x - 20, center_y - 20), (center_x + 20, center_y + 20)], fill='white', outline='black')

    frames = []
    num_frames = 30
    blink_frames = 6

    frame_duration = max(1, duration_ms / num_frames)
    durations = [frame_duration] * num_frames + [200] * blink_frames + [1500]

    for frame in range(num_frames):
        current_img = base_img.copy()
        draw = ImageDraw.Draw(current_img)
        
        progress = frame / num_frames
        
        if easing == 'ease_out':
            eased_progress = 1 - (1 - progress)**3
        else:
            eased_progress = progress
            
        current_rotation_deg = eased_progress * total_rotation
        
        arrow_angle_deg = (270 + current_rotation_deg) % 360
        arrow_angle_rad = math.radians(arrow_angle_deg)
        
        current_sector_idx = 0
        for i in range(n):
            s, e, _ = physical_angles[i]
            if s <= arrow_angle_deg < e:
                current_sector_idx = i
                break
        if current_sector_idx == 0 and arrow_angle_deg < physical_angles[0][0]:
            current_sector_idx = n - 1
            
        s_deg, e_deg, _ = physical_angles[current_sector_idx]
        s_rad = math.radians(s_deg)
        e_rad = math.radians(e_deg)
        
        bbox = [(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)]
        draw.arc(bbox, start=s_deg, end=e_deg, fill='#FF4040', width=5)
        sx1 = center_x + radius * math.cos(s_rad)
        sy1 = center_y + radius * math.sin(s_rad)
        draw.line([(center_x, center_y), (sx1, sy1)], fill='#FF4040', width=5)
        sx2 = center_x + radius * math.cos(e_rad)
        sy2 = center_y + radius * math.sin(e_rad)
        draw.line([(center_x, center_y), (sx2, sy2)], fill='#FF4040', width=5)
        
        if show_arrow:
            dir_x = math.cos(arrow_angle_rad)
            dir_y = math.sin(arrow_angle_rad)
            perp_x = -math.sin(arrow_angle_rad)
            perp_y = math.cos(arrow_angle_rad)
            
            tip_x = center_x + (radius - 30) * dir_x
            tip_y = center_y + (radius - 30) * dir_y
            base_x = center_x + (radius - 1) * dir_x
            base_y = center_y + (radius - 1) * dir_y
            l_x = base_x + 18 * perp_x
            l_y = base_y + 18 * perp_y
            r_x = base_x - 18 * perp_x
            r_y = base_y - 18 * perp_y
            draw.polygon([(tip_x, tip_y), (l_x, l_y), (r_x, r_y)], fill='red')
            
        draw.ellipse([(center_x - 20, center_y - 20), (center_x + 20, center_y + 20)], fill='white', outline='black')

        header_canvas = Image.new('RGBA', (size, title_height), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(header_canvas)
        
        fill_color = sector_colors[current_sector_idx]
        brightness = (fill_color[0] * 299 + fill_color[1] * 587 + fill_color[2] * 114) / 1000
        stroke_color = '#FFFFFF' if brightness < 128 else '#000000'
        header_text = f"当前指向：{options[current_sector_idx]}"
        h_draw.text((size / 2, title_height / 2), header_text, fill=fill_color, font=font_title, anchor='mm', stroke_width=1, stroke_fill=stroke_color)
        current_img.paste(header_canvas, (0, 0))
        frames.append(current_img)

    final_angle_rad = math.radians(target_center_angle)

    for i in range(blink_frames):
        current_img = base_img.copy()
        draw = ImageDraw.Draw(current_img)

        if show_arrow:
            dir_x = math.cos(final_angle_rad)
            dir_y = math.sin(final_angle_rad)
            perp_x = -math.sin(final_angle_rad)
            perp_y = math.cos(final_angle_rad)
            tip_x = center_x + (radius - 30) * dir_x
            tip_y = center_y + (radius - 30) * dir_y
            base_x = center_x + (radius - 1) * dir_x
            base_y = center_y + (radius - 1) * dir_y
            l_x = base_x + 18 * perp_x
            l_y = base_y + 18 * perp_y
            r_x = base_x - 18 * perp_x
            r_y = base_y - 18 * perp_y

        if i % 2 == 0:
            bbox = [(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)]
            t_s_rad = math.radians(target_start_angle)
            t_e_rad = math.radians(target_end_angle)
            
            draw.arc(bbox, start=target_start_angle, end=target_end_angle, fill='gold', width=5)
            tsx1 = center_x + radius * math.cos(t_s_rad)
            tsy1 = center_y + radius * math.sin(t_s_rad)
            draw.line([(center_x, center_y), (tsx1, tsy1)], fill='gold', width=5)
            tsx2 = center_x + radius * math.cos(t_e_rad)
            tsy2 = center_y + radius * math.sin(t_e_rad)
            draw.line([(center_x, center_y), (tsx2, tsy2)], fill='gold', width=5)
            
            draw.ellipse([(center_x - 20, center_y - 20), (center_x + 20, center_y + 20)], fill='white', outline='black')
            if show_arrow: draw.polygon([(tip_x, tip_y), (l_x, l_y), (r_x, r_y)], fill='gold')
        else:
            draw.ellipse([(center_x - 20, center_y - 20), (center_x + 20, center_y + 20)], fill='white', outline='black')
            if show_arrow: draw.polygon([(tip_x, tip_y), (l_x, l_y), (r_x, r_y)], fill='red')

        header_canvas = Image.new('RGBA', (size, title_height), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(header_canvas)
        fill_color = sector_colors[winner_index]
        brightness = (fill_color[0] * 299 + fill_color[1] * 587 + fill_color[2] * 114) / 1000
        stroke_color = '#FFFFFF' if brightness < 128 else '#000000'
        header_text = f"您抽中了：{options[winner_index]}"
        h_draw.text((size / 2, title_height / 2), header_text, fill=fill_color, font=font_title, anchor='mm', stroke_width=1, stroke_fill=stroke_color)
        current_img.paste(header_canvas, (0, 0))
        frames.append(current_img)

    final_img = base_img.copy()
    draw = ImageDraw.Draw(final_img)
    
    bbox = [(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)]
    t_s_rad = math.radians(target_start_angle)
    t_e_rad = math.radians(target_end_angle)
    draw.arc(bbox, start=target_start_angle, end=target_end_angle, fill='gold', width=5)
    tsx1 = center_x + radius * math.cos(t_s_rad)
    tsy1 = center_y + radius * math.sin(t_s_rad)
    draw.line([(center_x, center_y), (tsx1, tsy1)], fill='gold', width=5)
    tsx2 = center_x + radius * math.cos(t_e_rad)
    tsy2 = center_y + radius * math.sin(t_e_rad)
    draw.line([(center_x, center_y), (tsx2, tsy2)], fill='gold', width=5)
    
    draw.ellipse([(center_x - 20, center_y - 20), (center_x + 20, center_y + 20)], fill='white', outline='black')
    if show_arrow: draw.polygon([(tip_x, tip_y), (l_x, l_y), (r_x, r_y)], fill='gold')

    header_canvas = Image.new('RGBA', (size, title_height), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(header_canvas)
    fill_color = sector_colors[winner_index]
    brightness = (fill_color[0] * 299 + fill_color[1] * 587 + fill_color[2] * 114) / 1000
    stroke_color = '#FFFFFF' if brightness < 128 else '#000000'
    header_text = f"您抽中了：{options[winner_index]}"
    h_draw.text((size / 2, title_height / 2), header_text, fill=fill_color, font=font_title, anchor='mm', stroke_width=1, stroke_fill=stroke_color)
    final_img.paste(header_canvas, (0, 0))

    frames.append(final_img)

    # ★ 根据 loop 参数决定循环次数
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0 if loop else 1,   # True=无限循环，False=播放一次
        disposal=2
    )
    
    return options[winner_index]