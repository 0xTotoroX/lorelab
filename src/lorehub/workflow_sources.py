"""旧 LoreHub 模块兼容入口；唯一实现位于 soota.knowledge.workflow_sources。"""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("soota.knowledge.workflow_sources")
