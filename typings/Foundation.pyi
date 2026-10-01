# Minimal stub for PyObjC's Foundation framework, whose symbols are generated
# dynamically at runtime and so are invisible to static analysis. Treat every
# attribute as Any instead of reporting unknown-import errors.
from typing import Any

def __getattr__(name: str) -> Any: ...
