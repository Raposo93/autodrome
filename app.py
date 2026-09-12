"""Compatibility import for development; production uses ``autodrome``."""

from autodrome.web import app, conf, lifespan


__all__ = ["app", "conf", "lifespan"]
