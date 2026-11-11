"""TEK Runtime — Kaggle-side QEMU session manager."""
from .main import main
from .session import stop_active_session

__all__ = ["main", "stop_active_session"]
__version__ = "0.1.0"
