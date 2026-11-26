"""全局配置中心：加载/修改 .env，解析路径，校验配置。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.filesystem import PHP_VERSIONS, ensure_layout, read_json, write_json, write_text
from utils.log import get_logger

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

DEFAULTS: Dict[str, str] = {
    "DEV_HOME": "${HOME}/DevEnvironment",
    "PROJECTS_HOME": "${HOME}/Projects",
    "PHP_DEFAULT_VERSION": "8.3",
    "PHP_FPM_ENABLED_VERSIONS": "8.3",
    "NGINX_HTTP_PORT": "8080",
    "NGINX_HTTPS_PORT": "8443",
    "NGINX_ENABLED": "true",
    "MYSQL_VERSION": "8.0",
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_PORT": "3307",
    "MYSQL_ENABLED": "true",
    "MYSQL_DATA_DIR": "${DEV_HOME}/data/mysql",
    "REDIS_VERSION": "latest",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6380",
    "REDIS_ENABLED": "true",
    "REDIS_DATA_DIR": "${DEV_HOME}/data/redis",
    "NODE_DEFAULT_VERSION": "22",
    "COMPOSER_ENABLED": "true",
    "AUTO_START": "false",
    "AUTO_BACKUP": "true",
    "KEEP_DATA_ON_UNINSTALL": "true",
}

# 每个布尔键的合法值
BOOL_KEYS = {
    "NGINX_ENABLED",
    "MYSQL_ENABLED",
    "REDIS_ENABLED",
    "COMPOSER_ENABLED",
    "AUTO_START",
    "AUTO_BACKUP",
    "KEEP_DATA_ON_UNINSTALL",
}
PORT_KEYS = {"NGINX_HTTP_PORT", "NGINX_HTTPS_PORT", "MYSQL_PORT", "REDIS_PORT"}

ENV_ORDER = [
    "DEV_HOME",
    "PROJECTS_HOME",
    "PHP_DEFAULT_VERSION",
    "PHP_FPM_ENABLED_VERSIONS",
    "NGINX_HTTP_PORT",
    "NGINX_HTTPS_PORT",
    "NGINX_ENABLED",
    "MYSQL_VERSION",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_ENABLED",
    "MYSQL_DATA_DIR",
    "REDIS_VERSION",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_ENABLED",
    "REDIS_DATA_DIR",
    "NODE_DEFAULT_VERSION",
    "COMPOSER_ENABLED",
    "AUTO_START",
    "AUTO_BACKUP",
    "KEEP_DATA_ON_UNINSTALL",
]


class Config:
    def __init__(self, root: Optional[Path] = None) -> None:
        env_root = os.environ.get("DEV_HOME")
        if root:
            self.root = Path(root).expanduser()
        elif env_root:
            self.root = Path(env_root).expanduser()
        else:
            self.root = Path(__file__).resolve().parents[2]
        self.env_path = self.root / ".env"
        self.values: Dict[str, str] = {}
        self.load()

    # ------------------------------------------------------------------ 加载
    def load(self) -> None:
        data: Dict[str, str] = {}
        if self.env_path.exists():
            for raw in self.env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    data[key] = value
        merged = dict(DEFAULTS)
        merged.update(data)
        self.values = {
            key: self._expand(value, merged) for key, value in merged.items()
        }
        os.environ.setdefault("DEV_HOME", str(self.root))

    def _expand(self, value: str, table: Dict[str, str], depth: int = 0) -> str:
        if depth > 6 or "$" not in value:
            return value

        def replace(match: "re.Match[str]") -> str:
            name = match.group(1) or match.group(2)
            if name == "HOME":
                return str(Path.home())
            if name == "DEV_HOME":
                return str(self.root)
            if name in table:
                return self._expand(table[name], table, depth + 1)
            return os.environ.get(name, match.group(0))

        return ENV_REF.sub(replace, value)

    # ------------------------------------------------------------------ 读取
    def get(self, key: str, default: Optional[str] = None) -> str:
        if key in self.values:
            return self.values[key]
        if key in DEFAULTS:
            return self._expand(DEFAULTS[key], dict(DEFAULTS))
        return default if default is not None else ""

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key).strip().lower()
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        return default

    def get_list(self, key: str, default: Optional[List[str]] = None) -> List[str]:
        value = self.get(key).strip()
        if not value:
            return list(default or [])
        return [item.strip() for item in value.split(",") if item.strip()]

    def as_dict(self) -> Dict[str, str]:
        return {key: self.get(key) for key in ENV_ORDER}

    # ------------------------------------------------------------------ 路径
    @property
    def home(self) -> Path:
        return self.root

    @property
    def projects_home(self) -> Path:
        return Path(self.get("PROJECTS_HOME")).expanduser()

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def run_dir(self) -> Path:
        return self.root / "run"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def launch_agents_dir(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents"

    @property
    def projects_json(self) -> Path:
        return self.config_dir / "projects" / "projects.json"

    @property
    def nginx_conf(self) -> Path:
        return self.config_dir / "nginx" / "nginx.conf"

    @property
    def nginx_projects_dir(self) -> Path:
        return self.config_dir / "nginx" / "projects"

    @property
    def redis_conf(self) -> Path:
        return self.config_dir / "redis" / "redis.conf"

    def php_dir(self, version: str) -> Path:
        return self.config_dir / "php" / version

    def php_ini(self, version: str) -> Path:
        return self.php_dir(version) / "php.ini"

    def php_conf_d(self, version: str) -> Path:
        return self.php_dir(version) / "conf.d"

    def php_fpm_conf(self, version: str) -> Path:
        return self.php_dir(version) / "php-fpm.conf"

    def php_socket(self, version: str) -> Path:
        return self.run_dir / "php" / f"php{version.replace('.', '')}.sock"

    def php_fpm_pid(self, version: str) -> Path:
        return self.run_dir / "php" / f"php{version.replace('.', '')}-fpm.pid"

    def mysql_conf(self, version: str) -> Path:
        return self.config_dir / "mysql" / version / "my.cnf"

    def mysql_data_dir(self, version: str) -> Path:
        return self.data_dir / "mysql" / version / "data"

    def mysql_socket(self, version: str) -> Path:
        return self.run_dir / "mysql" / f"mysql{version.replace('.', '')}.sock"

    def mysql_pid(self, version: str) -> Path:
        return self.run_dir / "mysql" / f"mysql{version.replace('.', '')}.pid"

    def redis_data_dir(self) -> Path:
        return self.data_dir / "redis" / "data"

    def redis_pid(self) -> Path:
        return self.run_dir / "redis" / "redis.pid"

    # ------------------------------------------------------------------ 写入
    def set_env(self, key: str, value: str) -> None:
        """只修改 .env 中对应行，保留注释与其他配置。"""
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            lines = []
        pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
        replaced = False
        new_lines = []
        for line in lines:
            if pattern.match(line):
                new_lines.append(f"{key}={value}\n")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            new_lines.append(f"{key}={value}\n")
        write_text(self.env_path, "".join(new_lines))
        self.load()
        get_logger().info(f"config set {key}={value}")

    def save_snapshot(self) -> None:
        write_json(self.config_dir / "environment.json", self.as_dict())

    # ------------------------------------------------------------------ 校验
    def validate(self) -> List[Tuple[str, str]]:
        issues: List[Tuple[str, str]] = []
        for key in PORT_KEYS:
            try:
                port = int(self.get(key))
            except ValueError:
                issues.append(("error", f"{key} 不是合法端口: {self.get(key)}"))
                continue
            if not 1 <= port <= 65535:
                issues.append(("error", f"{key} 超出 1-65535: {port}"))
        ports = {
            "NGINX_HTTP_PORT": self.get_int("NGINX_HTTP_PORT"),
            "NGINX_HTTPS_PORT": self.get_int("NGINX_HTTPS_PORT"),
            "MYSQL_PORT": self.get_int("MYSQL_PORT"),
            "REDIS_PORT": self.get_int("REDIS_PORT"),
        }
        seen: Dict[int, str] = {}
        for key, port in ports.items():
            if port in seen:
                issues.append(("error", f"端口冲突: {key} 与 {seen[port]} 都使用 {port}"))
            else:
                seen[port] = key
        for key in BOOL_KEYS:
            value = self.get(key).lower()
            if value not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                issues.append(("error", f"{key} 必须是布尔值: {self.get(key)}"))
        default_php = self.get("PHP_DEFAULT_VERSION")
        if default_php not in PHP_VERSIONS:
            issues.append(("error", f"PHP_DEFAULT_VERSION 不支持: {default_php}"))
        for version in self.get_list("PHP_FPM_ENABLED_VERSIONS"):
            if version not in PHP_VERSIONS:
                issues.append(("error", f"PHP_FPM_ENABLED_VERSIONS 含不支持的版本: {version}"))
        if self.get("MYSQL_VERSION") not in ("8.0", "8.4"):
            issues.append(("error", f"MYSQL_VERSION 仅支持 8.0 / 8.4: {self.get('MYSQL_VERSION')}"))
        if not self.projects_home.parent.exists():
            issues.append(("warn", f"项目根目录的上级不存在: {self.projects_home.parent}"))
        if "root" in self.get("MYSQL_HOST") and self.get("MYSQL_HOST") not in ("127.0.0.1", "localhost"):
            issues.append(("warn", "MySQL 建议只监听 127.0.0.1"))
        return issues

    # ------------------------------------------------------------------ 初始化
    def init_layout(self) -> None:
        ensure_layout(self.root)
        if not self.env_path.exists():
            example = self.root / ".env.example"
            if example.exists():
                write_text(self.env_path, example.read_text(encoding="utf-8"))
            self.load()
        if not self.projects_json.exists():
            write_json(self.projects_json, {"projects": []})
        self.save_snapshot()


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> Config:
    global _config
    _config = Config()
    return _config
