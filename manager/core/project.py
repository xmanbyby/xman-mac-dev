"""项目管理：注册、类型识别、Nginx 配置生成、环境变量同步、启动/停止。"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from core.config import get_config
from core.state import get_state
from utils import security, shell, system
from utils.filesystem import ensure_dir, read_json, read_text, write_json, write_text
from utils.log import get_logger
from utils.validation import valid_domain, valid_name


class ProjectError(RuntimeError):
    pass


NODE_TYPES = {"react", "vue", "node", "vite"}


class ProjectManager:
    def __init__(self) -> None:
        self.config = get_config()
        self.state = get_state()
        self.log = get_logger()

    # ------------------------------------------------------------------ 数据
    def load(self) -> Dict:
        data = read_json(self.config.projects_json, {"projects": []})
        if not isinstance(data, dict):
            data = {"projects": []}
        data.setdefault("projects", [])
        return data

    def save(self, data: Dict) -> None:
        write_json(self.config.projects_json, data)

    def projects(self) -> List[Dict]:
        return self.load().get("projects", [])

    def find(self, name: str) -> Dict:
        for project in self.projects():
            if project.get("name") == name:
                return project
        raise ProjectError(f"项目不存在: {name}")

    # ------------------------------------------------------------------ 工具
    def resolve_path(self, project: Dict) -> Path:
        raw = str(project.get("path", ""))
        raw = raw.replace("${PROJECTS_HOME}", str(self.config.projects_home))
        raw = raw.replace("$PROJECTS_HOME", str(self.config.projects_home))
        return Path(raw).expanduser()

    def detect_type(self, path: Path) -> str:
        if (path / "artisan").exists() and (path / "composer.json").exists():
            return "laravel"
        if (path / "bin" / "console").exists() and (path / "composer.json").exists():
            return "symfony"
        package = read_json(path / "package.json", {})
        if isinstance(package, dict):
            deps = {}
            for key in ("dependencies", "devDependencies"):
                deps.update(package.get(key) or {})
            if "react" in deps:
                return "react"
            if "vue" in deps:
                return "vue"
            if "vite" in deps:
                return "vite"
            if deps:
                return "node"
        if (path / "index.php").exists() or (path / "public" / "index.php").exists():
            return "php"
        if (path / "index.html").exists():
            return "static"
        return "unknown"

    def default_document_root(self, project_type: str) -> str:
        if project_type in ("laravel", "symfony", "php"):
            return "public" if project_type != "php" or (Path("public")).exists() else ""
        return ""

    def nginx_conf_path(self, name: str) -> Path:
        return self.config.nginx_projects_dir / f"{name}.conf"

    # ------------------------------------------------------------------ 命令
    def add(
        self,
        name: str,
        path: Optional[str] = None,
        project_type: Optional[str] = None,
        domain: Optional[str] = None,
        php: Optional[str] = None,
        document_root: Optional[str] = None,
        port: Optional[int] = None,
    ) -> Dict:
        if not valid_name(name):
            raise ProjectError(f"项目名不合法: {name}")
        target = Path(path).expanduser() if path else self.config.projects_home / name
        if not target.exists():
            raise ProjectError(f"项目目录不存在: {target}")
        if any(item.get("name") == name for item in self.projects()):
            raise ProjectError(f"项目已存在: {name}")
        project_type = project_type or self.detect_type(target)
        if project_type == "unknown":
            raise ProjectError("无法自动识别项目类型，请用 --type 指定（laravel/symfony/php/react/vue/vite/node/static）")
        domain = domain or f"{name}.local"
        if not valid_domain(domain):
            raise ProjectError(f"域名不合法: {domain}")
        if any(item.get("domain") == domain for item in self.projects()):
            raise ProjectError(f"域名已被其他项目使用: {domain}")
        php = php or self.config.get("PHP_DEFAULT_VERSION", "8.3")
        if document_root is None:
            candidate = target / "public"
            document_root = "public" if candidate.is_dir() else ""
        project = {
            "name": name,
            "path": str(target),
            "type": project_type,
            "domain": domain,
            "php": php,
            "document_root": document_root,
            "mysql": True,
            "redis": True,
            "enabled": True,
        }
        if project_type in NODE_TYPES:
            project["port"] = port or 5173
        if project_type in ("laravel", "symfony", "php", "static") or project_type in NODE_TYPES:
            self.write_nginx(project)
        data = self.load()
        data["projects"].append(project)
        self.save(data)
        print(f"项目 {name} 已注册（类型 {project_type}，域名 {domain}）")
        self._print_hosts_hint(domain)
        return project

    def remove(self, name: str) -> None:
        project = self.find(name)
        data = self.load()
        data["projects"] = [item for item in data["projects"] if item.get("name") != name]
        self.save(data)
        conf = self.nginx_conf_path(name)
        if conf.exists():
            conf.unlink()
        print(f"项目 {name} 已移除（源码未删除）")

    def info(self, name: str) -> Dict[str, str]:
        project = self.find(name)
        path = self.resolve_path(project)
        hosts_ok = self._hosts_has(project.get("domain", ""))
        return {
            "名称": name,
            "类型": project.get("type", "-"),
            "路径": str(path),
            "存在": "是" if path.exists() else "否",
            "域名": project.get("domain", "-"),
            "PHP": project.get("php", "-"),
            "文档根": project.get("document_root") or "-",
            "Nginx 配置": str(self.nginx_conf_path(name)),
            "hosts 已配置": "是" if hosts_ok else "否",
        }

    def set_php(self, name: str, version: str) -> None:
        data = self.load()
        for project in data["projects"]:
            if project.get("name") == name:
                project["php"] = version
                self.write_nginx(project)
                self.save(data)
                print(f"项目 {name} PHP 版本已设置为 {version}")
                return
        raise ProjectError(f"项目不存在: {name}")

    # ------------------------------------------------------------------ Nginx
    def write_nginx(self, project: Dict) -> Path:
        name = project["name"]
        path = self.resolve_path(project)
        domain = project.get("domain") or f"{name}.local"
        port = self.config.get_int("NGINX_HTTP_PORT", 8080)
        logs = self.config.logs_dir / "nginx"
        ensure_dir(logs)
        ensure_dir(self.config.nginx_projects_dir)
        project_type = project.get("type", "php")
        access_log = logs / f"{name}.access.log"
        error_log = logs / f"{name}.error.log"

        if project_type in NODE_TYPES:
            target_port = project.get("port") or 5173
            body = f"""# Managed by dev - project {name} ({project_type})
server {{
    listen {port};
    server_name {domain};

    access_log {access_log};
    error_log {error_log};

    location / {{
        proxy_pass http://127.0.0.1:{target_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }}
}}
"""
        elif project_type == "static":
            body = f"""# Managed by dev - project {name} (static)
server {{
    listen {port};
    server_name {domain};
    root {path};
    index index.html;

    access_log {access_log};
    error_log {error_log};

    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""
        else:
            root = path / (project.get("document_root") or "")
            php_version = project.get("php") or self.config.get("PHP_DEFAULT_VERSION", "8.3")
            socket = self.config.php_socket(php_version)
            params_file = Path("/opt/homebrew/etc/nginx/fastcgi_params")
            include_line = f"include {params_file};" if params_file.exists() else (
                "fastcgi_param QUERY_STRING $query_string;\n"
                "        fastcgi_param REQUEST_METHOD $request_method;\n"
                "        fastcgi_param CONTENT_TYPE $content_type;\n"
                "        fastcgi_param CONTENT_LENGTH $content_length;\n"
                "        fastcgi_param SCRIPT_NAME $fastcgi_script_name;\n"
                "        fastcgi_param REQUEST_URI $request_uri;\n"
                "        fastcgi_param DOCUMENT_URI $document_uri;\n"
                "        fastcgi_param DOCUMENT_ROOT $document_root;\n"
                "        fastcgi_param SERVER_PROTOCOL $server_protocol;\n"
                "        fastcgi_param REQUEST_SCHEME $scheme;\n"
                "        fastcgi_param HTTPS $https if_not_empty;\n"
                "        fastcgi_param GATEWAY_INTERFACE CGI/1.1;\n"
                "        fastcgi_param SERVER_SOFTWARE nginx/$nginx_version;\n"
                "        fastcgi_param REMOTE_ADDR $remote_addr;\n"
                "        fastcgi_param REMOTE_PORT $remote_port;\n"
                "        fastcgi_param SERVER_ADDR $server_addr;\n"
                "        fastcgi_param SERVER_PORT $server_port;\n"
                "        fastcgi_param SERVER_NAME $server_name;"
            )
            body = f"""# Managed by dev - project {name} ({project_type}, PHP {php_version})
server {{
    listen {port};
    server_name {domain};
    root {root};
    index index.php index.html;
    charset utf-8;
    client_max_body_size 100m;

    access_log {access_log};
    error_log {error_log};

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location = /favicon.ico {{ access_log off; log_not_found off; }}
    location = /robots.txt  {{ access_log off; log_not_found off; }}

    location ~ \\.php$ {{
        fastcgi_pass unix:{socket};
        fastcgi_index index.php;
        fastcgi_split_path_info ^(.+\\.php)(/.+)$;
        {include_line}
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        fastcgi_read_timeout 300s;
    }}

    location ~ /\\.(?!well-known).* {{
        deny all;
    }}
}}
"""
        target = self.nginx_conf_path(name)
        write_text(target, body)
        return target

    def regenerate_all(self) -> None:
        for project in self.projects():
            if project.get("enabled", True):
                self.write_nginx(project)

    def _hosts_has(self, domain: str) -> bool:
        if not domain:
            return False
        try:
            content = Path("/etc/hosts").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(re.search(rf"^\s*127\.0\.0\.1\s+.*\b{re.escape(domain)}\b", content, re.MULTILINE))

    def _print_hosts_hint(self, domain: str) -> None:
        if not self._hosts_has(domain):
            print(
                f"提示: 需要将域名指向本机，可执行:\n"
                f"  echo '127.0.0.1 {domain}' | sudo tee -a /etc/hosts"
            )

    # ------------------------------------------------------------------ 环境同步
    def sync_env(self, name: str) -> None:
        project = self.find(name)
        path = self.resolve_path(project)
        env_file = path / ".env"
        if not env_file.exists():
            raise ProjectError(f"项目 .env 不存在: {env_file}")
        db_name = name.replace("-", "_")
        db_user = name
        db_password = security.keychain_get(f"mysql.{db_user}")
        redis_password = security.keychain_get("redis.default")
        updates = {
            "DB_CONNECTION": "mysql",
            "DB_HOST": self.config.get("MYSQL_HOST", "127.0.0.1"),
            "DB_PORT": str(self.config.get_int("MYSQL_PORT", 3307)),
            "DB_DATABASE": db_name,
            "DB_USERNAME": db_user,
        }
        if db_password:
            updates["DB_PASSWORD"] = db_password
        updates["REDIS_HOST"] = self.config.get("REDIS_HOST", "127.0.0.1")
        updates["REDIS_PORT"] = str(self.config.get_int("REDIS_PORT", 6380))
        updates["REDIS_PASSWORD"] = redis_password or ""

        lines = env_file.read_text(encoding="utf-8").splitlines()
        remaining = dict(updates)
        output = []
        for line in lines:
            match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if match and match.group(1) in remaining:
                key = match.group(1)
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        for key, value in remaining.items():
            output.append(f"{key}={value}")
        write_text(env_file, "\n".join(output) + "\n")
        print(f"项目 {name} 的 .env 已同步（未覆盖其他配置项）")

    # ------------------------------------------------------------------ 启停
    def start(self, name: str) -> None:
        project = self.find(name)
        project_type = project.get("type")
        if project_type in NODE_TYPES:
            self._start_node(project)
            return
        from providers.nginx import NginxProvider
        from providers.php import PHPProvider

        php = PHPProvider()
        version = project.get("php") or self.config.get("PHP_DEFAULT_VERSION", "8.3")
        if not php.fpm_running(version):
            php.start_fpm(version)
        nginx = NginxProvider()
        self.write_nginx(project)
        if not nginx.running():
            nginx.start()
        else:
            nginx.reload()
        print(f"项目 {name} 已启动: http://{project.get('domain')}:{self.config.get_int('NGINX_HTTP_PORT', 8080)}")

    def stop(self, name: str) -> None:
        project = self.find(name)
        if project.get("type") in NODE_TYPES:
            pid_file = self.config.run_dir / "projects" / f"{name}.pid"
            pid = system.read_pid(pid_file)
            if pid and system.pid_alive(pid):
                system.kill_pid(pid, "TERM")
                for _ in range(20):
                    if not system.pid_alive(pid):
                        break
                    time.sleep(0.2)
                print(f"项目 {name} 开发服务器已停止")
            else:
                print(f"项目 {name} 开发服务器未运行")
            system.remove_pid(pid_file)
            return
        print(f"项目 {name} 为 PHP/静态站点，停止由 dev nginx stop / dev php fpm stop 控制")

    def _start_node(self, project: Dict) -> None:
        name = project["name"]
        path = self.resolve_path(project)
        pid_file = self.config.run_dir / "projects" / f"{name}.pid"
        ensure_dir(pid_file.parent)
        pid = system.read_pid(pid_file)
        if pid and system.pid_alive(pid):
            print(f"项目 {name} 开发服务器已在运行 (PID {pid})")
            return
        if (path / "pnpm-lock.yaml").exists():
            command = ["pnpm", "dev"]
        elif (path / "yarn.lock").exists():
            command = ["yarn", "dev"]
        else:
            command = ["npm", "run", "dev"]
        log_path = self.config.logs_dir / "manager" / f"project-{name}.log"
        log_file = open(log_path, "ab")
        env = os.environ.copy()
        env["PATH"] = f"{self.config.home}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(path),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        finally:
            log_file.close()
        pid_file.write_text(str(proc.pid), encoding="utf-8")
        time.sleep(1.0)
        if proc.poll() is not None:
            tail = read_text(log_path).splitlines()[-8:]
            raise ProjectError(f"项目 {name} 启动失败: {' | '.join(tail)}")
        print(f"项目 {name} 开发服务器已启动 (PID {proc.pid})，日志: {log_path}")

    def doctor(self) -> List[str]:
        issues: List[str] = []
        for project in self.projects():
            path = self.resolve_path(project)
            if not path.exists():
                issues.append(f"{project.get('name')}: 目录不存在 {path}")
                continue
            if project.get("type") in ("laravel", "symfony", "php"):
                version = project.get("php")
                from providers.php import PHPProvider

                if version and not PHPProvider().is_installed(version):
                    issues.append(f"{project.get('name')}: PHP {version} 未安装")
            if not self.nginx_conf_path(project["name"]).exists():
                issues.append(f"{project.get('name')}: 缺少 Nginx 配置")
            if project.get("domain") and not self._hosts_has(project["domain"]):
                issues.append(f"{project.get('name')}: /etc/hosts 未配置 {project['domain']}")
        return issues
