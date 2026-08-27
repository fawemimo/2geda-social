default_app_config = "config.apps.ConfigConfig"


def __getattr__(name):
    if name in ("get_config", "get_int", "get_bool", "get_str", "invalidate_cache",
                "all_effective"):
        from config import runtime

        return getattr(runtime, name)
    raise AttributeError(name)
