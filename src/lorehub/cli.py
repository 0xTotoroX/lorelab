"""旧 LoreHub 命令与 Python 入口，委派到 LoreLab。"""

import importlib
import sys

implementation = importlib.import_module("lorelab.cli")
if __name__ == "__main__":
    raise SystemExit(implementation.main())
sys.modules[__name__] = implementation
