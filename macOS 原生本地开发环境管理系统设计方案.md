# macOS 原生本地开发环境管理系统设计方案

**项目名称：** DevEnvironment  
**统一管理命令：** `dev`  
**运行平台：** macOS / Apple Silicon  
**目标设备：** Mac mini M4 / 16GB 内存 / 256GB 存储

---

# 1. 项目目标

构建一套适用于 macOS 的原生本地开发环境管理系统。

不使用 Docker、OrbStack 或其他容器技术，所有服务直接运行在 macOS 系统中。

通过 Python 编写统一管理器，将 PHP、Nginx、MySQL、Redis、Node.js、Composer 等开发组件整合起来，实现统一安装、配置、启动、停止、卸载和诊断。

## 1.1 核心需求

1. 完全原生运行，不依赖容器。
2. 所有开发环境组件统一管理。
3. 支持一键安装整套开发环境。
4. 支持一键启动所有服务。
5. 支持一键停止所有服务。
6. 支持一键重启所有服务。
7. 支持一键卸载全部软件。
8. 支持彻底清理整个开发环境。
9. 支持 PHP 8.1、8.2、8.3、8.4、8.5 多版本。
10. 不同项目可以使用不同 PHP 版本。
11. 支持 PHP 扩展独立安装、启用、停用和卸载。
12. MySQL、Redis 数据与软件版本分离。
13. 支持 MySQL、Redis 版本切换和数据持久化。
14. 所有重要配置集中管理，采用类似 `.env` 的配置方式。
15. 支持 MySQL、Redis 密码方便修改。
16. 项目目录统一配置。
17. 支持项目自动注册和 Nginx 配置生成。
18. 服务默认按需启动，不默认开机自启动。
19. 卸载软件不自动删除用户数据。
20. 配置修改前自动备份，失败自动回滚。

## 1.2 最终使用体验

安装完成后，日常开发只需要：

```bash
# 一键启动整个开发环境
dev up

# 查看运行状态
dev status

# 一键停止整个开发环境
dev down

# 一键重启
dev restart

# 只启动/停止指定服务
dev start mysql redis
dev stop redis

# 查看日志
dev logs mysql
```

安装和维护：

```bash
# 一键安装整套环境
dev install --all

# 一键卸载所有软件，保留数据
dev uninstall --all

# 彻底清理开发环境
dev purge --all

# 环境诊断
dev doctor
```

---

# 2. 整体技术架构

## 2.1 技术选型

| 组件 | 技术 | 用途 |
|---|---|---|
| 操作系统 | macOS | 原生运行环境 |
| 软件包管理 | Homebrew | 软件安装和卸载 |
| 管理器语言 | Python 3 | 核心管理程序 |
| CLI 框架 | Typer | 命令行交互 |
| 服务管理 | launchd | 后台服务生命周期管理 |
| Web 服务 | Nginx | HTTP / HTTPS |
| PHP | PHP 8.1～8.5 | 后端开发 |
| PHP 进程管理 | PHP-FPM | PHP 请求处理 |
| 数据库 | MySQL | 数据存储 |
| 缓存 | Redis | 缓存和队列 |
| 前端运行环境 | Node.js | React / Vite |
| Node 版本管理 | fnm | Node 多版本管理 |
| 前端包管理 | npm / pnpm | 前端依赖 |
| PHP 包管理 | Composer | PHP 依赖 |
| 配置格式 | ENV / JSON / TOML | 配置管理 |
| 敏感信息管理 | macOS Keychain | 密码安全存储 |

## 2.2 整体架构

```text
                         macOS
                           │
                           │
                   Python 管理器
                       dev CLI
                           │
              ┌────────────┴────────────┐
              │                         │
           配置中心                  生命周期管理
              │                         │
       ┌──────┼──────┐            ┌─────┼─────┐
       │      │      │            │     │     │
      .env  JSON  Keychain       安装  启动  卸载
       │      │      │            │     │     │
       └──────┴──────┘            └─────┼─────┘
                                        │
                                  服务管理层
                                        │
             ┌──────────┬──────────┬────┼─────┐
             │          │          │    │     │
           Nginx       PHP       MySQL Redis Node
                        │
                ┌───────┼────────┐
                │       │        │
               8.1     8.3      8.5
                │       │        │
                └───────┼────────┘
                        │
                    PHP-FPM
                        │
                   Unix Socket
                        │
                     Nginx
                        │
                     项目代码
```

## 2.3 组件职责

管理器负责：

- 检测软件安装状态。
- 调用 Homebrew 安装软件。
- 管理软件版本。
- 生成服务配置。
- 管理 launchd。
- 管理服务启停。
- 管理 PHP 扩展。
- 管理项目。
- 管理数据库连接凭据。
- 管理配置文件。
- 管理备份。
- 检测端口冲突。
- 检查环境运行状态。

Homebrew 只负责软件包本身，不承担统一服务生命周期管理。

同一个服务不能同时交给 Homebrew Services 和自定义 launchd 托管。

---

# 3. 统一目录规划

## 3.1 根目录

所有开发环境配置、数据、日志和运行文件统一放在：

```text
~/DevEnvironment/
```

所有项目源码统一放在：

```text
~/Projects/
```

项目源码与开发环境管理器完全分离。

卸载开发环境时，不允许默认删除项目源码。

## 3.2 完整目录结构

```text
~/DevEnvironment/
│
├── .env
├── .env.example
├── .gitignore
│
├── bin/
│   └── dev
│
├── software/
│   ├── php/
│   │   ├── 8.1/
│   │   ├── 8.2/
│   │   ├── 8.3/
│   │   ├── 8.4/
│   │   └── 8.5/
│   │
│   ├── mysql/
│   │   ├── 8.0/
│   │   └── 8.4/
│   │
│   └── redis/
│       └── versions/
│
├── config/
│   │
│   ├── environment.json
│   │
│   ├── nginx/
│   │   ├── nginx.conf
│   │   └── projects/
│   │
│   ├── php/
│   │   ├── 8.1/
│   │   │   ├── php.ini
│   │   │   └── conf.d/
│   │   ├── 8.2/
│   │   ├── 8.3/
│   │   ├── 8.4/
│   │   └── 8.5/
│   │
│   ├── mysql/
│   │   ├── 8.0/
│   │   │   └── my.cnf
│   │   └── 8.4/
│   │       └── my.cnf
│   │
│   ├── redis/
│   │   └── redis.conf
│   │
│   └── projects/
│       └── projects.json
│
├── data/
│   ├── mysql/
│   │   ├── 8.0/
│   │   │   └── data/
│   │   ├── 8.4/
│   │   │   └── data/
│   │   └── backups/
│   │
│   └── redis/
│       ├── data/
│       └── backups/
│
├── logs/
│   ├── nginx/
│   ├── php/
│   ├── mysql/
│   ├── redis/
│   └── manager/
│
├── run/
│   ├── nginx/
│   ├── mysql/
│   ├── redis/
│   └── php/
│       ├── php81.sock
│       ├── php82.sock
│       ├── php83.sock
│       ├── php84.sock
│       └── php85.sock
│
├── state/
│   ├── installed.json
│   ├── services.json
│   ├── versions.json
│   └── migrations.json
│
├── backups/
│   ├── config/
│   ├── mysql/
│   ├── redis/
│   └── system/
│
└── manager/
    ├── main.py
    │
    ├── core/
    │   ├── manager.py
    │   ├── installer.py
    │   ├── service.py
    │   ├── config.py
    │   ├── backup.py
    │   ├── database.py
    │   ├── dependency.py
    │   └── doctor.py
    │
    ├── providers/
    │   ├── php.py
    │   ├── nginx.py
    │   ├── mysql.py
    │   ├── redis.py
    │   ├── node.py
    │   └── composer.py
    │
    ├── commands/
    │   ├── global.py
    │   ├── php.py
    │   ├── ext.py
    │   ├── mysql.py
    │   ├── redis.py
    │   ├── nginx.py
    │   └── project.py
    │
    └── utils/
        ├── shell.py
        ├── filesystem.py
        ├── system.py
        ├── security.py
        └── validation.py
```

---

# 4. 全局配置中心

## 4.1 设计目标

所有开发环境基础配置统一管理，采用 `.env` 形式。

不需要每次修改项目目录、端口、数据库密码时，到处修改配置文件。

全局配置和项目配置分开管理。

- `.env`：全局配置。
- `projects.json`：项目配置。
- macOS Keychain：敏感密码。
- 各服务配置：由管理器根据全局配置自动生成。

## 4.2 .env.example

```dotenv
# =====================================
# 基础目录
# =====================================

DEV_HOME=$HOME/DevEnvironment

PROJECTS_HOME=$HOME/Projects

# =====================================
# PHP
# =====================================

PHP_DEFAULT_VERSION=8.3

PHP_FPM_ENABLED_VERSIONS=8.3

# =====================================
# Nginx
# =====================================

NGINX_HTTP_PORT=8080

NGINX_HTTPS_PORT=8443

NGINX_ENABLED=true

# =====================================
# MySQL
# =====================================

MYSQL_VERSION=8.4

MYSQL_HOST=127.0.0.1

MYSQL_PORT=3307

MYSQL_ENABLED=true

MYSQL_DATA_DIR=$DEV_HOME/data/mysql

# =====================================
# Redis
# =====================================

REDIS_VERSION=latest

REDIS_HOST=127.0.0.1

REDIS_PORT=6380

REDIS_ENABLED=true

REDIS_DATA_DIR=$DEV_HOME/data/redis

# =====================================
# Node
# =====================================

NODE_DEFAULT_VERSION=22

# =====================================
# Composer
# =====================================

COMPOSER_ENABLED=true

# =====================================
# 环境行为
# =====================================

AUTO_START=false

AUTO_BACKUP=true

KEEP_DATA_ON_UNINSTALL=true
```

`.env.example` 只提供模板，不保存真实密码。

## 4.3 实际 .env

首次安装时：

```bash
cp .env.example .env
```

实际 `.env` 保存本机自定义配置。

例如：

```dotenv
DEV_HOME=/Users/用户名/DevEnvironment

PROJECTS_HOME=/Users/用户名/Projects

PHP_DEFAULT_VERSION=8.3

NGINX_HTTP_PORT=8080

MYSQL_VERSION=8.4
MYSQL_PORT=3307

REDIS_PORT=6380
```

注意：真实密码不建议长期明文放在 `.env` 中，统一交给 macOS Keychain。

## 4.4 配置修改命令

```bash
# 查看所有配置
dev config

# 查看指定配置
dev config get MYSQL_PORT

# 修改端口
dev config set MYSQL_PORT 3308

# 修改项目根目录
dev config set PROJECTS_HOME /Users/用户名/Projects

# 修改 PHP 默认版本
dev config set PHP_DEFAULT_VERSION 8.5

# 重新加载配置
dev config reload

# 检查配置
dev config validate
```

配置变更后，管理器判断哪些服务需要重新生成配置或重启。

不会因为修改无关配置而重启所有服务。

---

# 5. 密码与敏感信息管理

## 5.1 使用 macOS Keychain

数据库密码、Redis 密码等敏感信息存储在 macOS Keychain。

避免在普通配置文件中明文保存密码。

建议凭据名称：

```text
dev.mysql.root
dev.mysql.erp
dev.redis.default
dev.redis.erp
```

管理器负责读取和写入 Keychain。

## 5.2 MySQL 密码管理

命令：

```bash
# 初始化 root 密码
dev mysql password init

# 修改 root 密码
dev mysql password

# 创建数据库用户
dev mysql user create erp

# 修改数据库用户密码
dev mysql user password erp

# 删除用户
dev mysql user delete erp

# 查看用户
dev mysql user list

# 创建数据库并指定属主（属主用户不存在时自动创建，密码同用户名）
dev mysql database create erp --owner erp

# 查看数据库
dev mysql database list
```

创建数据库时如果指定了 `--owner` 且该用户不存在，管理器会自动创建 `localhost` 与 `127.0.0.1` 两个账号，密码默认与用户名相同并写入 Keychain，随后授予该库全部权限。自动创建后应尽快执行 `dev mysql user password <用户>` 修改密码。

修改密码时：

1. 验证当前数据库连接。
2. 修改 MySQL 内部用户密码。
3. 更新 Keychain 凭据。
4. 验证新密码是否可以连接。
5. 提示是否同步更新对应项目配置。

不能只修改 Keychain 而不修改 MySQL 内部密码。

## 5.3 Redis 密码管理

命令：

```bash
# 初始化密码
dev redis password init

# 修改密码
dev redis password

# 创建用户
dev redis user create erp

# 修改用户密码
dev redis user password erp

# 查看用户
dev redis user list
```

Redis 6 及以上版本优先使用 ACL。

支持不同项目使用独立 Redis 用户。

## 5.4 项目密码配置

Laravel 项目仍然使用自己的 `.env`：

```dotenv
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3307
DB_DATABASE=erp
DB_USERNAME=erp
DB_PASSWORD=项目数据库密码

REDIS_HOST=127.0.0.1
REDIS_PORT=6380
REDIS_PASSWORD=项目Redis密码
```

管理器可以通过命令将 Keychain 中的凭据同步到项目 `.env`。

```bash
dev project sync-env erp
```

同步时保留项目中其他已有配置，不能直接覆盖整个 `.env` 文件。

---

# 6. 统一命令行设计

## 6.1 基础命令

```bash
dev
dev help
dev help php
dev help php fpm
dev version
dev status
dev info
dev doctor
dev logs mysql
```

## 6.2 一键生命周期命令

这是整个系统最重要的功能。

### 一键安装

```bash
dev install --all
```

自动检查并安装：

- PHP 指定版本。
- PHP 默认扩展。
- Nginx。
- MySQL。
- Redis。
- Node.js。
- Composer。
- 管理器所需依赖。

安装前检查：

- Homebrew 是否可用。
- macOS 架构是否兼容。
- 磁盘空间是否足够。
- 目标软件版本是否存在。
- 是否有端口冲突。
- 配置目录是否可用。

安装过程必须可重复执行。

已经安装的组件自动跳过，不重复安装。

### 一键启动

```bash
dev up
```

启动顺序：

1. 检查配置。
2. 检查数据目录。
3. 启动 MySQL。
4. 启动 Redis。
5. 启动已启用的 PHP-FPM。
6. 启动 Nginx。
7. 检查服务健康状态。

### 一键停止

```bash
dev down
```

停止顺序：

1. 停止 Nginx。
2. 停止 PHP-FPM。
3. 停止 Redis。
4. 停止 MySQL。

### 一键重启

```bash
dev restart
```

先执行停止，再按依赖顺序启动。

### 批量启动 / 停止指定服务

```bash
# 启动指定服务（按依赖顺序）
dev start mysql redis
dev up --only mysql,redis,nginx

# 停止指定服务（按依赖逆序）
dev stop redis mysql
dev down --only redis,mysql

# 重启指定服务
dev restart php redis
```

支持的服务名：`mysql`、`redis`、`php`、`nginx`。不指定时作用于全部服务；无效名称会被提示并忽略。

### 查看日志

```bash
dev logs                    # Nginx 错误日志，默认最近 50 行
dev logs nginx:access       # Nginx 访问日志
dev logs php                # 当前 PHP 版本的 FPM 错误日志
dev logs php:8.3            # 指定 PHP 版本
dev logs php:slow           # PHP 慢日志
dev logs mysql              # 当前 MySQL 版本错误日志
dev logs mysql:slow         # MySQL 慢查询日志
dev logs redis              # Redis 日志
dev logs nginx:access -n 200
dev logs nginx:access -f    # 持续跟踪，Ctrl+C 退出
```

日志文件不存在时会列出当前所有可用日志。

### 一键卸载

```bash
dev uninstall --all
```

卸载所有由管理器安装的软件，保留：

- 项目源码。
- 数据库数据。
- Redis 数据。
- 自定义配置。
- 日志。
- 备份。

按组件批量卸载：

```bash
dev uninstall nginx redis
dev uninstall php:8.3 mysql:8.4
dev uninstall node composer --yes
```

不指定组件时不会执行，必须显式给出组件或 `--all`。

### 选择性清理

默认只清空日志，避免误删数据：

```bash
dev purge                 # 仅清空日志（默认）
dev purge logs            # 同上
dev purge data            # 清空 MySQL/Redis 数据（保留已安装软件）
dev purge config          # 删除生成的配置，下次启动自动重建
dev purge state           # 清空管理器状态记录
dev purge backups         # 删除所有备份
dev purge data config     # 组合清理，需确认
dev purge data config --yes

# 彻底清理（软件 + 数据 + 配置 + 日志 + 状态 + 备份）
dev purge --all
dev purge all
```

说明：

- `logs` 直接清空日志文件，无需确认。
- `data`、`config`、`state`、`backups` 需要确认，`--yes` 可跳过。
- `all` 需要双重确认。
- 数据与配置删除后不可恢复；项目源码与 `.env` 不在清理范围内。

## 6.3 单个组件管理

全局命令之外，保留单个服务操作：

```bash
dev nginx start
dev nginx stop
dev nginx restart

dev mysql start
dev mysql stop
dev mysql restart

dev redis start
dev redis stop
dev redis restart
```

PHP：

```bash
dev php fpm start 8.3
dev php fpm stop 8.3
dev php fpm restart 8.3
```

## 6.4 统一生命周期

所有组件实现统一接口：

| 操作 | 作用 |
|---|---|
| install | 安装 |
| enable | 纳入启用管理 |
| disable | 禁止自动纳入全局启动 |
| start | 启动 |
| stop | 停止 |
| restart | 重启 |
| status | 状态 |
| info | 信息 |
| uninstall | 卸载，保留数据 |
| reinstall | 重新安装 |
| purge | 彻底清理 |

enable / disable 与 start / stop 分开。

例如：

```bash
dev disable redis
```

表示不再由 `dev up` 自动启动 Redis，不代表立即卸载 Redis。

---

# 7. PHP 多版本管理

## 7.1 支持版本

支持以下 PHP 版本：

| PHP 版本 | 支持方式 |
|---|---|
| PHP 8.1 | 独立安装 |
| PHP 8.2 | 独立安装 |
| PHP 8.3 | 独立安装 |
| PHP 8.4 | 独立安装 |
| PHP 8.5 | 独立安装 |

所有版本可以按需安装。

使用 Homebrew 管理软件包，优先采用 `shivammathur/php` 仓库。

```bash
brew tap shivammathur/php
```

安装示例：

```bash
brew install shivammathur/php/php@8.1
brew install shivammathur/php/php@8.2
brew install shivammathur/php/php@8.3
brew install shivammathur/php/php@8.4
brew install shivammathur/php/php@8.5
```

实际安装前必须检查公式是否存在、PHP 版本是否仍受支持，以及当前 macOS 和 Apple Silicon 是否兼容。

## 7.2 PHP 管理命令

```bash
# 安装
dev php install 8.3
dev php install 8.5

# 卸载
dev php uninstall 8.3

# 查看所有版本
dev php list

# 切换 CLI 默认版本
dev php switch 8.5

# 查看当前版本
dev php current

# 查看版本信息
dev php info 8.5

# 查看 php.ini
dev php ini 8.5
```

CLI 默认版本与 PHP-FPM 运行版本相互独立。

切换 CLI 默认版本，不影响正在运行的项目。

## 7.3 PHP-FPM 多版本运行

每个 PHP 版本拥有独立的 PHP-FPM 进程。

不同版本可以同时运行。

```bash
dev php fpm start 8.3
dev php fpm start 8.5

dev php fpm stop 8.3
dev php fpm restart 8.5

dev php fpm status
```

Socket：

```text
~/DevEnvironment/run/php/
├── php81.sock
├── php82.sock
├── php83.sock
├── php84.sock
└── php85.sock
```

项目通过 Nginx 连接对应 PHP-FPM Socket。

## 7.4 PHP 配置隔离

```text
config/php/
├── 8.1/
│   ├── php.ini
│   └── conf.d/
├── 8.2/
│   ├── php.ini
│   └── conf.d/
├── 8.3/
│   ├── php.ini
│   └── conf.d/
├── 8.4/
│   ├── php.ini
│   └── conf.d/
└── 8.5/
    ├── php.ini
    └── conf.d/
```

每个版本独立管理：

- php.ini
- PHP-FPM 配置。
- 扩展配置。
- 扩展二进制。
- PHP CLI。
- PHP-FPM。
- phpize。
- php-config。

---

# 8. PHP 默认扩展管理

## 8.1 默认扩展清单

以下为每个 PHP 版本的目标扩展集合。

管理器尽可能安装全部兼容扩展。

```text
bcmath
calendar
Core
ctype
curl
date
dom
exif
FFI
fileinfo
filter
ftp
gd
gettext
hash
iconv
igbinary
imagick
intl
json
libxml
mbstring
memcached
msgpack
mysqli
mysqlnd
openssl
pcntl
pcre
PDO
pdo_mysql
pdo_pgsql
pdo_sqlite
pgsql
Phar
posix
random
readline
redis
Reflection
session
shmop
SimpleXML
sockets
sodium
SPL
sqlite3
standard
swoole
sysvmsg
sysvsem
sysvshm
tokenizer
xdebug
xlswriter
xml
xmlreader
xmlwriter
xsl
Zend OPcache
zip
zlib
```

Zend Modules：

```text
Xdebug
Zend OPcache
```

## 8.2 扩展分类

### PHP 核心模块

由 PHP 本身提供，不需要单独安装：

```text
Core
date
json
pcre
Reflection
SPL
standard
```

### PHP 自带扩展

通常随 PHP 构建提供，或通过 PHP 构建选项启用：

```text
bcmath
calendar
ctype
curl
dom
exif
fileinfo
filter
ftp
gd
gettext
iconv
intl
mbstring
mysqli
mysqlnd
openssl
pcntl
PDO
pdo_mysql
pdo_pgsql
pdo_sqlite
pgsql
Phar
posix
readline
session
shmop
SimpleXML
sockets
sodium
sqlite3
sysvmsg
sysvsem
sysvshm
tokenizer
xml
xmlreader
xmlwriter
xsl
zip
zlib
```

### PECL 第三方扩展

需要按 PHP ABI 单独编译或安装：

```text
igbinary
imagick
memcached
msgpack
redis
swoole
xdebug
xlswriter
```

### Zend 扩展

```text
Xdebug
Zend OPcache
```

OPcache 通常由 PHP 构建提供。

Xdebug 作为开发调试扩展管理，默认安装但默认关闭。

## 8.3 扩展管理命令

```bash
# 搜索扩展
dev ext search redis

# 安装扩展
dev ext install redis --php=8.3

# 启用扩展
dev ext enable redis --php=8.3

# 停用扩展
dev ext disable redis --php=8.3

# 卸载扩展
dev ext uninstall redis --php=8.3

# 查看扩展
dev ext list --php=8.3

# 检查扩展
dev ext doctor --php=8.5
```

## 8.4 PHP 8.5 扩展兼容性

PHP 8.5 必须单独检查第三方扩展兼容性。

重点检查：

| 扩展 | 处理要求 |
|---|---|
| redis | 检查兼容版本 |
| igbinary | 检查兼容版本 |
| imagick | 检查兼容版本 |
| memcached | 检查兼容版本 |
| msgpack | 检查兼容版本 |
| swoole | 检查兼容版本 |
| xdebug | 检查兼容版本 |
| xlswriter | 检查兼容版本 |

如果扩展暂不支持 PHP 8.5：

1. 不影响 PHP 8.5 本身安装。
2. 标记为不兼容。
3. 记录失败原因。
4. 保存编译日志。
5. 不影响其他扩展安装。
6. 后续支持重新检测和安装。

扩展二进制必须与 PHP 版本、架构和 ABI 匹配。

## 8.5 默认启用策略

| 扩展 | 默认策略 |
|---|---|
| OPcache | 默认启用 |
| Xdebug | 默认安装，默认关闭 |
| Redis | 安装后启用 |
| Swoole | 安装后启用 |
| Imagick | 安装后启用 |
| Memcached | 安装后启用 |
| igbinary | 安装后启用 |
| msgpack | 安装后启用 |
| xlswriter | 安装后启用 |

每个 PHP 版本安装完成后进行扩展验证：

```bash
php -m
php --ri redis
php --ri swoole
php --ri imagick
php --ri xdebug
```

实际执行时必须使用对应版本的 PHP 二进制，而不是仅检查当前 CLI 默认版本。

---

# 9. Nginx 管理

## 9.1 安装

```bash
dev nginx install
```

## 9.2 配置目录

```text
config/nginx/
├── nginx.conf
└── projects/
    ├── erp.conf
    ├── laravel.conf
    └── react.conf
```

## 9.3 端口

```text
HTTP  8080
HTTPS 8443
```

## 9.4 管理命令

```bash
dev nginx start
dev nginx stop
dev nginx restart
dev nginx reload
dev nginx status
dev nginx test
```

## 9.5 Laravel 项目配置示例

```nginx
server {
    listen 8080;

    server_name erp.local;

    root /Users/用户名/Projects/erp/public;

    index index.php index.html;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        fastcgi_pass unix:/Users/用户名/DevEnvironment/run/php/php83.sock;

        fastcgi_index index.php;

        include fastcgi_params;

        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
}
```

Nginx 配置由项目管理器自动生成。

不同项目自动选择不同 PHP-FPM Socket。

---

# 10. MySQL 管理

## 10.1 版本管理

支持 MySQL 多版本独立安装。

初期建议重点支持：

- MySQL 8.0。
- MySQL 8.4。

未来可以根据需要增加其他版本。

安装：

```bash
dev mysql install 8.4
dev mysql install 8.0
```

查看：

```bash
dev mysql list
dev mysql info
```

切换：

```bash
dev mysql switch 8.0
dev mysql switch 8.4
```

升级：

```bash
dev mysql upgrade 8.0 8.4
```

## 10.2 数据持久化

数据库软件和数据库数据彻底分离。

软件目录：

```text
software/mysql/
├── 8.0/
└── 8.4/
```

数据目录：

```text
data/mysql/
├── 8.0/
│   └── data/
├── 8.4/
│   └── data/
└── backups/
```

不同 MySQL 大版本拥有独立的数据目录。

不能让不同大版本直接共用一个数据目录。

## 10.3 版本切换

```bash
dev mysql switch 8.0
```

执行：

1. 检查目标版本是否安装。
2. 检查对应数据目录。
3. 检查当前数据库状态。
4. 停止当前 MySQL。
5. 启动目标版本。
6. 检查数据库连接。
7. 更新当前版本状态。

如果目标版本没有数据目录，提示初始化或恢复备份。

## 10.4 数据升级

```bash
dev mysql upgrade 8.0 8.4
```

升级流程：

1. 停止 MySQL。
2. 检查磁盘空间。
3. 执行数据库备份。
4. 检查版本兼容性。
5. 创建新版本独立数据目录。
6. 执行官方支持的升级流程。
7. 启动新版本。
8. 检查数据库完整性。
9. 更新当前版本状态。
10. 保留旧版本数据和备份。

不能直接把新版本数据目录交给旧版本运行。

不能保证任意版本之间都可以直接降级。

## 10.5 MySQL 配置

```text
config/mysql/
├── 8.0/
│   └── my.cnf
└── 8.4/
    └── my.cnf
```

默认端口：

```text
3307
```

默认监听：

```text
127.0.0.1
```

数据目录：

```text
data/mysql/
```

## 10.6 MySQL 管理命令

```bash
dev mysql start
dev mysql stop
dev mysql restart
dev mysql status

dev mysql password
dev mysql user create erp
dev mysql user password erp
dev mysql user list

# 属主用户不存在时自动创建（密码同用户名）
dev mysql database create erp --owner erp
dev mysql database list

dev mysql backup
dev mysql restore
```

## 10.7 卸载策略

卸载 MySQL 默认只卸载软件。

不删除：

- 数据目录。
- 数据库文件。
- 备份文件。
- 用户自定义配置。

彻底清理必须使用：

```bash
dev mysql purge
```

并进行二次确认。

---

# 11. Redis 管理

## 11.1 安装和版本管理

```bash
dev redis install
dev redis list
dev redis info
```

后续可以扩展 Redis 多版本管理。

## 11.2 数据持久化

软件和数据分离。

```text
software/redis/

data/redis/
├── data/
└── backups/
```

Redis 默认配置 RDB 持久化，并支持 AOF 配置。

切换 Redis 版本时，必须检查 RDB/AOF 文件格式兼容性。

不允许未经检查直接覆盖原数据。

## 11.3 配置

默认端口：

```text
6380
```

默认监听：

```text
127.0.0.1
```

配置文件：

```text
config/redis/redis.conf
```

## 11.4 管理命令

```bash
dev redis start
dev redis stop
dev redis restart
dev redis status

dev redis password
dev redis user create erp
dev redis user password erp

dev redis backup
dev redis restore
```

## 11.5 数据保护

卸载 Redis 默认保留：

- RDB 文件。
- AOF 文件。
- 用户配置。
- 备份。

彻底清理使用：

```bash
dev redis purge
```

---

# 12. Node.js / React / Vite

## 12.1 Node.js

使用 fnm 管理 Node.js 多版本。

安装：

```bash
brew install fnm
```

版本示例：

```bash
fnm install 22
fnm install 24

fnm use 22
fnm default 22
```

具体版本根据 Node.js 官方支持情况选择。

## 12.2 前端包管理

安装 pnpm：

```bash
npm install -g pnpm
```

支持：

- npm。
- pnpm。
- Node.js 多版本。
- React。
- Vue。
- Vite。

## 12.3 前端项目启动

```bash
cd ~/Projects/react-admin

pnpm install

pnpm dev
```

默认 Vite 端口：

```text
5173
```

Node.js 开发服务器默认由项目自己的开发命令运行。

如果后续需要统一管理前端开发服务器，可以增加：

```bash
dev project start react-admin
dev project stop react-admin
```

---

# 13. Composer 管理

安装：

```bash
dev composer install
```

管理命令：

```bash
dev composer version
dev composer diagnose
```

Composer 使用当前 CLI 默认 PHP 版本。

指定版本运行：

```bash
dev php run 8.3 composer install
```

也可以在项目配置中指定 PHP 版本，由管理器自动选择对应 PHP 执行 Composer。

---

# 14. 项目管理

## 14.1 项目目录

全局项目目录通过 `.env` 设置：

```dotenv
PROJECTS_HOME=/Users/用户名/Projects
```

统一结构：

```text
~/Projects/
├── erp/
├── laravel/
├── react-admin/
└── other-projects/
```

修改项目根目录时，管理器自动重新解析项目配置。

不需要手动修改每个项目的路径。

## 14.2 项目配置

文件：

```text
config/projects/projects.json
```

示例：

```json
{
  "projects": [
    {
      "name": "erp",
      "path": "${PROJECTS_HOME}/erp",
      "type": "laravel",
      "domain": "erp.local",
      "php": "8.3",
      "document_root": "public",
      "mysql": true,
      "redis": true,
      "enabled": true
    },
    {
      "name": "laravel",
      "path": "${PROJECTS_HOME}/laravel",
      "type": "laravel",
      "domain": "laravel.local",
      "php": "8.5",
      "document_root": "public",
      "mysql": true,
      "redis": false,
      "enabled": true
    },
    {
      "name": "react-admin",
      "path": "${PROJECTS_HOME}/react-admin",
      "type": "react",
      "port": 5173,
      "enabled": true
    }
  ]
}
```

## 14.3 项目管理命令

```bash
# 添加项目
dev project add erp

# 删除项目配置
dev project remove erp

# 查看项目
dev project list

# 查看详情
dev project info erp

# 设置 PHP 版本
dev project php erp 8.5

# 生成 Nginx 配置
dev project config erp

# 启动项目
dev project start erp

# 停止项目
dev project stop erp

# 同步项目环境变量
dev project sync-env erp
```

## 14.4 添加项目自动化

执行：

```bash
dev project add erp
```

管理器自动：

1. 检查项目目录。
2. 识别 Laravel、React、Vue 等项目类型。
3. 读取项目配置。
4. 检查 PHP 版本。
5. 检查所需服务。
6. 注册项目。
7. 生成 Nginx 配置。
8. 检查域名配置。
9. 检查端口冲突。

如果无法自动识别项目类型，允许用户指定类型。

---

# 15. launchd 服务管理

## 15.1 管理原则

使用 macOS launchd 管理后台服务。

统一由 `dev` 管理服务生命周期。

Homebrew 只负责软件安装。

避免 Homebrew Services 和自定义 launchd 同时托管同一个服务。

## 15.2 服务启动方式

默认按需启动，不默认开机自启动。

用户执行：

```bash
dev up
```

管理器根据配置启动所有启用的服务。

用户执行：

```bash
dev down
```

管理器停止所有由它管理的服务。

## 15.3 服务配置

使用：

```text
~/Library/LaunchAgents/
```

管理器为各服务生成独立 plist。

服务启动前检查：

- 软件是否安装。
- 配置是否存在。
- 配置是否有效。
- 数据目录是否存在。
- 端口是否冲突。
- 依赖服务是否运行。
- 文件权限是否正确。

---

# 16. 服务依赖与启动编排

## 16.1 启动顺序

```text
检查配置
   │
   ▼
检查数据目录
   │
   ▼
启动 MySQL
   │
   ▼
启动 Redis
   │
   ▼
启动 PHP-FPM
   │
   ▼
启动 Nginx
   │
   ▼
健康检查
```

Node.js 前端开发服务器按项目需求单独启动。

## 16.2 停止顺序

```text
停止 Nginx
   │
   ▼
停止 PHP-FPM
   │
   ▼
停止 Redis
   │
   ▼
停止 MySQL
```

## 16.3 故障处理

某个服务启动失败：

1. 记录错误日志。
2. 显示失败组件。
3. 显示失败原因。
4. 不擅自杀死其他进程。
5. 不删除任何数据。
6. 对依赖该服务的组件停止继续启动。
7. 对不相关的组件允许继续启动。
8. 最终汇总整体启动结果。

---

# 17. 状态管理

## 17.1 installed.json

记录安装状态：

```json
{
  "php": [
    "8.3",
    "8.5"
  ],
  "nginx": true,
  "mysql": [
    "8.4"
  ],
  "redis": true,
  "node": true,
  "composer": true
}
```

## 17.2 services.json

```json
{
  "nginx": {
    "enabled": true,
    "running": true,
    "port": 8080
  },
  "mysql": {
    "enabled": true,
    "running": true,
    "version": "8.4",
    "port": 3307
  },
  "redis": {
    "enabled": true,
    "running": true,
    "port": 6380
  },
  "php": {
    "8.3": {
      "enabled": true,
      "running": true
    },
    "8.5": {
      "enabled": false,
      "running": false
    }
  }
}
```

实际状态必须通过进程、Socket、端口、服务管理状态和健康检查获取。

不能只依赖 JSON 记录。

## 17.3 versions.json

记录当前默认版本：

```json
{
  "php_cli": "8.3",
  "mysql": "8.4",
  "node": "22"
}
```

---

# 18. 备份与恢复

## 18.1 备份范围

支持备份：

- 全局 `.env`。
- 服务配置。
- PHP 配置。
- Nginx 配置。
- MySQL 数据。
- Redis 数据。
- 项目管理配置。
- 管理器状态。

不默认备份项目源码。

## 18.2 命令

```bash
# 备份全部配置和数据
dev backup

# 仅备份配置
dev backup config

# 备份 MySQL
dev backup mysql

# 备份 Redis
dev backup redis

# 查看备份
dev backup list

# 恢复
dev restore
```

## 18.3 MySQL 备份要求

优先采用与数据库版本兼容的官方备份方式。

逻辑备份可使用 `mysqldump` 或 `mysqlpump`（根据实际版本和工具可用性选择）。

备份时记录：

- MySQL 版本。
- 数据库列表。
- 备份时间。
- 备份文件。
- 备份校验结果。

## 18.4 Redis 备份要求

备份 RDB/AOF 文件时，必须保证文件完整性。

备份记录 Redis 版本和持久化格式信息。

---

# 19. 环境诊断

统一执行：

```bash
dev doctor
```

检查：

- macOS 版本。
- CPU 架构。
- Homebrew。
- Python。
- PHP 版本。
- PHP 扩展。
- PHP-FPM。
- Nginx。
- MySQL。
- Redis。
- Node.js。
- Composer。
- 端口冲突。
- 数据目录。
- 配置权限。
- 服务状态。
- 备份状态。
- Keychain 凭据读取情况。

子命令：

```bash
dev php doctor
dev mysql doctor
dev redis doctor
dev nginx doctor
dev project doctor
```

诊断报告应显示：

- 正常项目。
- 异常项目。
- 异常原因。
- 修复建议。

不应在未经用户确认的情况下自动执行危险修复。

---

# 20. 端口规划

统一规划：

| 服务 | 端口 | 说明 |
|---|---:|---|
| Nginx HTTP | 8080 | HTTP |
| Nginx HTTPS | 8443 | HTTPS |
| MySQL | 3307 | 数据库 |
| Redis | 6380 | 缓存 |
| Vite | 5173 | 前端开发 |
| PHP-FPM | Unix Socket | 不占 TCP 端口 |

默认所有数据库和缓存服务只监听：

```text
127.0.0.1
```

PHP-FPM 使用：

```text
php81.sock
php82.sock
php83.sock
php84.sock
php85.sock
```

端口冲突时：

- 显示端口。
- 显示 PID。
- 显示进程名称。
- 给出解决建议。
- 不擅自终止进程。

---

# 21. 安全与数据保护

必须遵守：

1. MySQL 默认只监听本地。
2. Redis 默认只监听本地。
3. 数据库密码优先存储于 Keychain。
4. `.env` 不提交到 Git。
5. 不擅自杀死其他进程。
6. 不擅自删除用户数据。
7. 普通卸载保留数据。
8. purge 必须二次确认。
9. 修改配置前自动备份。
10. 配置变更后必须执行语法检查。
11. 配置检查失败自动回滚。
12. PHP 各版本扩展相互隔离。
13. 数据库不同大版本使用独立数据目录。
14. 数据库升级前必须备份。
15. 项目源码与开发环境管理器分离。
16. 密码不能输出到普通日志。
17. 安装和卸载过程记录操作日志。
18. 不允许管理器静默覆盖用户自定义配置。

---

# 22. 管理器代码架构

## 22.1 Provider 模式

每种软件使用独立 Provider。

示例：

```python
class PHPProvider:

    def install(self, version):
        pass

    def uninstall(self, version):
        pass

    def start(self, version):
        pass

    def stop(self, version):
        pass

    def restart(self, version):
        pass

    def status(self, version):
        pass

    def info(self, version):
        pass
```

其他 Provider：

```text
PHPProvider
NginxProvider
MySQLProvider
RedisProvider
NodeProvider
ComposerProvider
```

## 22.2 核心管理模块

| 模块 | 职责 |
|---|---|
| Manager | 总体编排 |
| Installer | 软件安装 |
| ServiceManager | 服务生命周期 |
| ConfigManager | 配置管理 |
| BackupManager | 备份恢复 |
| DatabaseManager | 数据库管理 |
| DependencyManager | 依赖关系 |
| ProjectManager | 项目管理 |
| SecretManager | Keychain 密码管理 |
| Doctor | 环境诊断 |

## 22.3 命令执行规范

所有系统命令通过 Python subprocess 执行。

要求：

- 使用参数数组，不使用不安全字符串拼接。
- 捕获 stdout 和 stderr。
- 设置执行超时。
- 记录错误日志。
- 处理权限异常。
- 不擅自执行危险命令。
- 失败时给出可读错误信息。

---

# 23. 开发实施计划

建议分阶段开发，不要一次性实现所有功能。

## 第一阶段：管理器基础

实现：

- Python CLI。
- Typer 命令框架。
- 统一目录初始化。
- `.env` 配置加载。
- JSON 状态管理。
- Keychain 基础封装。
- Homebrew 检测。
- 日志管理。
- 配置备份。
- doctor 基础诊断。

目标：

```bash
dev version
dev status
dev config
dev doctor
```

## 第二阶段：PHP 多版本管理

实现：

- PHP 8.1～8.5 安装。
- CLI 默认版本切换。
- PHP-FPM 多版本运行。
- PHP 配置隔离。
- PHP 扩展管理。
- 扩展兼容性检测。

目标：

```bash
dev php install 8.5
dev php switch 8.5
dev php fpm start 8.5
dev ext list --php=8.5
```

## 第三阶段：Nginx 和项目管理

实现：

- Nginx 安装。
- Nginx 配置生成。
- 虚拟主机管理。
- PHP-FPM Socket 自动匹配。
- 项目注册。
- 项目目录管理。
- 域名配置。

目标：

```bash
dev project add erp
dev project config erp
dev nginx start
```

## 第四阶段：MySQL / Redis

实现：

- MySQL 安装。
- MySQL 多版本管理。
- MySQL 数据目录隔离。
- MySQL 数据升级。
- MySQL 密码管理。
- Redis 安装。
- Redis 数据持久化。
- Redis ACL 用户管理。
- 数据备份恢复。

## 第五阶段：Node.js / Composer

实现：

- fnm。
- Node.js 多版本。
- npm。
- pnpm。
- Composer。
- React / Vite 项目支持。

## 第六阶段：全局生命周期

实现：

- `dev install --all`。
- `dev up`。
- `dev down`。
- `dev restart`。
- `dev start` / `dev stop`（指定服务批量启停）。
- `dev up/down/restart --only mysql,redis`。
- `dev uninstall <组件>` 批量卸载。
- `dev uninstall --all`。
- `dev purge logs`（默认仅清空日志）。
- `dev purge <data|config|state|backups>` 选择性清理。
- `dev purge --all`。
- `dev logs nginx[:access] / php[:版本|:slow] / mysql[:版本|:slow] / redis`。
- `dev help` 及二级帮助 `dev help php fpm`。
- 依赖管理。
- 启动顺序编排。
- 健康检查。
- 故障汇总。

## 第七阶段：完善与优化

实现：

- 配置回滚。
- 数据恢复。
- 自动诊断。
- 服务异常检测。
- 更完善的权限控制。
- 统一交互体验。
- 性能优化。

---

# 24. 最终命令清单

## 全局命令

```bash
dev help
dev help php
dev help php fpm
dev version
dev status
dev info
dev doctor

dev install --all
dev uninstall --all
dev uninstall nginx redis
dev uninstall php:8.3 mysql:8.4
dev purge logs
dev purge data config --yes
dev purge --all

dev up
dev down
dev restart
dev start mysql redis
dev stop redis
dev up --only mysql,redis

dev logs nginx
dev logs nginx:access -f
dev logs mysql
dev logs php:slow
dev logs redis

dev backup
dev restore
```

## 配置命令

```bash
dev config
dev config get MYSQL_PORT
dev config set MYSQL_PORT 3308
dev config reload
dev config validate
```

## PHP 命令

```bash
dev php install 8.5
dev php uninstall 8.3
dev php list
dev php switch 8.5
dev php current

dev php fpm start 8.5
dev php fpm stop 8.5
dev php fpm status
```

## PHP 扩展命令

```bash
dev ext search redis
dev ext install redis --php=8.5
dev ext enable redis --php=8.5
dev ext disable redis --php=8.5
dev ext uninstall redis --php=8.5
dev ext list --php=8.5
dev ext doctor --php=8.5
```

## Nginx 命令

```bash
dev nginx start
dev nginx stop
dev nginx restart
dev nginx reload
dev nginx status
dev nginx test
```

## MySQL 命令

```bash
dev mysql install 8.4
dev mysql switch 8.4
dev mysql upgrade 8.0 8.4

dev mysql start
dev mysql stop
dev mysql restart
dev mysql status

dev mysql password
dev mysql user create erp
dev mysql user password erp
dev mysql user list

# 属主用户不存在时自动创建（密码同用户名）
dev mysql database create erp --owner erp
dev mysql database list

dev mysql backup
dev mysql restore
```

## Redis 命令

```bash
dev redis install
dev redis start
dev redis stop
dev redis restart
dev redis status

dev redis password
dev redis user create erp

dev redis backup
dev redis restore
```

## 项目命令

```bash
dev project add erp
dev project remove erp
dev project list
dev project info erp

dev project php erp 8.5
dev project config erp

dev project start erp
dev project stop erp

dev project sync-env erp
```

---

# 25. 最终验收标准

## 基础环境

- [ ] 完全原生运行。
- [ ] 不依赖 Docker。
- [ ] 不依赖 OrbStack。
- [ ] 统一管理器正常运行。
- [ ] `.env` 配置正常加载。
- [ ] Keychain 密码管理正常。
- [ ] 所有目录统一管理。

## PHP

- [ ] PHP 8.1 可以独立安装。
- [ ] PHP 8.2 可以独立安装。
- [ ] PHP 8.3 可以独立安装。
- [ ] PHP 8.4 可以独立安装。
- [ ] PHP 8.5 可以独立安装。
- [ ] CLI 默认版本可以切换。
- [ ] 多版本 PHP-FPM 可以同时运行。
- [ ] 项目可以独立指定 PHP 版本。
- [ ] 每个版本有独立 php.ini。
- [ ] 每个版本有独立扩展。
- [ ] 扩展可以独立安装和卸载。
- [ ] 扩展兼容性可以检查。

## Nginx

- [ ] 一键安装。
- [ ] 一键启动和停止。
- [ ] 支持多个虚拟主机。
- [ ] 支持不同 PHP-FPM Socket。
- [ ] 自动生成项目配置。
- [ ] 支持配置检测和重载。

## MySQL

- [ ] 一键安装。
- [ ] 多版本独立管理。
- [ ] 数据目录与软件分离。
- [ ] 版本切换不丢失原数据。
- [ ] 支持备份和恢复。
- [ ] 支持数据库版本升级。
- [ ] 支持密码修改。
- [ ] 支持数据库用户管理。
- [ ] 卸载默认保留数据。

## Redis

- [ ] 一键安装。
- [ ] 数据持久化。
- [ ] 支持密码修改。
- [ ] 支持 ACL 用户管理。
- [ ] 支持备份和恢复。
- [ ] 卸载默认保留数据。

## 项目管理

- [ ] 项目目录统一配置。
- [ ] 支持多个项目。
- [ ] 支持不同 PHP 版本。
- [ ] 自动生成 Nginx 配置。
- [ ] 支持项目环境变量同步。
- [ ] 项目源码与管理器分离。

## 全局生命周期

- [ ] 一键安装整套环境。
- [ ] 一键启动所有服务。
- [ ] 一键停止所有服务。
- [ ] 一键重启所有服务。
- [ ] 一键卸载所有软件。
- [ ] 一键彻底清理。
- [ ] 服务依赖顺序正确。
- [ ] 启动失败有明确提示。
- [ ] 不会误删用户数据。

---

# 26. 最终设计原则

整套系统坚持以下原则：

1. **原生运行**：所有服务直接运行在 macOS。
2. **统一管理**：所有组件通过 `dev` 命令管理。
3. **一键操作**：整套环境支持一键安装、启动、停止、重启和卸载。
4. **配置集中**：全局配置使用 `.env`，项目配置独立管理。
5. **密码安全**：敏感密码使用 macOS Keychain。
6. **版本隔离**：PHP、MySQL 等支持独立版本管理。
7. **数据持久化**：软件安装目录与数据目录分离。
8. **项目隔离**：不同项目可以使用不同 PHP 版本和数据库账号。
9. **按需启动**：不需要的服务不启动。
10. **安全卸载**：普通卸载不删除用户数据。
11. **可恢复**：配置和数据支持备份恢复。
12. **可扩展**：采用 Provider 架构，方便以后增加组件。
13. **自动化**：尽可能自动处理安装、配置、启动和诊断。

最终目标是构建一套适合 Apple Silicon Mac 的原生开发环境管理系统。

日常只需要：

```bash
# 开始开发
dev up

# 查看状态
dev status

# 结束开发
dev down
```

所有底层软件版本、项目配置、数据库、缓存和服务生命周期，都由管理器统一维护。