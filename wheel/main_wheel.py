from .wheel_generator import generate_weighted_wheel_gif

def generate_main_wheel(prizes: list, weights: list, output_path: str, show_arrow: bool, duration_ms: int, loop: bool = True) -> str:
    """生成一级主轮盘并返回结果，自带缓出减速"""
    return generate_weighted_wheel_gif(
        options=prizes,
        weights=weights,
        output_path=output_path,
        show_arrow=show_arrow,
        duration_ms=duration_ms,
        easing='ease_out',
        loop=loop
    )