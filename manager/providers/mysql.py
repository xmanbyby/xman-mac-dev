"""MySQL Provider：多版本安装、数据目录隔离、启停与版本切换。"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict, List, Optional

from core import installer
from core.config import get_config
from core.database import DatabaseError, MySQLClient
from core.service import ServiceError, ServiceSpec
from providers.base import Provider
from utils import shell, security, system
from utils.filesystem import MYSQL_VERSIONS, ensure_dir, write_text

MY_CNF = """# Managed by dev - 由管理器生成
[mysqld]
port = {port}
bind-address = {host}
datadir = {datadir}
socket = {socket}
pid-file = {pid}
log-error = {error_log}
secure_file_priv = {files}
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
default-time-zone = '+08:00'
max_connections = 200
max_allowed_packet = 64M
innodb_buffer_pool_size = 256M
innodb_flush_log_at_trx_commit = 2
slow_query_log = 1
slow_query_log_file = {slow_log}
long_query_time = 2
log_bin_trust_function_creators = 1

[client]
port = {port}
socket = {socket}
default-character-set = utf8mb4
"""


class MySQLProvider(Provider):
    name = "mysql"

    # ------------------------------------------------------------------ 基础
    def formula(self, version: str) -> str:
        return f"mysql@{version}"

    def keg(self, version: str) -> Optional[Path]:
        prefix = installer.keg_prefix(self.formula(version))
        return Path(prefix) if prefix else None

    def binary(self, version: str, name: str) -> Optional[Path]:
        keg = self.keg(version)
        if not keg:
            return None
        candidate = keg / "bin" / name
        return candidate if candidate.exists() else None

    def is_installed(self, version: str) -> bool:
        return installer.is_installed(self.formula(version)) and self.binary(version, "mysqld") is not None

    def installed_versions(self) -> List[str]:
        return [version for version in MYSQL_VERSIONS if self.is_installed(version)]

    def current_version(self) -> str:
        stored = self.state.versions().get("mysql")
        if stored and stored in MYSQL_VERSIONS:
            return stored
        installed = self.installed_versions()
        return installed[-1] if installed else self.config.get("MYSQL_VERSION", "8.4")

    def active_version(self) -> Optional[str]:
        """按状态文件顺序找到真正在运行的版本。"""
        for version in MYSQL_VERSIONS:
            if self.running(version):
                return version
        return None

    # ------------------------------------------------------------------ 配置
    def write_conf(self, version: str) -> Path:
        config = self.config
        datadir = config.mysql_data_dir(version)
        files = config.data_dir / "mysql" / version / "files"
        logs = config.logs_dir / "mysql" / version
        ensure_dir(datadir)
        ensure_dir(files)
        ensure_dir(logs)
        body = MY_CNF.format(
            port=config.get_int("MYSQL_PORT", 3307),
            host=config.get("MYSQL_HOST", "127.0.0.1"),
            datadir=datadir,
            socket=config.mysql_socket(version),
            pid=config.mysql_pid(version),
            error_log=logs / "error.log",
            files=files,
            slow_log=logs / "slow.log",
        )
        write_text(config.mysql_conf(version), body)
        return config.mysql_conf(version)

    def initialized(self, version: str) -> bool:
        datadir = self.config.mysql_data_dir(version)
        return (datadir / "mysql").is_dir() and any(datadir.iterdir()) if datadir.exists() else False

    def initialize(self, version: str) -> None:
        mysqld = self.binary(version, "mysqld")
        if not mysqld:
            raise RuntimeError(f"MySQL {version} 未安装")
        self.write_conf(version)
        datadir = self.config.mysql_data_dir(version)
        ensure_dir(datadir)
        if self.initialized(version):
            return
        print(f"初始化 MySQL {version} 数据目录: {datadir}")
        result = shell.run(
            [
                str(mysqld),
                f"--defaults-file={self.config.mysql_conf(version)}",
                "--initialize-insecure",
            ],
            quiet=True,
            timeout=600,
        )
        if not result.ok:
            raise RuntimeError(f"MySQL {version} 初始化失败: {result.brief()}")

    # ------------------------------------------------------------------ 安装
    def install(self, version: str) -> None:
        if version not in MYSQL_VERSIONS:
            raise ValueError(f"不支持的 MySQL 版本: {version}")
        if self.is_installed(version):
            print(f"MySQL {version} 已安装，跳过")
            self.initialize(version)
            return
        installer.install(self.formula(version))
        self.initialize(version)
        self.state.mark_installed("mysql", version)
        versions = self.state.versions()
        if not versions.get("mysql"):
            self.state.set_version("mysql", version)
        print(f"MySQL {version} 安装完成")

    def uninstall(self, version: str) -> None:
        self.stop(version)
        self.services.remove(self.spec(version))
        installer.uninstall(self.formula(version))
        self.state.mark_uninstalled("mysql", version)
        print(f"MySQL {version} 已卸载（数据目录与备份保留）")

    def purge(self, version: str) -> None:
        self.stop(version)
        self.services.remove(self.spec(version))
        installer.uninstall(self.formula(version))
        self.state.mark_uninstalled("mysql", version)
        data = self.config.data_dir / "mysql" / version
        if data.exists():
            import shutil

            shutil.rmtree(data)
        print(f"MySQL {version} 已彻底清理（含数据目录）")

    # ------------------------------------------------------------------ 服务
    def spec(self, version: str) -> ServiceSpec:
        return ServiceSpec(
            name=f"mysql-{version}",
            label=f"com.devenv.mysql.{version}",
            args=[
                str(self.binary(version, "mysqld") or "mysqld"),
                f"--defaults-file={self.config.mysql_conf(version)}",
            ],
            log_path=self.config.logs_dir / "mysql" / version / "launchd.out.log",
            pid_file=self.config.mysql_pid(version),
            port=self.config.get_int("MYSQL_PORT", 3307),
            display=f"mysql {version}",
        )

    def running(self, version: str) -> bool:
        """以各版本独立 pid 文件为准，避免端口被其他版本占用时误判。"""
        pid = system.read_pid(self.config.mysql_pid(version))
        return bool(pid and system.pid_alive(pid))

    def start(self, version: Optional[str] = None, init_password: bool = True) -> None:
        version = version or self.current_version()
        if not self.is_installed(version):
            raise RuntimeError(f"MySQL {version} 未安装，请先执行: dev mysql install {version}")
        self.initialize(version)
        self.write_conf(version)
        self.services.start(self.spec(version), timeout=60)
        client = MySQLClient()
        if not client.wait_ready(version, timeout=40):
            raise RuntimeError(f"MySQL {version} 启动后无法连接，请查看 logs/mysql/{version}/error.log")
        if init_password:
            stored = security.keychain_get("mysql.root")
            if stored and client.ping(version, password=stored):
                pass
            elif client.ping(version, password=""):
                password = stored or secrets.token_urlsafe(18)
                if client.ensure_root_password(version, password):
                    print("MySQL root 密码已初始化并写入 macOS Keychain (dev.mysql.root)")
                else:
                    self.log.warn("MySQL root 密码初始化失败，请执行 dev mysql password init")
            elif stored:
                self.log.warn("root 密码与 Keychain 不一致，请执行 dev mysql password init")
        self.state.save_services({**self.state.services(), "mysql": {
            "enabled": self.config.get_bool("MYSQL_ENABLED", True),
            "version": version,
            "port": self.config.get_int("MYSQL_PORT", 3307),
        }})
        print(f"MySQL {version} 已启动: {self.config.get('MYSQL_HOST')}:{self.config.get_int('MYSQL_PORT')}")

    def stop(self, version: Optional[str] = None) -> None:
        version = version or self.active_version() or self.current_version()
        self.services.stop(self.spec(version), timeout=60)
        print(f"MySQL {version} 已停止")

    def restart(self, version: Optional[str] = None) -> None:
        version = version or self.current_version()
        self.stop(version)
        self.start(version, init_password=False)

    def switch(self, version: str) -> None:
        if not self.is_installed(version):
            raise RuntimeError(f"MySQL {version} 未安装，请先执行: dev mysql install {version}")
        active = self.active_version()
        if active and active != version:
            self.stop(active)
        self.state.set_version("mysql", version)
        self.config.set_env("MYSQL_VERSION", version)
        self.start(version)
        print(f"MySQL 已切换并运行于 {version}")

    def upgrade(self, from_version: str, to_version: str, dump_file: Path) -> None:
        """逻辑升级：备份旧版本 -> 启动新版本 -> 导入。"""
        if not dump_file.exists():
            raise RuntimeError("升级前备份文件不存在")
        self.stop(from_version)
        if not self.is_installed(to_version):
            self.install(to_version)
        self.state.set_version("mysql", to_version)
        self.config.set_env("MYSQL_VERSION", to_version)
        self.start(to_version)
        binary = self.binary(to_version, "mysql")
        if not binary:
            raise RuntimeError(f"MySQL {to_version} 客户端不存在")
        client = MySQLClient()
        cnf = client._cnf(to_version, "root", client.root_password() or "")
        try:
            result = shell.run(
                ["/bin/sh", "-c", f'"{binary}" --defaults-extra-file="{cnf}" < "{dump_file}"'],
                quiet=True,
                timeout=3600,
            )
        finally:
            cnf.unlink(missing_ok=True)
        if not result.ok:
            raise DatabaseError(f"升级导入失败: {result.brief()}")
        print(f"MySQL 已从 {from_version} 逻辑升级到 {to_version}")

    # ------------------------------------------------------------------ 信息
    def info(self, version: Optional[str] = None) -> Dict[str, str]:
        version = version or self.current_version()
        client = MySQLClient()
        return {
            "配置版本": version,
            "运行状态": "running" if self.running(version) else "stopped",
            "服务端版本": client.server_version(version) if self.running(version) else "-",
            "监听": f"{self.config.get('MYSQL_HOST')}:{self.config.get_int('MYSQL_PORT')}",
            "数据目录": str(self.config.mysql_data_dir(version)),
            "配置文件": str(self.config.mysql_conf(version)),
            "Socket": str(self.config.mysql_socket(version)),
            "已安装版本": ", ".join(self.installed_versions()) or "-",
        }
