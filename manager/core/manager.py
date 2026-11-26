"""总体编排：一键安装 / 启动 / 停止 / 重启 / 卸载 / 清理 / 状态。"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core import installer
from core.config import get_config
from core.dependency import startup_order
from core.state import get_state
from utils import security, shell, system
from utils.filesystem import ensure_dir
from utils.log import get_logger

COMPONENTS = ["php", "nginx", "mysql", "redis", "node", "composer"]


class Manager:
    def __init__(self) -> None:
        self.config = get_config()
        self.state = get_state()
        self.log = get_logger()

    # ------------------------------------------------------------------ 状态
    def status_rows(self) -> List[Dict[str, str]]:
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        rows: List[Dict[str, str]] = []
        mysql = MySQLProvider()
        active = mysql.active_version()
        rows.append({
            "服务": "mysql",
            "状态": "running" if active else "stopped",
            "版本": active or mysql.current_version(),
            "地址": f"{self.config.get('MYSQL_HOST')}:{self.config.get_int('MYSQL_PORT')}",
            "PID": str(system.read_pid(self.config.mysql_pid(active)) or "-") if active else "-",
        })
        redis = RedisProvider()
        running = redis.running()
        rows.append({
            "服务": "redis",
            "状态": "running" if running else "stopped",
            "版本": redis.info().get("服务端版本", "-"),
            "地址": f"{self.config.get('REDIS_HOST')}:{self.config.get_int('REDIS_PORT')}",
            "PID": str(system.read_pid(self.config.redis_pid()) or "-") if running else "-",
        })
        php = PHPProvider()
        for version in php.installed_versions():
            running_fpm = php.fpm_running(version)
            rows.append({
                "服务": f"php-fpm {version}",
                "状态": "running" if running_fpm else "stopped",
                "版本": php.version_string(version) or "-",
                "地址": f"unix:{self.config.php_socket(version).name}",
                "PID": str(system.read_pid(self.config.php_fpm_pid(version)) or "-") if running_fpm else "-",
            })
        nginx = NginxProvider()
        nginx_running = nginx.running()
        rows.append({
            "服务": "nginx",
            "状态": "running" if nginx_running else "stopped",
            "版本": shell.output([nginx.binary(), "-v"]).replace("nginx version: ", "") if nginx.is_installed() else "未安装",
            "地址": f"http://127.0.0.1:{self.config.get_int('NGINX_HTTP_PORT')}",
            "PID": str(system.read_pid(self.config.run_dir / "nginx" / "nginx.pid") or "-") if nginx_running else "-",
        })
        return rows

    # ------------------------------------------------------------------ 生命周期
    def up(self, only: Optional[List[str]] = None) -> List[Tuple[str, bool, str]]:
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        order = startup_order(only)
        explicit = bool(only)
        results: List[Tuple[str, bool, str]] = []
        php_failed = False

        for name in order:
            if name == "mysql":
                if not explicit and not self.config.get_bool("MYSQL_ENABLED", True):
                    continue
                try:
                    MySQLProvider().start()
                    results.append(("mysql", True, "已启动"))
                except Exception as exc:  # noqa: BLE001 - 汇总并继续其他服务
                    self.log.error(f"mysql start failed: {exc}")
                    results.append(("mysql", False, str(exc)))
            elif name == "redis":
                if not explicit and not self.config.get_bool("REDIS_ENABLED", True):
                    continue
                try:
                    RedisProvider().start()
                    results.append(("redis", True, "已启动"))
                except Exception as exc:  # noqa: BLE001
                    self.log.error(f"redis start failed: {exc}")
                    results.append(("redis", False, str(exc)))
            elif name == "php":
                provider = PHPProvider()
                versions = provider.enabled_fpm_versions()
                if explicit:
                    versions = provider.installed_versions()
                if not versions:
                    results.append(("php-fpm", False, "没有已启用的 PHP 版本"))
                    php_failed = True
                    continue
                for version in versions:
                    try:
                        provider.start_fpm(version)
                        results.append((f"php-fpm {version}", True, "已启动"))
                    except Exception as exc:  # noqa: BLE001
                        php_failed = True
                        self.log.error(f"php-fpm {version} start failed: {exc}")
                        results.append((f"php-fpm {version}", False, str(exc)))
            elif name == "nginx":
                if not explicit and not self.config.get_bool("NGINX_ENABLED", True):
                    continue
                if php_failed:
                    results.append(("nginx", False, "依赖的 PHP-FPM 未就绪，已跳过"))
                    continue
                try:
                    NginxProvider().start()
                    results.append(("nginx", True, "已启动"))
                except Exception as exc:  # noqa: BLE001
                    self.log.error(f"nginx start failed: {exc}")
                    results.append(("nginx", False, str(exc)))
        return results

    def down(self, only: Optional[List[str]] = None) -> List[Tuple[str, bool, str]]:
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        selected = set(only) if only else {"mysql", "redis", "php", "nginx"}
        results: List[Tuple[str, bool, str]] = []

        if "nginx" in selected:
            nginx = NginxProvider()
            try:
                if nginx.running():
                    nginx.stop()
                results.append(("nginx", True, "已停止"))
            except Exception as exc:  # noqa: BLE001
                results.append(("nginx", False, str(exc)))

        if "php" in selected:
            php = PHPProvider()
            stopped = False
            for version in php.installed_versions():
                if not php.fpm_running(version):
                    continue
                stopped = True
                try:
                    php.stop_fpm(version)
                    results.append((f"php-fpm {version}", True, "已停止"))
                except Exception as exc:  # noqa: BLE001
                    results.append((f"php-fpm {version}", False, str(exc)))
            if not stopped:
                results.append(("php-fpm", True, "未运行"))

        if "redis" in selected:
            redis = RedisProvider()
            try:
                if redis.running():
                    redis.stop()
                results.append(("redis", True, "已停止"))
            except Exception as exc:  # noqa: BLE001
                results.append(("redis", False, str(exc)))

        if "mysql" in selected:
            mysql = MySQLProvider()
            active = mysql.active_version()
            try:
                if active:
                    mysql.stop(active)
                results.append(("mysql", True, "已停止"))
            except Exception as exc:  # noqa: BLE001
                results.append(("mysql", False, str(exc)))
        return results

    def restart(self, only: Optional[List[str]] = None) -> List[Tuple[str, bool, str]]:
        if only:
            order = startup_order(only)
            # 只重启指定服务
            from providers.nginx import NginxProvider
            from providers.mysql import MySQLProvider
            from providers.php import PHPProvider
            from providers.redis import RedisProvider

            results: List[Tuple[str, bool, str]] = []
            if "nginx" in order:
                provider = NginxProvider()
                try:
                    provider.restart()
                    results.append(("nginx", True, "已重启"))
                except Exception as exc:  # noqa: BLE001
                    results.append(("nginx", False, str(exc)))
            if "php" in order:
                php = PHPProvider()
                for version in php.enabled_fpm_versions():
                    try:
                        php.restart_fpm(version)
                        results.append((f"php-fpm {version}", True, "已重启"))
                    except Exception as exc:  # noqa: BLE001
                        results.append((f"php-fpm {version}", False, str(exc)))
            if "redis" in order:
                try:
                    RedisProvider().restart()
                    results.append(("redis", True, "已重启"))
                except Exception as exc:  # noqa: BLE001
                    results.append(("redis", False, str(exc)))
            if "mysql" in order:
                mysql = MySQLProvider()
                try:
                    mysql.restart(mysql.active_version())
                    results.append(("mysql", True, "已重启"))
                except Exception as exc:  # noqa: BLE001
                    results.append(("mysql", False, str(exc)))
            return results
        self.down()
        return self.up()

    # ------------------------------------------------------------------ 安装
    def preflight(self) -> None:
        if not installer.brew_available():
            raise RuntimeError("Homebrew 不可用，请先安装 Homebrew")
        free = system.disk_free_gb(self.config.home)
        if free < 5:
            raise RuntimeError(f"磁盘剩余空间不足: {free} GB")
        for label, port in (
            ("Nginx", self.config.get_int("NGINX_HTTP_PORT")),
            ("MySQL", self.config.get_int("MYSQL_PORT")),
            ("Redis", self.config.get_int("REDIS_PORT")),
        ):
            owners = system.port_owners(port)
            if owners:
                detail = ", ".join(f"PID {item.pid} ({item.command})" for item in owners)
                self.log.warn(f"port {port} ({label}) already in use: {detail}")

    def install_all(
        self,
        components: Optional[List[str]] = None,
        with_extensions: bool = True,
    ) -> List[Tuple[str, bool, str]]:
        from providers.composer import ComposerProvider
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.node import NodeProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        targets = components or list(COMPONENTS)
        self.preflight()
        self.config.init_layout()
        results: List[Tuple[str, bool, str]] = []

        if "php" in targets:
            versions = []
            default = self.config.get("PHP_DEFAULT_VERSION", "8.3")
            versions.append(default)
            for version in self.config.get_list("PHP_FPM_ENABLED_VERSIONS"):
                if version not in versions:
                    versions.append(version)
            provider = PHPProvider()
            for version in versions:
                try:
                    provider.install(version)
                    results.append((f"php {version}", True, "已安装"))
                    if with_extensions:
                        ext_results = provider.install_default_extensions(version)
                        failed = [name for name, state in ext_results.items() if not state.startswith("ok")]
                        detail = "默认扩展已处理" if not failed else "部分扩展失败: " + ", ".join(failed)
                        results.append((f"php {version} 扩展", not failed, detail))
                except Exception as exc:  # noqa: BLE001
                    results.append((f"php {version}", False, str(exc)))

        if "nginx" in targets:
            try:
                NginxProvider().install()
                results.append(("nginx", True, "已安装"))
            except Exception as exc:  # noqa: BLE001
                results.append(("nginx", False, str(exc)))

        if "mysql" in targets:
            version = self.config.get("MYSQL_VERSION", "8.4")
            try:
                MySQLProvider().install(version)
                results.append((f"mysql {version}", True, "已安装"))
            except Exception as exc:  # noqa: BLE001
                results.append((f"mysql {version}", False, str(exc)))

        if "redis" in targets:
            try:
                RedisProvider().install()
                results.append(("redis", True, "已安装"))
            except Exception as exc:  # noqa: BLE001
                results.append(("redis", False, str(exc)))

        if "node" in targets:
            try:
                NodeProvider().install()
                results.append(("node", True, "已安装"))
            except Exception as exc:  # noqa: BLE001
                results.append(("node", False, str(exc)))

        if "composer" in targets:
            try:
                ComposerProvider().install()
                results.append(("composer", True, "已安装"))
            except Exception as exc:  # noqa: BLE001
                results.append(("composer", False, str(exc)))
        return results

    def uninstall(self, targets: List[str]) -> List[Tuple[str, bool, str]]:
        """按组件批量卸载，支持 php:8.3 / mysql:8.4 指定版本。"""
        from providers.composer import ComposerProvider
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.node import NodeProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        results: List[Tuple[str, bool, str]] = []
        wanted: Dict[str, List[Optional[str]]] = {}
        for token in targets:
            name, _, version = token.partition(":")
            name = name.strip()
            version = version.strip() or None
            if name not in COMPONENTS:
                results.append((token, False, f"未知组件，可选: {', '.join(COMPONENTS)}"))
                continue
            wanted.setdefault(name, []).append(version)

        if "nginx" in wanted:
            try:
                provider = NginxProvider()
                if provider.running():
                    provider.stop()
                provider.uninstall()
                results.append(("nginx", True, "已卸载（保留配置/日志）"))
            except Exception as exc:  # noqa: BLE001
                results.append(("nginx", False, str(exc)))

        if "redis" in wanted:
            try:
                provider = RedisProvider()
                if provider.running():
                    provider.stop()
                provider.uninstall()
                results.append(("redis", True, "已卸载（保留数据）"))
            except Exception as exc:  # noqa: BLE001
                results.append(("redis", False, str(exc)))

        if "composer" in wanted:
            try:
                ComposerProvider().uninstall()
                results.append(("composer", True, "已卸载"))
            except Exception as exc:  # noqa: BLE001
                results.append(("composer", False, str(exc)))

        if "node" in wanted:
            try:
                NodeProvider().uninstall()
                results.append(("node", True, "fnm 已卸载（Node 版本目录保留）"))
            except Exception as exc:  # noqa: BLE001
                results.append(("node", False, str(exc)))

        if "mysql" in wanted:
            provider = MySQLProvider()
            installed = provider.installed_versions()
            selected = [v for v in installed if None in wanted["mysql"] or v in wanted["mysql"]]
            if not selected:
                results.append(("mysql", True, "未安装，跳过"))
            for version in selected:
                try:
                    if provider.running(version):
                        provider.stop(version)
                    provider.uninstall(version)
                    results.append((f"mysql {version}", True, "已卸载（保留数据）"))
                except Exception as exc:  # noqa: BLE001
                    results.append((f"mysql {version}", False, str(exc)))

        if "php" in wanted:
            provider = PHPProvider()
            installed = provider.installed_versions()
            selected = [v for v in installed if None in wanted["php"] or v in wanted["php"]]
            if not selected:
                results.append(("php", True, "未安装，跳过"))
            for version in selected:
                try:
                    if provider.fpm_running(version):
                        provider.stop_fpm(version)
                    provider.uninstall(version)
                    results.append((f"php {version}", True, "已卸载（保留配置）"))
                except Exception as exc:  # noqa: BLE001
                    results.append((f"php {version}", False, str(exc)))
        return results

    def uninstall_all(self) -> List[Tuple[str, bool, str]]:
        self.down()
        return self.uninstall(list(COMPONENTS))

    def purge_logs(self) -> Tuple[int, int]:
        """清空日志目录下的所有日志文件，返回 (文件数, 释放字节数)。"""
        logs_dir = self.config.logs_dir
        files = 0
        freed = 0
        if not logs_dir.exists():
            return files, freed
        for path in sorted(logs_dir.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                freed += path.stat().st_size
                with path.open("w"):
                    pass
                files += 1
            except OSError as exc:  # noqa: BLE001
                self.log.warn(f"清空日志失败 {path}: {exc}")
        self._reopen_logs()
        return files, freed

    def _reopen_logs(self) -> None:
        """通知运行中的服务重新打开日志，避免持续写入产生稀疏文件。"""
        import os
        import signal

        from core.database import MySQLClient, RedisClient
        from providers.mysql import MySQLProvider
        from providers.nginx import NginxProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        try:
            nginx = NginxProvider()
            if nginx.running():
                shell.run(
                    [nginx.binary(), "-s", "reopen", "-c", str(self.config.nginx_conf), "-p", str(self.config.home)],
                    quiet=True,
                    timeout=30,
                )
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"nginx 日志 reopen 失败: {exc}")

        try:
            php = PHPProvider()
            for version in php.installed_versions():
                if not php.fpm_running(version):
                    continue
                pid = system.read_pid(self.config.php_fpm_pid(version))
                if pid:
                    os.kill(pid, signal.SIGUSR1)
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"php-fpm 日志 reopen 失败: {exc}")

        try:
            mysql = MySQLProvider()
            active = mysql.active_version()
            if active:
                MySQLClient().execute(active, "FLUSH LOGS")
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"mysql 日志 flush 失败: {exc}")

        try:
            redis = RedisProvider()
            if redis.running():
                RedisClient().execute("CONFIG", "SET", "logfile", str(self.config.logs_dir / "redis" / "redis.log"))
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"redis 日志 reopen 失败: {exc}")

    def purge_data(self) -> None:
        """清空 MySQL 与 Redis 数据（保留已安装软件）。"""
        import shutil

        self.down(["mysql", "redis"])
        for name in ("mysql", "redis"):
            path = self.config.data_dir / name
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)

    def purge_config(self) -> None:
        """删除生成的配置（保留 .env、manager/ 与项目源码）。"""
        import shutil

        self.down()
        for name in ("nginx", "php", "mysql", "redis", "projects"):
            shutil.rmtree(self.config.config_dir / name, ignore_errors=True)
        environment_json = self.config.config_dir / "environment.json"
        if environment_json.exists():
            environment_json.unlink()

    def purge_state(self) -> None:
        """清空管理器状态文件（安装记录、服务记录、版本记录）。"""
        for path in self.config.state_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def purge_backups(self) -> None:
        """删除所有备份。"""
        import shutil

        shutil.rmtree(self.config.home / "backups", ignore_errors=True)

    def purge(self, targets: List[str]) -> List[Tuple[str, bool, str]]:
        """按目标选择性清理。"""
        results: List[Tuple[str, bool, str]] = []
        for target in targets:
            try:
                if target == "logs":
                    files, freed = self.purge_logs()
                    results.append(("logs", True, f"已清空 {files} 个文件，释放 {freed / 1048576:.1f} MB"))
                elif target == "data":
                    self.purge_data()
                    results.append(("data", True, "MySQL/Redis 数据已清空"))
                elif target == "config":
                    self.purge_config()
                    results.append(("config", True, "生成的配置已删除，下次启动会重新生成"))
                elif target == "state":
                    self.purge_state()
                    results.append(("state", True, "状态记录已清空"))
                elif target == "backups":
                    self.purge_backups()
                    results.append(("backups", True, "备份已删除"))
                elif target == "all":
                    self.purge_all()
                    results.append(("all", True, "环境已彻底清理"))
                else:
                    results.append((target, False, "未知清理目标"))
            except Exception as exc:  # noqa: BLE001
                results.append((target, False, str(exc)))
        return results

    def purge_all(self) -> None:
        import shutil

        from providers.mysql import MySQLProvider
        from providers.redis import RedisProvider

        mysql = MySQLProvider()
        for version in mysql.installed_versions():
            try:
                mysql.purge(version)
            except Exception as exc:  # noqa: BLE001
                self.log.warn(f"mysql purge {version}: {exc}")
        redis = RedisProvider()
        if redis.is_installed():
            try:
                redis.purge()
            except Exception as exc:  # noqa: BLE001
                self.log.warn(f"redis purge: {exc}")
        self.uninstall_all()
        for label_file in self.config.launch_agents_dir.glob("com.devenv.*.plist"):
            try:
                shell.run(["launchctl", "bootout", f"gui/{system.uid()}/{label_file.stem}"], quiet=True, timeout=30)
            except Exception:  # noqa: BLE001
                pass
            label_file.unlink(missing_ok=True)
        for name in ("data", "logs", "run", "state", "backups"):
            shutil.rmtree(self.config.home / name, ignore_errors=True)
        for name in ("nginx", "php", "mysql", "redis", "projects"):
            shutil.rmtree(self.config.config_dir / name, ignore_errors=True)
        environment_json = self.config.config_dir / "environment.json"
        if environment_json.exists():
            environment_json.unlink()
        print("开发环境已彻底清理（.env、manager/ 与项目源码保留）")

    # ------------------------------------------------------------------ 启用/禁用
    def set_enabled(self, name: str, enabled: bool, version: Optional[str] = None) -> None:
        if name == "php":
            from providers.php import PHPProvider

            provider = PHPProvider()
            versions = self.config.get_list("PHP_FPM_ENABLED_VERSIONS")
            target = version or provider.current_cli() or self.config.get("PHP_DEFAULT_VERSION", "8.3")
            if enabled:
                if target not in versions:
                    versions.append(target)
            else:
                versions = [item for item in versions if item != target]
            self.config.set_env("PHP_FPM_ENABLED_VERSIONS", ",".join(versions))
            self.state.save_services({**self.state.services(), **{
                "php": {v: {"enabled": v in versions} for v in provider.installed_versions()}
            }})
            print(f"PHP-FPM {target} 已{'纳入' if enabled else '移出'}全局启动")
            return
        key_map = {"nginx": "NGINX_ENABLED", "mysql": "MYSQL_ENABLED", "redis": "REDIS_ENABLED"}
        if name not in key_map:
            raise ValueError(f"不支持的服务: {name}")
        self.config.set_env(key_map[name], "true" if enabled else "false")
        services = self.state.services()
        services.setdefault(name, {})["enabled"] = enabled
        self.state.save_services(services)
        print(f"{name} 已{'启用' if enabled else '禁用'}（不会立即启动/卸载）")

    # ------------------------------------------------------------------ 信息
    def info(self) -> Dict[str, str]:
        from core.project import ProjectManager
        from providers.composer import ComposerProvider
        from providers.mysql import MySQLProvider
        from providers.node import NodeProvider
        from providers.php import PHPProvider
        from providers.redis import RedisProvider

        php = PHPProvider()
        mysql = MySQLProvider()
        node = NodeProvider()
        composer = ComposerProvider()
        redis = RedisProvider()
        return {
            "DEV_HOME": str(self.config.home),
            "PROJECTS_HOME": str(self.config.projects_home),
            "配置文件": str(self.config.env_path),
            "PHP 已安装": ", ".join(php.installed_versions()) or "无",
            "PHP 默认": php.current_cli() or "-",
            "PHP-FPM 启用": ", ".join(self.config.get_list("PHP_FPM_ENABLED_VERSIONS")) or "无",
            "MySQL 已安装": ", ".join(mysql.installed_versions()) or "无",
            "MySQL 当前": mysql.active_version() or mysql.current_version(),
            "Redis": "已安装" if redis.is_installed() else "未安装",
            "Node 默认": node.current(),
            "Composer": composer.version() if composer.is_installed() else "未安装",
            "项目数": str(len(ProjectManager().projects())),
            "MySQL 端口": str(self.config.get_int("MYSQL_PORT")),
            "Redis 端口": str(self.config.get_int("REDIS_PORT")),
            "Nginx 端口": str(self.config.get_int("NGINX_HTTP_PORT")),
        }
