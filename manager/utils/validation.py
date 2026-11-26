"""输入校验。"""
from __future__ import annotations

import re
from typing import Iterable

SERVICE_NAMES = {"nginx", "mysql", "redis", "php", "node", "composer"}
DOMAIN_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$")


def valid_php_version(version: str, available: Iterable[str]) -> bool:
    return version in set(available)


def valid_port(port: int) -> bool:
    return 1 <= port <= 65535


def valid_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.match(domain))


def valid_name(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,62}$", name))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
