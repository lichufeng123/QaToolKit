from __future__ import annotations


class FastMCP:
    def __init__(self, name: str):
        self.name = name

    def tool(self):
        def decorator(func):
            return func

        return decorator

    def resource(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    def prompt(self):
        def decorator(func):
            return func

        return decorator

    def run(self, *args, **kwargs):
        raise RuntimeError("FastMCP stub does not support run() in this environment")
