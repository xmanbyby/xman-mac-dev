"""环境诊断 doctor。"""
from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from typing import List, Optional

from core import installer
from core.config import get_config
from core.state import get_state
from utils import security, shell, system
from utils.filesystem import MYSQL_VERSIONS, PHP_VERSIONS


@dataclass
class Check:
    name: str
    status: str  # ok / warn / fail
    detail: str = ""
    advice: str = ""


class Doctor:
    def __init__(self) -> None:
        self.config = get_config()
        self.state = get_state()
        self.checks: List[Check] = []

    def add(self, name: str, status: str, detail: str = "", advice: str = "") -> None:
        self.checks.append(Check(name, status, detail, advice))

    # ------------------------------------------------------------------ 执行
    def run(self, scope: Optional[str] = None) -> List[Check]:
        self.system_checks()
        self.config_checks()
        if scope in (None, "php"):
            self.php_checks()
        if scope in (None, "nginx"):
            self.nginx_checks()
        if scope in (None, "mysql"):
            self.mysql_checks()
        if scope in (None, "redis"):
            self.redis_checks()
        if scope in (None, "node", "composer"):
            self.node_composer_checks()
        if scope is None:
            self.port_checks()
            self.service_conflict_checks()
            self.backup_checks()
        return self.checks

    # ------------------------------------------------------------------ 基础
    def system_checks(self) -> None:
        version = system.macos_version()
        if version:
            major = int(version.split(".")[0])
            self.add("macOS", "ok" if major >= 12 else "warn", f"{version}",
                     "" if major >= 12 else "建议升级到 macOS 12 以上")
        else:
            self.add("macOS", "warn", "无法读取版本")
        self.add("CPU 架构", "ok" if system.is_apple_silicon() else "warn", system.arch(),
                 "" if system.is_apple_silicon() else "本方案针对 Apple Silicon 设计")
        if installer.brew_available():
            self.add("Homebrew", "ok", f"{shell.output(['brew', '--version']).splitlines()[0] if shell.output(['brew', '--version']) else ''}")
        else:
            self.add("Homebrew", "fail", "未找到 brew", "安装: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        self.add("Python", "ok", platform.python_version())
        free = system.disk_free_gb(self.config.home)
        self.add("磁盘空间", "ok" if free >= 10 else "warn", f"剩余 {free} GB",
                 "" if free >= 10 else "建议至少保留 10 GB")

    def config_checks(self) -> None:
        if not self.config.env_path.exists():
            self.add(".env", "fail", "不存在", "执行: dev init")
        else:
            self.add(".env", "ok", str(self.config.env_path))
        issues = self.config.validate()
        if not issues:
            self.add("配置校验", "ok", "全部通过")
        for level, message in issues:
            self.add("配置校验", "fail" if level == "error" else "warn", message)
        for path, label in (
            (self.config.config_dir, "配置目录"),
            (self.config.data_dir, "数据目录"),
            (self.config.run_dir, "运行目录"),
            (self.config.logs_dir, "日志目录"),
        ):
            if not path.exists():
                self.add(label, "warn", f"不存在: {path}", "执行: dev init")
            elif not path.is_dir():
                self.add(label, "fail", f"不是目录: {path}")
            else:
                self.add(label, "ok", str(path))
        if self.config.projects_home.exists():
            self.add("项目根目录", "ok", str(self.config.projects_home))
        else:
            self.add("项目根目录", "warn", f"不存在: {self.config.projects_home}", "创建目录或 dev config set PROJECTS_HOME")

    # ------------------------------------------------------------------ 组件
    def php_checks(self) -> None:
        from providers.php import PHPProvider

        provider = PHPProvider()
        installed = provider.installed_versions()
        if not installed:
            self.add("PHP", "warn", "未安装任何版本", "执行: dev php install 8.3")
        for version in installed:
            binary = provider.cli_binary(version)
            modules = provider.module_list(version)
            status = "ok" if modules else "warn"
            self.add(f"PHP {version}", status, f"{provider.version_string(version) or 'unknown'} | 扩展 {len(modules)} 个",
                     "" if modules else "执行: dev ext doctor --php=" + version)
            if provider.fpm_running(version):
                self.add(f"PHP-FPM {version}", "ok", f"socket {self.config.php_socket(version)}")
            else:
                self.add(f"PHP-FPM {version}", "warn", "未运行", f"执行: dev php fpm start {version}")
        default = provider.current_cli()
        self.add("PHP CLI 默认版本", "ok" if default else "warn", default or "未设置",
                 "" if default else "执行: dev php switch 8.3")

    def nginx_checks(self) -> None:
        from providers.nginx import NginxProvider

        provider = NginxProvider()
        if not provider.is_installed():
            self.add("Nginx", "warn", "未安装", "执行: dev nginx install")
            return
        self.add("Nginx", "ok", provider.binary())
        if provider.test(verbose=False):
            self.add("Nginx 配置", "ok", "语法检查通过")
        else:
            self.add("Nginx 配置", "fail", "语法检查失败", "执行: dev nginx test")
        self.add("Nginx 服务", "ok" if provider.running() else "warn",
                 "running" if provider.running() else "stopped",
                 "" if provider.running() else "执行: dev nginx start")

    def mysql_checks(self) -> None:
        from core.database import MySQLClient
        from providers.mysql import MySQLProvider

        provider = MySQLProvider()
        installed = provider.installed_versions()
        if not installed:
            self.add("MySQL", "warn", "未安装", "执行: dev mysql install 8.4")
            return
        self.add("MySQL 已安装版本", "ok", ", ".join(installed))
        active = provider.active_version()
        if active:
            self.add("MySQL 服务", "ok", f"{active} running")
            client = MySQLClient()
            if client.ping(active):
                self.add("MySQL 连接", "ok", f"{self.config.get('MYSQL_HOST')}:{self.config.get_int('MYSQL_PORT')}")
            else:
                self.add("MySQL 连接", "fail", "无法使用 Keychain 中的 root 密码连接",
                         "执行: dev mysql password init")
        else:
            self.add("MySQL 服务", "warn", "未运行", "执行: dev mysql start")
        if security.keychain_get("mysql.root"):
            self.add("MySQL root 密码", "ok", "已保存在 Keychain")
        else:
            self.add("MySQL root 密码", "warn", "Keychain 中不存在", "执行: dev mysql password init")
        for version in installed:
            self.add(f"MySQL {version} 数据目录", "ok" if self.config.mysql_data_dir(version).exists() else "warn",
                     str(self.config.mysql_data_dir(version)))

    def redis_checks(self) -> None:
        from core.database import RedisClient
        from providers.redis import RedisProvider

        provider = RedisProvider()
        if not provider.is_installed():
            self.add("Redis", "warn", "未安装", "执行: dev redis install")
            return
        self.add("Redis", "ok", provider.binary())
        if provider.running():
            self.add("Redis 服务", "ok", f"{self.config.get('REDIS_HOST')}:{self.config.get_int('REDIS_PORT')}")
        else:
            self.add("Redis 服务", "warn", "未运行", "执行: dev redis start")
        if RedisClient().ping():
            self.add("Redis 连接", "ok", "PONG")
        else:
            self.add("Redis 连接", "warn", "PING 失败（未运行或密码未同步）",
                     "执行: dev redis start 或 dev redis password init")
        if security.keychain_get("redis.default"):
            self.add("Redis 密码", "ok", "已保存在 Keychain")
        else:
            self.add("Redis 密码", "warn", "未设置（本地开发可接受）", "执行: dev redis password init")

    def node_composer_checks(self) -> None:
        from providers.composer import ComposerProvider
        from providers.node import NodeProvider

        node = NodeProvider()
        if node.is_installed():
            self.add("fnm", "ok", node.fnm() or "")
            versions = node.list_versions()
            self.add("Node 版本", "ok" if versions else "warn", ", ".join(versions) or "未安装任何版本",
                     "" if versions else "执行: dev node install 22")
        else:
            self.add("fnm", "warn", "未安装", "执行: dev node install")
        composer = ComposerProvider()
        if composer.is_installed():
            self.add("Composer", "ok", composer.version())
        else:
            self.add("Composer", "warn", "未安装", "执行: dev composer install")

    # ------------------------------------------------------------------ 端口
    def port_checks(self) -> None:
        ports = {
            "Nginx HTTP": self.config.get_int("NGINX_HTTP_PORT", 8080),
            "Nginx HTTPS": self.config.get_int("NGINX_HTTPS_PORT", 8443),
            "MySQL": self.config.get_int("MYSQL_PORT", 3307),
            "Redis": self.config.get_int("REDIS_PORT", 6380),
        }
        for label, port in ports.items():
            owners = system.port_owners(port)
            if not owners:
                self.add(f"端口 {port} ({label})", "ok", "可用")
            else:
                detail = ", ".join(f"PID {item.pid} ({item.command})" for item in owners)
                managed = {"nginx", "mysqld", "redis-server", "php-fpm"} & {item.command for item in owners}
                if managed:
                    self.add(f"端口 {port} ({label})", "ok", f"由本环境服务占用: {detail}")
                else:
                    self.add(f"端口 {port} ({label})", "warn", f"被其他进程占用: {detail}",
                             "修改端口 (dev config set) 或停止占用进程")

    def service_conflict_checks(self) -> None:
        conflicts = [name for name in installer.services_list()
                     if name in ("nginx", "mysql", "mysql@8.0", "mysql@8.4", "redis", "php")]
        if conflicts:
            self.add("brew services 冲突", "fail", "以下服务被 brew services 托管: " + ", ".join(conflicts),
                     "执行: brew services stop <服务>，统一交给 dev 管理")
        else:
            self.add("brew services 冲突", "ok", "未发现双重托管")

    def backup_checks(self) -> None:
        base = self.config.backups_dir / "config"
        items = sorted(base.glob("*.tar.gz"), reverse=True) if base.exists() else []
        if items:
            self.add("配置备份", "ok", items[0].name)
        else:
            self.add("配置备份", "warn", "尚无配置备份", "执行: dev backup config")
