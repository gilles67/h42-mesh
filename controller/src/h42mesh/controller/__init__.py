"""h42-mesh controller: API that configures the mesh network."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("h42-mesh-controller")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"
