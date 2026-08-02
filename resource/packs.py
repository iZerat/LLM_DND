from pathlib import Path

from mods.types import find_resource_dirs

DEFAULT_PACK_ID = "default-dnd"

RESOURCE_MODE_PACK = "pack"
RESOURCE_MODE_FREE = "free"

RESOURCE_MODE_LABELS = {
    RESOURCE_MODE_PACK: "查表创建",
    RESOURCE_MODE_FREE: "填表创建",
}


def packs_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "mods" / "resource" / "resource_packs"


def pack_dir(pack_id: str = DEFAULT_PACK_ID) -> Path:
    """在所有 mod 根的 resource/resource_packs/ 下查找 <pack_id> 目录，主目录优先；
    找不到再回退到主目录下的默认路径。"""
    found = find_resource_dirs("resource", "resource_packs", pack_id)
    if found:
        return found[0]
    return packs_dir() / pack_id


def default_pack_dir() -> Path:
    return pack_dir(DEFAULT_PACK_ID)


_ACTIVE_PACK_ID = DEFAULT_PACK_ID


def active_pack_id() -> str:
    return _ACTIVE_PACK_ID


def active_pack_dir() -> Path:
    return pack_dir(_ACTIVE_PACK_ID)


def set_active_pack(pack_id: str):
    """切换当前资源包（srd 从该包读取）。"""
    global _ACTIVE_PACK_ID
    _ACTIVE_PACK_ID = pack_id or DEFAULT_PACK_ID


def configure_resource_catalogs(resource_mode: str, pack_id: str = DEFAULT_PACK_ID):
    """按资源策略配置全局目录。

    pack（查表创建）: 加载指定资源包（默认 default-dnd），所有对象从库检索。
    free（填表创建）: 不带入任何资源包，对象全部由大模型填表创建。
    """
    from resource.item_db import item_db
    from resource.spell_db import spell_db
    from world.npc_templates import npc_catalog
    if resource_mode == RESOURCE_MODE_FREE:
        set_active_pack(DEFAULT_PACK_ID)
        item_db.set_items_dir(None)
        spell_db.set_spells_dir(None)
        npc_catalog.set_base_dir(None)
    else:
        set_active_pack(pack_id)
        item_db.set_items_dir(pack_dir(_ACTIVE_PACK_ID) / "items")
        spell_db.set_spells_dir(pack_dir(_ACTIVE_PACK_ID) / "spells")
        npc_catalog.set_base_dir(pack_dir(_ACTIVE_PACK_ID) / "npcs")
    # 按当前资源包重载 SRD（原地替换，保持既有引用）
    from rules.srd_data import reload as srd_reload
    from core.character import reload_srd as character_reload
    srd_reload()
    character_reload()
