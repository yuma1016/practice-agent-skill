from __future__ import annotations

from enum import Enum


class ChatMode(str, Enum):
    RESEARCH = "research"
    NAVIGATION = "navigation"


class ConversationRouter:
    """Small deterministic router; explicit slash commands always win."""

    _navigation_markers = (
        "案内",
        "行き方",
        "どこ",
        "場所",
        "何階",
        "受付へ",
        "受付に",
        "トイレ",
        "目的地",
        "現在地",
        "地図",
        "向かいたい",
        "行きたい",
    )

    def __init__(self) -> None:
        self.mode = ChatMode.RESEARCH

    def classify(self, text: str) -> ChatMode:
        lowered = text.casefold()
        if any(marker in lowered for marker in self._navigation_markers):
            self.mode = ChatMode.NAVIGATION
        return self.mode

    def set_mode(self, mode: ChatMode) -> None:
        self.mode = mode
