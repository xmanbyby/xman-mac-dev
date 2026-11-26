"""备份与恢复：配置文件、MySQL、Redis。"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, List, Optional

from core.config import get_config
from core.database import MySQLClient, RedisClient
from utils import shell, system
from utils.filesystem import ensure_dir, read_json, write_json
from utils.log import get_logger


class BackupError(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupManager:
    def __init__(self) -> None:
        self.config = get_config()
        self.log = get_logger()

    # ------------------------------------------------------------------ 配置
    def backup_config(self) -> Path:
        target_dir = self.config.backups_dir / "config"
        ensure_dir(target_dir)
        archive = target_dir / f"devenv-config-{_stamp()}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in (".env",):
                path = self.config.home / name
                if path.exists():
                    tar.add(path, arcname=name)
            for name in ("config", "state"):
                path = self.config.home / name
                if path.exists():
                    tar.add(path, arcname=name)
        write_json(target_dir / f"{archive.stem}.json", {
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "archive": archive.name,
            "sha256": _sha256(archive),
        })
        self.log.info(f"config backup: {archive}")
        print(f"配置备份完成: {archive}")
        return archive

    def restore_config(self, archive: Path) -> None:
        if not archive.exists():
            raise BackupError(f"备份文件不存在: {archive}")
        base = self.config.home
        safe = base.resolve()
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                target = (base / member.name).resolve()
                if not str(target).startswith(str(safe)):
                    raise BackupError(f"备份包含非法路径: {member.name}")
            tar.extractall(base)
        print(f"配置已恢复: {archive}")

    # ------------------------------------------------------------------ MySQL
    def backup_mysql(self, version: Optional[str] = None) -> Path:
        from providers.mysql import MySQLProvider

        provider = MySQLProvider()
        version = version or provider.active_version() or provider.current_version()
        if not provider.running(version):
            raise BackupError(f"MySQL {version} 未运行，无法备份")
        client = MySQLClient()
        binary = client.binary(version, "mysqldump")
        if not binary:
            raise BackupError(f"未找到 MySQL {version} 的 mysqldump")
        target_dir = self.config.backups_dir / "mysql" / _stamp()
        ensure_dir(target_dir)
        dump_file = target_dir / "all-databases.sql"
        cnf = client._cnf(version, "root", client.root_password() or "")
        try:
            with open(dump_file, "wb") as out:
                proc = subprocess.run(
                    [
                        str(binary),
                        f"--defaults-extra-file={cnf}",
                        "--single-transaction",
                        "--routines",
                        "--events",
                        "--triggers",
                        "--all-databases",
                        "--set-gtid-purged=OFF",
                    ],
                    stdout=out,
                    stderr=subprocess.PIPE,
                    timeout=3600,
                )
        finally:
            cnf.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise BackupError(f"mysqldump 失败: {proc.stderr.decode('utf-8', 'replace')[-800:]}")
        databases: List[str] = []
        try:
            databases = client.list_databases(version)
        except Exception:  # noqa: BLE001
            pass
        write_json(target_dir / "metadata.json", {
            "type": "mysql",
            "version": client.server_version(version) or version,
            "config_version": version,
            "databases": databases,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "file": dump_file.name,
            "size": dump_file.stat().st_size,
            "sha256": _sha256(dump_file),
        })
        print(f"MySQL 备份完成: {dump_file}")
        return dump_file

    def restore_mysql(self, dump_file: Path, version: Optional[str] = None) -> None:
        from providers.mysql import MySQLProvider

        if not dump_file.exists():
            raise BackupError(f"备份文件不存在: {dump_file}")
        provider = MySQLProvider()
        version = version or provider.active_version() or provider.current_version()
        if not provider.running(version):
            raise BackupError(f"MySQL {version} 未运行，无法恢复")
        client = MySQLClient()
        binary = client.binary(version, "mysql")
        if not binary:
            raise BackupError("未找到 mysql 客户端")
        cnf = client._cnf(version, "root", client.root_password() or "")
        try:
            result = shell.run(
                ["/bin/sh", "-c", f'"{binary}" --defaults-extra-file="{cnf}" < "{dump_file}"'],
                quiet=True,
                timeout=7200,
            )
        finally:
            cnf.unlink(missing_ok=True)
        if not result.ok:
            raise BackupError(f"恢复 MySQL 失败: {result.brief()}")
        print(f"MySQL 数据已恢复: {dump_file}")

    # ------------------------------------------------------------------ Redis
    def backup_redis(self) -> Path:
        client = RedisClient()
        if not client.ping():
            raise BackupError("Redis 未运行或密码不正确，无法备份")
        client.run(["BGSAVE"])
        import time

        deadline = time.time() + 120
        while time.time() < deadline:
            info = client.run(["INFO", "persistence"]).stdout
            if "rdb_bgsave_in_progress:0" in info:
                break
            time.sleep(0.5)
        target_dir = self.config.backups_dir / "redis" / _stamp()
        ensure_dir(target_dir)
        data_dir = self.config.redis_data_dir()
        copied: List[str] = []
        for name in ("dump.rdb", "appendonlydir"):
            source = data_dir / name
            if not source.exists():
                continue
            destination = target_dir / name
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            copied.append(name)
        if not copied:
            raise BackupError("未找到可备份的 Redis 持久化文件")
        write_json(target_dir / "metadata.json", {
            "type": "redis",
            "version": client.server_version(),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "files": copied,
        })
        print(f"Redis 备份完成: {target_dir}")
        return target_dir

    def restore_redis(self, backup_dir: Path) -> None:
        from providers.redis import RedisProvider

        if not backup_dir.exists():
            raise BackupError(f"备份目录不存在: {backup_dir}")
        provider = RedisProvider()
        provider.stop()
        data_dir = self.config.redis_data_dir()
        ensure_dir(data_dir)
        for name in ("dump.rdb", "appendonlydir"):
            source = backup_dir / name
            target = data_dir / name
            if not source.exists():
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        provider.start()
        print(f"Redis 数据已从备份恢复: {backup_dir}")

    # ------------------------------------------------------------------ 查询
    def list_backups(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for kind in ("config", "mysql", "redis"):
            base = self.config.backups_dir / kind
            if not base.exists():
                continue
            for item in sorted(base.iterdir(), reverse=True):
                if item.name.endswith(".json"):
                    continue
                size = ""
                if item.is_file():
                    size = f"{item.stat().st_size / 1024 / 1024:.1f} MB"
                rows.append({
                    "类型": kind,
                    "名称": item.name,
                    "路径": str(item),
                    "大小": size,
                })
        return rows

    def backup_all(self) -> Dict[str, str]:
        results: Dict[str, str] = {}
        results["config"] = str(self.backup_config())
        from providers.mysql import MySQLProvider

        if MySQLProvider().active_version():
            try:
                results["mysql"] = str(self.backup_mysql())
            except BackupError as exc:
                results["mysql"] = f"失败: {exc}"
        if RedisClient().ping():
            try:
                results["redis"] = str(self.backup_redis())
            except BackupError as exc:
                results["redis"] = f"失败: {exc}"
        return results
