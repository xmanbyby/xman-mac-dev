"""PHP 多版本 Provider：安装、CLI 切换、PHP-FPM、扩展。"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
from pathlib import Path
from typing import Dict, List, Optional

from core import installer
from core.service import ServiceSpec
from providers.base import Provider
from utils import shell, system
from utils.filesystem import PHP_VERSIONS, ensure_dir, read_text, write_text

TAP = "shivammathur/php"

PECL_EXTENSIONS = [
    "igbinary",
    "imagick",
    "memcached",
    "msgpack",
    "redis",
    "swoole",
    "xdebug",
    "xlswriter",
]
DEFAULT_DISABLED = {"xdebug"}
ZEND_EXTENSIONS = {"xdebug"}

# 由扩展 tap / pecl 提供的 so 名称
SO_NAMES = {
    "igbinary": "igbinary.so",
    "imagick": "imagick.so",
    "memcached": "memcached.so",
    "msgpack": "msgpack.so",
    "redis": "redis.so",
    "swoole": "swoole.so",
    "xdebug": "xdebug.so",
    "xlswriter": "xlswriter.so",
}

INI_TEMPLATE = """; Managed by dev. 该文件由管理器生成，可继续修改。
[PHP]
engine = On
short_open_tag = Off
precision = 14
output_buffering = 4096
zlib.output_compression = Off
implicit_flush = Off
serialize_precision = -1
max_execution_time = 120
max_input_time = 120
memory_limit = 512M
error_reporting = E_ALL
display_errors = On
display_startup_errors = On
log_errors = On
report_memleaks = On
post_max_size = 64M
upload_max_filesize = 64M
max_file_uploads = 20
default_socket_timeout = 60
date.timezone = Asia/Shanghai
expose_php = Off

[Session]
session.save_handler = files
session.use_strict_mode = 1
session.use_cookies = 1
session.cookie_httponly = 1
session.gc_maxlifetime = 1440

[opcache]
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = 128
opcache.interned_strings_buffer = 16
opcache.max_accelerated_files = 20000
opcache.validate_timestamps = 1
opcache.revalidate_freq = 2
"""


class PHPProvider(Provider):
    name = "php"

    # ------------------------------------------------------------------ 路径
    def formula(self, version: str) -> str:
        """优先使用 homebrew-core 的 php@X.Y；不可用时回退到 shivammathur/php。"""
        core = f"php@{version}"
        if installer.formula_exists(core):
            return core
        return f"{TAP}/php@{version}"

    def keg(self, version: str) -> Optional[Path]:
        prefix = installer.keg_prefix(self.formula(version))
        return Path(prefix) if prefix else None

    def cli_binary(self, version: str) -> Optional[Path]:
        keg = self.keg(version)
        if not keg:
            return None
        candidate = keg / "bin" / "php"
        return candidate if candidate.exists() else None

    def fpm_binary(self, version: str) -> Optional[Path]:
        keg = self.keg(version)
        if not keg:
            return None
        for rel in ("sbin/php-fpm", "bin/php-fpm"):
            candidate = keg / rel
            if candidate.exists():
                return candidate
        return None

    def wrapper_path(self, version: str) -> Path:
        return self.config.home / "bin" / f"php{version}"

    def is_installed(self, version: str) -> bool:
        return installer.is_installed(self.formula(version)) and self.cli_binary(version) is not None

    def installed_versions(self) -> List[str]:
        return [version for version in PHP_VERSIONS if self.is_installed(version)]

    # ------------------------------------------------------------------ 安装
    def install(self, version: str) -> None:
        if version not in PHP_VERSIONS:
            raise ValueError(f"不支持的 PHP 版本: {version}")
        if self.is_installed(version):
            print(f"PHP {version} 已安装，跳过")
            self._prepare_config(version)
            return
        formula = self.formula(version)
        tap_name = TAP if formula.startswith(TAP) else None
        installer.install(formula, tap_name=tap_name)
        self._prepare_config(version)
        self._seed_conf_d(version)
        self.state.mark_installed("php", version)
        versions = self.state.versions()
        if not versions.get("php_cli"):
            self.switch_cli(version)
        print(f"PHP {version} 安装完成")

    def uninstall(self, version: str) -> None:
        self.stop_fpm(version)
        self.services.remove(self.fpm_spec(version))
        installer.uninstall(self.formula(version))
        self.state.mark_uninstalled("php", version)
        self._remove_wrapper(version)
        print(f"PHP {version} 已卸载（配置与日志保留）")

    def _prepare_config(self, version: str) -> None:
        config = self.config
        ensure_dir(config.php_conf_d(version))
        ensure_dir(config.logs_dir / "php" / version)
        ini = config.php_ini(version)
        if not ini.exists() or not read_text(ini).strip():
            keg = self.keg(version)
            candidates = []
            if keg:
                candidates.append(keg / "etc" / "php" / version / "php.ini")
                candidates.append(keg / "etc" / "php.ini")
            candidates.append(Path(self.brew_prefix) / "etc" / "php" / version / "php.ini")
            source = next((item for item in candidates if item.exists()), None)
            if source:
                content = source.read_text(encoding="utf-8", errors="replace")
                write_text(ini, f"; Managed by dev (base: {source})\n{content}")
            else:
                write_text(ini, INI_TEMPLATE)
        self._write_wrapper(version)
        self.write_fpm_config(version)

    def _seed_conf_d(self, version: str) -> None:
        keg = self.keg(version)
        sources = []
        if keg:
            sources.append(keg / "etc" / "php" / version / "conf.d")
        sources.append(Path(self.brew_prefix) / "etc" / "php" / version / "conf.d")
        for source in sources:
            if not source.is_dir():
                continue
            for item in source.glob("*.ini"):
                target = self.config.php_conf_d(version) / item.name
                if not target.exists():
                    shutil.copy2(item, target)
        # 确保 extension_dir 正确（不同 PHP 版本 ABI 目录不同）
        ext_dir = self._extension_dir(version)
        if ext_dir:
            ini = self.config.php_ini(version)
            text = read_text(ini)
            if "extension_dir" in text:
                text = re.sub(r"^\s*;?\s*extension_dir\s*=.*$", f'extension_dir = "{ext_dir}"',
                              text, flags=re.MULTILINE)
            else:
                text += f'\nextension_dir = "{ext_dir}"\n'
            write_text(ini, text)

    def _extension_dir(self, version: str) -> str:
        binary = self.cli_binary(version)
        if not binary:
            return ""
        result = shell.run([str(binary), "-n", "-r", 'echo ini_get("extension_dir");'], quiet=True, timeout=30)
        if result.ok:
            value = result.stdout.strip()
            if value and Path(value).exists():
                return value
        keg = self.keg(version)
        if keg:
            for candidate in sorted((keg / "lib" / "php" / "pecl").glob("*"), reverse=True):
                if candidate.is_dir():
                    return str(candidate)
        return ""

    def _write_wrapper(self, version: str) -> None:
        binary = self.cli_binary(version)
        if not binary:
            return
        path = self.wrapper_path(version)
        content = (
            "#!/bin/sh\n"
            f'export PHP_INI_SCAN_DIR="{self.config.php_conf_d(version)}"\n'
            f'exec "{binary}" -c "{self.config.php_ini(version)}" "$@"\n'
        )
        write_text(path, content, mode=0o755)
        default = self.config.home / "bin" / "php"
        if not default.exists() or default.is_symlink():
            self._link_default(version)

    def _link_default(self, version: str) -> None:
        default = self.config.home / "bin" / "php"
        target = self.wrapper_path(version)
        try:
            if default.is_symlink() or default.exists():
                default.unlink()
            default.symlink_to(target)
        except OSError as exc:
            self.log.warn(f"symlink {default} 失败: {exc}")

    def _remove_wrapper(self, version: str) -> None:
        path = self.wrapper_path(version)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ CLI
    def switch_cli(self, version: str) -> None:
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} 未安装，请先执行: dev php install {version}")
        self._link_default(version)
        self.state.set_version("php_cli", version)
        print(f"PHP CLI 默认版本已切换为 {version}")
        bin_dir = str(self.config.home / "bin")
        if bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
            print(
                f"注意: {bin_dir} 不在 PATH 中，终端直接执行 php 仍会命中 Homebrew 版本。\n"
                f"请在 ~/.zshrc 中加入: export PATH=\"{bin_dir}:$PATH\" 并重开终端。"
            )

    def current_cli(self) -> Optional[str]:
        stored = self.state.versions().get("php_cli")
        if stored and self.is_installed(stored):
            return stored
        for version in self.installed_versions():
            return version
        return None

    def run(self, version: str, args: List[str]) -> int:
        binary = self.cli_binary(version)
        if not binary:
            raise RuntimeError(f"PHP {version} 未安装")
        result = shell.run(
            [str(binary), "-c", str(self.config.php_ini(version))] + args,
            env={"PHP_INI_SCAN_DIR": str(self.config.php_conf_d(version))},
            timeout=1800,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        return result.returncode

    def version_string(self, version: str) -> str:
        return shell.output(
            [str(self.cli_binary(version)), "-c", str(self.config.php_ini(version)), "-r", 'echo PHP_VERSION;'],
            env={"PHP_INI_SCAN_DIR": str(self.config.php_conf_d(version))},
        )

    # ------------------------------------------------------------------ FPM
    def write_fpm_config(self, version: str) -> None:
        config = self.config
        ensure_dir(config.run_dir / "php")
        socket = config.php_socket(version)
        pid = config.php_fpm_pid(version)
        log_dir = config.logs_dir / "php" / version
        ensure_dir(log_dir)
        body = f"""; Managed by dev. 由管理器生成。
[global]
pid = {pid}
error_log = {log_dir / 'php-fpm-error.log'}
daemonize = no
log_level = notice
emergency_restart_threshold = 10
emergency_restart_interval = 1m
process_control_timeout = 10s

[www]
user = {system.username()}
group = {system.group_name()}
listen = {socket}
listen.mode = 0660
listen.allowed_clients = 127.0.0.1
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 4
pm.max_requests = 500
request_terminate_timeout = 300s
request_slowlog_timeout = 10s
slowlog = {log_dir / 'php-fpm-slow.log'}
catch_workers_output = yes
decorate_workers_output = no
clear_env = no
php_admin_value[error_log] = {log_dir / 'php-error.log'}
php_admin_flag[log_errors] = on
"""
        write_text(config.php_fpm_conf(version), body)

    def fpm_spec(self, version: str) -> ServiceSpec:
        binary = self.fpm_binary(version)
        return ServiceSpec(
            name=f"php-fpm-{version}",
            label=f"com.devenv.php-fpm.{version}",
            args=[
                str(binary or f"php-fpm@{version}"),
                "--nodaemonize",
                "--fpm-config",
                str(self.config.php_fpm_conf(version)),
                "-c",
                str(self.config.php_ini(version)),
            ],
            log_path=self.config.logs_dir / "php" / version / "php-fpm.log",
            pid_file=self.config.php_fpm_pid(version),
            socket=self.config.php_socket(version),
            env={"PHP_INI_SCAN_DIR": str(self.config.php_conf_d(version))},
            display=f"php-fpm {version}",
        )

    def start_fpm(self, version: str) -> None:
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} 未安装")
        self.write_fpm_config(version)
        self.services.start(self.fpm_spec(version))
        print(f"php-fpm {version} 已启动 -> {self.config.php_socket(version)}")

    def stop_fpm(self, version: str) -> None:
        self.services.stop(self.fpm_spec(version))
        print(f"php-fpm {version} 已停止")

    def restart_fpm(self, version: str) -> None:
        self.write_fpm_config(version)
        self.services.restart(self.fpm_spec(version))
        print(f"php-fpm {version} 已重启")

    def fpm_running(self, version: str) -> bool:
        return self.services.is_running(self.fpm_spec(version))

    def enabled_fpm_versions(self) -> List[str]:
        enabled = [v for v in self.config.get_list("PHP_FPM_ENABLED_VERSIONS") if self.is_installed(v)]
        if enabled:
            return enabled
        current = self.current_cli()
        return [current] if current else []

    # ------------------------------------------------------------------ 扩展
    def module_list(self, version: str) -> List[str]:
        binary = self.cli_binary(version)
        if not binary:
            return []
        result = shell.run(
            [str(binary), "-c", str(self.config.php_ini(version)), "-m"],
            env={"PHP_INI_SCAN_DIR": str(self.config.php_conf_d(version))},
            quiet=True,
        )
        modules = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("[") and line != "Module" and not line.startswith("PHP Modules"):
                modules.append(line)
        return modules

    def _ext_ini(self, version: str, ext: str) -> Path:
        return self.config.php_conf_d(version) / f"{ext}.ini"

    def ext_enabled(self, version: str, ext: str) -> bool:
        return self._ext_ini(version, ext).exists()

    def ext_install(self, version: str, ext: str) -> bool:
        if not self.is_installed(version):
            raise RuntimeError(f"PHP {version} 未安装")
        if ext in self.module_list(version) and self.ext_enabled(version, ext):
            print(f"扩展 {ext} 已在 PHP {version} 中启用")
            return True

        installed = False
        # 升级/重装前先卸载加载项，避免 pecl 报 "already loaded"
        self._strip_ini_extension(version, ext)
        ext_ini = self._ext_ini(version, ext)
        if ext_ini.exists():
            ext_ini.replace(ext_ini.with_suffix(".ini.disabled"))
        try:
            installed = self._pecl_install(version, ext)
        finally:
            self._strip_ini_extension(version, ext)
        if not installed:
            raise RuntimeError(
                f"扩展 {ext} 编译安装失败（可能暂不支持 PHP {version}），"
                f"详见 logs/manager/pecl-{ext}-{version}.log"
            )

        # pecl 会自行写入 php.ini，这里统一改为由 conf.d 管理，避免重复加载
        self._strip_ini_extension(version, ext)
        self.ext_enable(version, ext, verify=False)
        modules = self.module_list(version)
        if ext not in modules:
            self.log.warn(f"扩展 {ext} 已安装但未出现在 php -m，请执行 dev ext doctor --php={version}")
            return False
        print(f"扩展 {ext} 已安装并启用 (PHP {version})")
        return True

    def _strip_ini_extension(self, version: str, ext: str) -> None:
        ini = self.config.php_ini(version)
        if not ini.exists():
            return
        pattern = re.compile(
            rf"^\s*(?:zend_)?extension\s*=\s*[\"']?{re.escape(ext)}\.so[\"']?\s*$",
            re.IGNORECASE,
        )
        lines = ini.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = [line for line in lines if not pattern.match(line)]
        if len(kept) != len(lines):
            write_text(ini, "\n".join(kept) + "\n")

    def _pecl_install(self, version: str, ext: str) -> bool:
        keg = self.keg(version)
        if not keg:
            return False
        pecl = keg / "bin" / "pecl"
        if not pecl.exists():
            return False
        log_path = self.config.logs_dir / "manager" / f"pecl-{ext}-{version}.log"
        ensure_dir(log_path.parent)
        env = {
            "PATH": f"{keg}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PHP_PEAR_PHP_BIN": str(keg / "bin" / "php"),
            "PHP_INI_SCAN_DIR": str(self.config.php_conf_d(version)),
            "CPPFLAGS": f"-I{self.brew_prefix}/include",
            "LDFLAGS": f"-L{self.brew_prefix}/lib",
            "PKG_CONFIG_PATH": f"{self.brew_prefix}/lib/pkgconfig",
        }
        # pecl 会用 PHP_PEAR_PHP_BIN 启动 PHP，通过 wrapper 强制使用本管理器的 php.ini，
        # 避免读取 Homebrew 全局 php.ini 导致扩展重复加载。
        wrapper = self.config.run_dir / "php" / f"pecl-php{version.replace('.', '')}.sh"
        write_text(
            wrapper,
            f'#!/bin/sh\nexec "{keg / "bin" / "php"}" -c "{self.config.php_ini(version)}" "$@"\n',
            mode=0o755,
        )
        env["PHP_PEAR_PHP_BIN"] = str(wrapper)
        answers = "/opt/homebrew\n\n\n\n" if ext in ("imagick", "memcached") else ""
        try:
            result = shell.run(
                [str(pecl), "install", "-f", ext],
                env=env,
                quiet=True,
                timeout=1800,
                input_text=answers,
            )
        finally:
            try:
                wrapper.unlink(missing_ok=True)
            except OSError:
                pass
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(result.stdout + "\n" + result.stderr)
        return result.ok

    def ext_enable(self, version: str, ext: str, verify: bool = True) -> None:
        ini = self._ext_ini(version, ext)
        disabled = ini.with_suffix(".ini.disabled")
        if disabled.exists():
            disabled.replace(ini)
            if verify:
                print(f"扩展 {ext} 已启用 (PHP {version})")
            return
        if ini.exists():
            if verify:
                print(f"扩展 {ext} 已处于启用状态")
            return
        so = SO_NAMES.get(ext, f"{ext}.so")
        directive = "zend_extension" if ext in ZEND_EXTENSIONS else "extension"
        write_text(ini, f"; Managed by dev\n{directive}={so}\n")
        if verify:
            print(f"扩展 {ext} 已启用 (PHP {version})")

    def ext_disable(self, version: str, ext: str) -> None:
        ini = self._ext_ini(version, ext)
        if not ini.exists():
            print(f"扩展 {ext} 未启用")
            return
        ini.replace(ini.with_suffix(".ini.disabled"))
        print(f"扩展 {ext} 已停用 (PHP {version})，PHP-FPM 需重启后生效")

    def ext_uninstall(self, version: str, ext: str) -> None:
        for candidate in (self._ext_ini(version, ext), self._ext_ini(version, ext).with_suffix(".ini.disabled")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        if installer.is_installed(f"{ext}@{version}"):
            installer.uninstall(f"{ext}@{version}")
        keg = self.keg(version)
        if keg:
            pecl = keg / "bin" / "pecl"
            if pecl.exists():
                shell.run([str(pecl), "uninstall", ext], quiet=True, timeout=300)
        print(f"扩展 {ext} 已从 PHP {version} 卸载")

    def install_default_extensions(self, version: str) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for ext in PECL_EXTENSIONS:
            try:
                ok = self.ext_install(version, ext)
                if ext in DEFAULT_DISABLED:
                    self.ext_disable(version, ext)
                results[ext] = "ok" if ok else "已安装未生效"
            except Exception as exc:  # noqa: BLE001 - 单个扩展失败不影响其他扩展
                results[ext] = f"失败: {exc}"
        return results

    # ------------------------------------------------------------------ 信息
    def info(self, version: str) -> Dict[str, str]:
        binary = self.cli_binary(version)
        return {
            "版本": self.version_string(version) if binary else "-",
            "安装路径": str(self.keg(version) or "-"),
            "php.ini": str(self.config.php_ini(version)),
            "conf.d": str(self.config.php_conf_d(version)),
            "FPM Socket": str(self.config.php_socket(version)),
            "FPM 状态": "running" if self.fpm_running(version) else "stopped",
            "扩展数": str(len(self.module_list(version))),
        }
