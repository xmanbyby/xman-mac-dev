"""服务依赖与启动编排顺序。"""

SERVICE_ORDER = ["mysql", "redis", "php", "nginx"]
DEPENDENCIES = {
    "nginx": ["php"],
    "php": [],
    "mysql": [],
    "redis": [],
    "node": [],
    "composer": [],
}


def startup_order(only=None):
    order = list(SERVICE_ORDER)
    if only:
        wanted = {item.strip() for item in only if item.strip()}
        order = [name for name in order if name in wanted]
    return order


def stop_order():
    return list(reversed(SERVICE_ORDER))
