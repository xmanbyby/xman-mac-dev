"""数据库与缓存的客户端封装：MySQL / Redis。密码从 Keychain 读取。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from core import installer
from core.config import get_config
from utils import shell, system
from utils import security
from utils.log import get_logger


class DatabaseError(RuntimeError):
    pass


class MySQLClient:
    def __init__(self) -> None:
        self.config = get_config()
        self.log = get_logger()

    # ------------------------------------------------------------------ 二进制
    def keg(self, version: str) -> Optional[Path]:
        prefix = installer.keg_prefix(f"mysql@{version}")
        return Path(prefix) if prefix else None

    def binary(self, version: str, name: str) -> Optional[Path]:
        keg = self.keg(version)
        if not keg:
            return None
        candidate = keg / "bin" / name
        return candidate if candidate.exists() else None

    def root_password(self) -> Optional[str]:
        return security.keychain_get("mysql.root")

    def _cnf(self, version: str, user: str, password: str, database: Optional[str] = None) -> Path:
        run_dir = self.config.run_dir / "mysql"
        run_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="client-", suffix=".cnf", dir=str(run_dir))
        os.chmod(path, 0o600)
        lines = [
            "[client]",
            f"host={self.config.get('MYSQL_HOST', '127.0.0.1')}",
            f"port={self.config.get_int('MYSQL_PORT', 3307)}",
            f"user={user}",
            f"password={password}",
            f"socket={self.config.mysql_socket(version)}",
        ]
        if database:
            lines.append(f"database={database}")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return Path(path)

    def execute(
        self,
        version: str,
        sql: str,
        user: str = "root",
        password: Optional[str] = None,
        database: Optional[str] = None,
        timeout: int = 120,
    ) -> "shell.CommandResult":
        binary = self.binary(version, "mysql")
        if not binary:
            raise DatabaseError(f"MySQL {version} 未安装")
        pwd = password if password is not None else (self.root_password() or "")
        cnf = self._cnf(version, user, pwd, database)
        try:
            return shell.run(
                [str(binary), f"--defaults-extra-file={cnf}", "--batch", "--raw", "--default-character-set=utf8mb4", "-e", sql],
                quiet=True,
                timeout=timeout,
            )
        finally:
            cnf.unlink(missing_ok=True)

    def query(
        self,
        version: str,
        sql: str,
        user: str = "root",
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> List[List[str]]:
        result = self.execute(version, sql, user=user, password=password, database=database)
        if not result.ok:
            raise DatabaseError(result.brief())
        rows: List[List[str]] = []
        for line in result.stdout.splitlines():
            rows.append(line.split("\t"))
        return rows

    def ping(self, version: str, user: str = "root", password: Optional[str] = None) -> bool:
        try:
            result = self.execute(version, "SELECT 1;", user=user, password=password, timeout=30)
        except DatabaseError:
            return False
        return result.ok

    def wait_ready(self, version: str, timeout: int = 30) -> bool:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            if system.port_connectable(self.config.get_int("MYSQL_PORT", 3307)):
                if self.ping(version) or self.ping(version, password=""):
                    return True
            time.sleep(0.5)
        return False

    def server_version(self, version: str) -> str:
        try:
            rows = self.query(version, "SELECT VERSION();")
        except DatabaseError:
            return ""
        return rows[1][0] if len(rows) > 1 else ""

    # ------------------------------------------------------------------ 用户/库
    def ensure_root_password(self, version: str, password: str) -> bool:
        result = self.execute(version, "SELECT 1;", password=password)
        if result.ok:
            return True
        alter = (
            "ALTER USER 'root'@'localhost' IDENTIFIED BY "
            + self._quote(password)
            + "; FLUSH PRIVILEGES;"
        )
        first = self.execute(version, alter, password="")
        if not first.ok:
            first = self.execute(version, alter, password=password)
        if not first.ok:
            return False
        security.keychain_set("mysql.root", password)
        return self.ping(version, password=password)

    def create_user(self, version: str, name: str, password: str) -> None:
        for host in ("localhost", "127.0.0.1"):
            sql = (
                f"CREATE USER IF NOT EXISTS '{name}'@'{host}' IDENTIFIED BY {self._quote(password)};"
                f"ALTER USER '{name}'@'{host}' IDENTIFIED BY {self._quote(password)};"
            )
            result = self.execute(version, sql)
            if not result.ok:
                raise DatabaseError(f"创建用户失败: {result.brief()}")
        security.keychain_set(f"mysql.{name}", password)

    def set_user_password(self, version: str, name: str, password: str) -> None:
        hosts = self._existing_hosts(version, name)
        if not hosts:
            raise DatabaseError(f"用户 {name} 不存在，请先执行: dev mysql user create {name}")
        for host in hosts:
            sql = f"ALTER USER '{name}'@'{host}' IDENTIFIED BY {self._quote(password)};"
            result = self.execute(version, sql)
            if not result.ok:
                raise DatabaseError(f"修改用户密码失败: {result.brief()}")
        security.keychain_set(f"mysql.{name}", password)

    def delete_user(self, version: str, name: str) -> None:
        for host in ("localhost", "127.0.0.1"):
            self.execute(version, f"DROP USER IF EXISTS '{name}'@'{host}';")
        security.keychain_delete(f"mysql.{name}")

    def list_users(self, version: str) -> List[Tuple[str, str]]:
        rows = self.query(
            version,
            "SELECT user, host FROM mysql.user "
            "WHERE user NOT IN ('mysql.sys','mysql.session','mysql.infoschema') ORDER BY user, host;",
        )
        return [(row[0], row[1]) for row in rows[1:] if len(row) >= 2]

    def create_database(self, version: str, name: str, owner: Optional[str] = None) -> bool:
        result = self.execute(
            version,
            f"CREATE DATABASE IF NOT EXISTS `{name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        )
        if not result.ok:
            raise DatabaseError(f"创建数据库失败: {result.brief()}")
        auto_created = False
        if owner:
            hosts = self._existing_hosts(version, owner)
            if not hosts:
                self.create_user(version, owner, owner)
                hosts = self._existing_hosts(version, owner)
                auto_created = True
            for host in hosts:
                grant = self.execute(version, f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{owner}'@'{host}';")
                if not grant.ok:
                    raise DatabaseError(f"授权失败: {grant.brief()}")
            self.execute(version, "FLUSH PRIVILEGES;")
        return auto_created

    def _existing_hosts(self, version: str, name: str) -> List[str]:
        rows = self.query(version, f"SELECT host FROM mysql.user WHERE user = {self._quote(name)} ORDER BY host;")
        return [row[0] for row in rows[1:] if row]

    def list_databases(self, version: str) -> List[str]:
        rows = self.query(version, "SHOW DATABASES;")
        return [row[0] for row in rows[1:] if row]

    def drop_database(self, version: str, name: str) -> None:
        self.execute(version, f"DROP DATABASE IF EXISTS `{name}`;")

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class RedisClient:
    def __init__(self) -> None:
        self.config = get_config()
        self.log = get_logger()

    def binary(self, name: str = "redis-cli") -> str:
        prefix = installer.keg_prefix("redis")
        if prefix:
            candidate = Path(prefix) / "bin" / name
            if candidate.exists():
                return str(candidate)
        return name

    def default_password(self) -> Optional[str]:
        return security.keychain_get("redis.default")

    def run(self, args: List[str], password: Optional[str] = None, timeout: int = 120) -> "shell.CommandResult":
        pwd = password if password is not None else (self.default_password() or "")
        cmd = [self.binary(), "-h", self.config.get("REDIS_HOST", "127.0.0.1"),
               "-p", str(self.config.get_int("REDIS_PORT", 6380)), "--no-auth-warning"]
        if args:
            cmd += args
        env = {}
        if pwd:
            env["REDISCLI_AUTH"] = pwd
        return shell.run(cmd, env=env, quiet=True, timeout=timeout)

    def ping(self, password: Optional[str] = None) -> bool:
        return self.run(["PING"], password=password, timeout=20).stdout.strip().upper() == "PONG"

    def execute(self, *args: str, password: Optional[str] = None) -> str:
        result = self.run(list(args), password=password)
        if not result.ok:
            raise DatabaseError(result.brief())
        return result.stdout.strip()

    def server_version(self) -> str:
        try:
            return self.execute("INFO", "server").split("redis_version:")[1].splitlines()[0].strip()
        except (DatabaseError, IndexError):
            return ""
