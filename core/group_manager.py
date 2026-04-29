"""
GroupManager — gestion interne des groupes cross-plateforme.
Stockage en mémoire (extensible vers une DB).
"""

import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger("GAB.groups")


class GroupManager:
    """Registre des groupes créés via GAB."""

    def __init__(self):
        self._groups: dict[str, dict] = {}

    def create(self, name: str, creator: str, platform: str) -> dict:
        gid = str(uuid.uuid4())[:8]
        group = {
            "id":        gid,
            "name":      name,
            "platform":  platform,
            "creator":   creator,
            "members":   [creator],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._groups[gid] = group
        logger.info("Groupe '%s' (%s) créé par %s sur %s", name, gid, creator, platform)
        return group

    def add_member(self, group_id: str, user_id: str) -> bool:
        group = self._groups.get(group_id)
        if not group:
            return False
        if user_id not in group["members"]:
            group["members"].append(user_id)
        return True

    def remove_member(self, group_id: str, user_id: str) -> bool:
        group = self._groups.get(group_id)
        if not group:
            return False
        group["members"] = [m for m in group["members"] if m != user_id]
        return True

    def get(self, group_id: str) -> dict | None:
        return self._groups.get(group_id)

    def list_by_user(self, user_id: str, platform: str) -> list[dict]:
        return [
            g for g in self._groups.values()
            if user_id in g["members"] and g["platform"] == platform
        ]

    def all(self) -> list[dict]:
        return list(self._groups.values())
