"""h42-mesh agent: configures and drives the tunnels and routing of a router."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("h42-mesh-agent")
except PackageNotFoundError:  # source tree not installed
    __version__ = "0.0.0"
