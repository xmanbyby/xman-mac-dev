"""Redis Provider：安装、持久化配置、启停、密码与 ACL 用户。"""
from __future__ import annotations

import secrets
from typing import Dict, List, Optional

from core import installer
from core.database import RedisClient
from core.service import ServiceSpec
from providers.base import Provider
from utils import security, system
from utils.filesystem import ensure_dir, write_text

REDIS_CONF = """# Managed by dev - 由管理器生成
bind {host}
protected-mode yes
port {port}
tcp-backlog 511
timeout 0
tcp-keepalive 300

daemonize no
supervised no
pidfile {pid}
loglevel notice
logfile {logfile}
databases 16

always-show-logo no
set-proc-title yes
proc-title-template "{{title}} {{listen-addr}}"

save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir {datadir}

appendonly yes
appendfilename "appendonly.aof"
appenddirname "appendonlydir"
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

maxmemory 512mb
maxmemory-policy allkeys-lru
{requirepass}
"""


class RedisProvider(Provider):
    name = "redis"

    def binary(self) -> str:
        prefix = installer.keg_prefix("redis")
        if prefix:
            candidate = prefix + "/bin/redis-server"
            return candidate
        return "redis-server"

    def is_installed(self) -> bool:
        return installer.is_installed("redis") and system.find_binary("redis-server", [str(self.brew_prefix) + "/bin"]) is not None

    def install(self) -> None:
        if self.is_installed():
            print("Redis 已安装，跳过")
            self.write_conf()
            return
        installer.install("redis")
        self.write_conf()
        self.state.mark_installed("redis")
        print("Redis 安装完成")

    def uninstall(self) -> None:
        self.stop()
        self.services.remove(self.spec())
        installer.uninstall("redis")
        self.state.mark_uninstalled("redis")
        print("Redis 已卸载（RDB/AOF 与配置保留）")

    def purge(self) -> None:
        self.stop()
        self.services.remove(self.spec())
        installer.uninstall("redis")
        self.state.mark_uninstalled("redis")
        import shutil

        data = self.config.data_dir / "redis"
        if data.exists():
            shutil.rmtree(data)
        print("Redis 已彻底清理（含数据文件）")

    # ------------------------------------------------------------------ 配置
    def write_conf(self) -> None:
        password = security.keychain_get("redis.default")
        requirepass = f"requirepass {password}" if password else "# requirepass 未设置（dev redis password init 可设置）"
        ensure_dir(self.config.redis_data_dir())
        ensure_dir(self.config.logs_dir / "redis")
        ensure_dir(self.config.run_dir / "redis")
        body = REDIS_CONF.format(
            host=self.config.get("REDIS_HOST", "127.0.0.1"),
            port=self.config.get_int("REDIS_PORT", 6380),
            pid=self.config.redis_pid(),
            logfile=self.config.logs_dir / "redis" / "redis.log",
            datadir=self.config.redis_data_dir(),
            requirepass=requirepass,
        )
        write_text(self.config.redis_conf, body)

    def spec(self) -> ServiceSpec:
        return ServiceSpec(
            name="redis",
            label="com.devenv.redis",
            args=[self.binary(), str(self.config.redis_conf)],
            log_path=self.config.logs_dir / "redis" / "launchd.out.log",
            pid_file=self.config.redis_pid(),
            port=self.config.get_int("REDIS_PORT", 6380),
            display="redis",
        )

    def running(self) -> bool:
        return self.services.is_running(self.spec()) and RedisClient().ping()

    def start(self) -> None:
        if not self.is_installed():
            raise RuntimeError("Redis 未安装，请先执行: dev redis install")
        self.write_conf()
        self.services.start(self.spec(), timeout=30)
        self.state.save_services({**self.state.services(), "redis": {
            "enabled": self.config.get_bool("REDIS_ENABLED", True),
            "port": self.config.get_int("REDIS_PORT", 6380),
        }})
        print(f"Redis 已启动: {self.config.get('REDIS_HOST')}:{self.config.get_int('REDIS_PORT')}")

    def stop(self) -> None:
        self.services.stop(self.spec(), timeout=30)
        print("Redis 已停止")

    def restart(self) -> None:
        self.stop()
        self.start()

    # ------------------------------------------------------------------ 密码/用户
    def init_password(self) -> str:
        password = secrets.token_urlsafe(18)
        security.keychain_set("redis.default", password)
        self.write_conf()
        client = RedisClient()
        if self.running():
            client.run(["CONFIG", "SET", "requirepass", password], password="")
            client.run(["CONFIG", "SET", "requirepass", password], password=password)
            print("Redis 密码已设置并即时生效")
        else:
            print("Redis 密码已写入 Keychain 与配置，启动后生效")
        return password

    def set_password(self, password: str) -> None:
        client = RedisClient()
        current = security.keychain_get("redis.default") or ""
        if self.running():
            result = client.run(["CONFIG", "SET", "requirepass", password], password=current)
            if not result.ok:
                raise RuntimeError(f"设置 Redis 密码失败（当前密码可能不正确）: {result.brief()}")
        security.keychain_set("redis.default", password)
        self.write_conf()
        print("Redis 密码已更新")

    def create_user(self, name: str, password: str) -> None:
        client = RedisClient()
        result = client.run(["ACL", "SETUSER", name, "on", f">{password}", "~*", "+@all"])
        if not result.ok:
            raise RuntimeError(f"创建 Redis 用户失败: {result.brief()}")
        security.keychain_set(f"redis.{name}", password)
        print(f"Redis 用户 {name} 已创建（密码已写入 Keychain: dev.redis.{name}）")

    def set_user_password(self, name: str, password: str) -> None:
        client = RedisClient()
        result = client.run(["ACL", "SETUSER", name, f">{password}"])
        if not result.ok:
            raise RuntimeError(f"修改 Redis 用户密码失败: {result.brief()}")
        security.keychain_set(f"redis.{name}", password)
        print(f"Redis 用户 {name} 密码已更新")

    def list_users(self) -> List[str]:
        try:
            output = RedisClient().run(["ACL", "USERS"]).stdout
        except Exception:  # noqa: BLE001
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def delete_user(self, name: str) -> None:
        RedisClient().run(["ACL", "DELUSER", name])
        security.keychain_delete(f"redis.{name}")
        print(f"Redis 用户 {name} 已删除")

    # ------------------------------------------------------------------ 信息
    def info(self) -> Dict[str, str]:
        client = RedisClient()
        running = self.running()
        info_text = ""
        if running:
            try:
                info_text = client.run(["INFO", "server"]).stdout
            except Exception:  # noqa: BLE001
                info_text = ""
        version = ""
        if "redis_version:" in info_text:
            version = info_text.split("redis_version:")[1].splitlines()[0].strip()
        return {
            "运行状态": "running" if running else "stopped",
            "服务端版本": version or "-",
            "监听": f"{self.config.get('REDIS_HOST')}:{self.config.get_int('REDIS_PORT')}",
            "数据目录": str(self.config.redis_data_dir()),
            "配置文件": str(self.config.redis_conf),
            "密码": "已设置 (Keychain)" if security.keychain_get("redis.default") else "未设置",
            "持久化": "RDB + AOF",
        }
