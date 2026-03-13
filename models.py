from dataclasses import dataclass, field
from typing import List


@dataclass
class GameItem:
    title: str
    path: str
    icon_path: str = ""
    favorited: bool = False
    use_icon: bool = False

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "path": self.path,
            "icon_path": self.icon_path,
            "favorited": self.favorited,
            "use_icon": self.use_icon,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameItem":
        return cls(
            title=data["title"],
            path=data["path"],
            icon_path=data.get("icon_path", ""),
            favorited=data.get("favorited", False),
            use_icon=data.get("use_icon", False),
        )


@dataclass
class GameTab:
    name: str
    games: List[GameItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "games": [g.to_dict() for g in self.games]}

    @classmethod
    def from_dict(cls, data: dict) -> "GameTab":
        games = [GameItem.from_dict(g) for g in data.get("games", [])]
        return cls(name=data["name"], games=games)
