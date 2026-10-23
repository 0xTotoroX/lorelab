"""LoreHub 旧导入名；与 lorelab.runtime 共用同一个模块。"""

import sys

from lorelab import runtime as _implementation

sys.modules[__name__] = _implementation
