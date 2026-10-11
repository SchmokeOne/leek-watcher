"""Compatibility entry point. Original source is in upstream; UI changes are extensions."""
import sys
from dashboard_adapter import engine

if __name__ == '__main__':
    engine.main()
else:
    sys.modules[__name__] = engine
