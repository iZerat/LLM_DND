from pathlib import Path

DEFAULT_PACK_ID = "default-dnd"

RESOURCE_MODE_PACK = "pack"
RESOURCE_MODE_FREE = "free"

RESOURCE_MODE_LABELS = {
    RESOURCE_MODE_PACK: "查表创建",
    RESOURCE_MODE_FREE: "填表创建",
}


def packs_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "packs"


def pack_dir(pack_id: str = DEFAULT_PACK_ID) -> Path:
    return packs_dir() / pack_id


def default_pack_dir() -> Path:
    return pack_dir(DEFAULT_PACK_ID)


def configure_resource_catalogs(resource_mode: str):
    """按资源策略配置全局目录。

    pack（查表创建）: 加载默认资源包，所有对象从库检索。
    free（填表创建）: 不带入任何资源包，对象全部由大模型填表创建。
    """
    from resource.item_db import item_db
    from world.npc_templates import npc_catalog
    if resource_mode == RESOURCE_MODE_FREE:
        item_db.set_items_dir(None)
        npc_catalog.set_base_dir(None)
    else:
        item_db.set_items_dir(default_pack_dir() / "items")
        npc_catalog.set_base_dir(default_pack_dir() / "npcs")
