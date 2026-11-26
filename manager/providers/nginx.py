"""Nginx Provider：安装、配置生成、启停、测试、重载。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from core import installer
from core.service import ServiceSpec
from providers.base import Provider
from utils import shell
from utils.filesystem import ensure_dir, write_text

BASE_CONF = """# Managed by dev - 由管理器生成，请勿手工修改（修改请用 dev config / dev project）
worker_processes auto;
worker_rlimit_nofile 4096;
pid {pid};

error_log {error_log} warn;

events {{
    worker_connections 1024;
    multi_accept on;
}}

http {{
    default_type application/octet-stream;
    charset utf-8;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" rt=$request_time';

    access_log {access_log} main;

    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    server_tokens off;
    client_max_body_size 100m;
    client_body_temp_path {run}/client_body_temp;
    proxy_temp_path {run}/proxy_temp;
    fastcgi_temp_path {run}/fastcgi_temp;
    uwsgi_temp_path {run}/uwsgi_temp;
    scgi_temp_path {run}/scgi_temp;

{mime}
    include {projects}/*.conf;
}}
"""


class NginxProvider(Provider):
    name = "nginx"

    def binary(self) -> str:
        prefix = installer.keg_prefix("nginx")
        if prefix:
            candidate = Path(prefix) / "bin" / "nginx"
            if candidate.exists():
                return str(candidate)
        return "nginx"

    def is_installed(self) -> bool:
        return installer.is_installed("nginx") and Path(self.binary()).exists()

    def install(self) -> None:
        installer.install("nginx")
        self.write_conf()
        self.state.mark_installed("nginx")
        print("Nginx 安装完成")

    def uninstall(self) -> None:
        self.services.remove(self.spec())
        installer.uninstall("nginx")
        self.state.mark_uninstalled("nginx")
        print("Nginx 已卸载（配置与日志保留）")

    # ------------------------------------------------------------------ 配置
    def write_conf(self) -> Path:
        config = self.config
        run = config.run_dir / "nginx"
        logs = config.logs_dir / "nginx"
        ensure_dir(run)
        ensure_dir(logs)
        ensure_dir(config.nginx_projects_dir)
        for name in ("client_body_temp", "proxy_temp", "fastcgi_temp", "uwsgi_temp", "scgi_temp"):
            ensure_dir(run / name)

        mime_path = Path(self.brew_prefix) / "etc" / "nginx" / "mime.types"
        mime = f"    include {mime_path};" if mime_path.exists() else ""

        content = BASE_CONF.format(
            pid=run / "nginx.pid",
            error_log=logs / "error.log",
            access_log=logs / "access.log",
            run=run,
            projects=config.nginx_projects_dir,
            mime=mime,
        )
        # 若已存在非管理器生成的自定义配置，先备份
        write_text(config.nginx_conf, content)
        return config.nginx_conf

    def current_conf_has_projects(self) -> List[str]:
        if not self.config.nginx_projects_dir.exists():
            return []
        return sorted(item.name for item in self.config.nginx_projects_dir.glob("*.conf"))

    def ensure_http_server(self) -> None:
        """没有项目时也提供一个默认欢迎页，避免 8080 无响应。"""
        default = self.config.nginx_projects_dir / "000-default.conf"
        if any(self.config.nginx_projects_dir.glob("*.conf")):
            return
        write_text(
            default,
            f"""# Managed by dev - 默认页面
server {{
    listen {self.config.get_int('NGINX_HTTP_PORT', 8080)};
    server_name localhost 127.0.0.1;
    root {self.config.home / 'run' / 'nginx' / 'www'};
    index index.html;

    location / {{
        try_files $uri $uri/ =404;
    }}

    location = /health {{
        access_log off;
        return 200 "ok\\n";
    }}
}}
""",
        )
        www = self.config.run_dir / "nginx" / "www"
        ensure_dir(www)
        index = www / "index.html"
        if not index.exists():
            write_text(
                index,
                "<!doctype html><meta charset='utf-8'><title>DevEnvironment</title>"
                "<h1>DevEnvironment</h1><p>Nginx 已运行，添加项目后访问对应域名。</p>",
            )

    # ------------------------------------------------------------------ 生命周期
    def spec(self) -> ServiceSpec:
        return ServiceSpec(
            name="nginx",
            label="com.devenv.nginx",
            args=[self.binary(), "-c", str(self.config.nginx_conf), "-p", str(self.config.home), "-g", "daemon off;"],
            log_path=self.config.logs_dir / "nginx" / "launchd.out.log",
            pid_file=self.config.run_dir / "nginx" / "nginx.pid",
            port=self.config.get_int("NGINX_HTTP_PORT", 8080),
            display="nginx",
        )

    def start(self) -> None:
        if not self.is_installed():
            raise RuntimeError("Nginx 未安装，请先执行: dev nginx install")
        self.write_conf()
        self.ensure_http_server()
        if not self.test(verbose=False):
            raise RuntimeError("Nginx 配置检查失败，请执行 dev nginx test 查看详情")
        self.services.start(self.spec())
        print(f"Nginx 已启动: http://127.0.0.1:{self.config.get_int('NGINX_HTTP_PORT', 8080)}")

    def stop(self) -> None:
        self.services.stop(self.spec())
        print("Nginx 已停止")

    def restart(self) -> None:
        self.stop()
        self.start()

    def reload(self) -> bool:
        self.write_conf()
        if not self.test(verbose=False):
            return False
        result = shell.run([self.binary(), "-s", "reload", "-c", str(self.config.nginx_conf), "-p", str(self.config.home)], quiet=True, timeout=60)
        if not result.ok:
            raise RuntimeError(f"Nginx reload 失败: {result.brief()}")
        print("Nginx 已重载配置")
        return True

    def test(self, verbose: bool = True) -> bool:
        self.write_conf()
        result = shell.run(
            [self.binary(), "-t", "-c", str(self.config.nginx_conf), "-p", str(self.config.home)],
            quiet=True,
            timeout=60,
        )
        if verbose:
            print(result.stdout or result.stderr)
        return result.ok

    def running(self) -> bool:
        return self.services.is_running(self.spec())
