from world.object import Object
from world.scene import Scene
from world.world import World
from world.ability import Skill, Feat, Spell, skills_from_srd
from world.state import WorldState

__all__ = [
    "Entity", "NPC", "WorldState", "spawn", "get_template", "list_templates",
    "Object", "Scene", "World", "Skill", "Feat", "Spell", "skills_from_srd",
]

_LAZY_MODULES = {
    "Entity": ("world.entity", "Entity"),
    "NPC": ("world.entity", "NPC"),
    "spawn": ("world.npc_templates", "spawn"),
    "get_template": ("world.npc_templates", "get_template"),
    "list_templates": ("world.npc_templates", "list_templates"),
}


def __getattr__(name):
    entry = _LAZY_MODULES.get(name)
    if entry:
        import importlib
        module_name, attr = entry
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'world' has no attribute {name!r}")
