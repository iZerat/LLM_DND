"""开场模板（旧入口，转发到 mods 统一资源 API）。"""
from mods.api import list_opening_templates, load_opening_template

__all__ = ["list_opening_templates", "load_opening_template"]
