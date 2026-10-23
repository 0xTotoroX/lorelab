"""LoreHub 旧导入名；与 lorelab.components 共用同一个模块。"""

import sys

from lorelab import components as _implementation

sys.modules[__name__] = _implementation
