"""Provider 基类。"""
from __future__ import annotations

from core.config import get_config
from core.installer import brew_prefix
from core.service import ServiceManager
from core.state import get_state
from utils.log import get_logger


class Provider:
    name = "provider"

    def __init__(self) -> None:
        self.config = get_config()
        self.state = get_state()
        self.services = ServiceManager()
        self.log = get_logger()
        self.brew_prefix = brew_prefix()
