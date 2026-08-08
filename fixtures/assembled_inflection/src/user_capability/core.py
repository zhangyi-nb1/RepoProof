"""用户能力 seam:AI 的适配代码经 REPOPROOF_ADAPTATION_DIR 注入。"""
import importlib.util
import os
from pathlib import Path


def _adapter():
    root = os.environ.get("REPOPROOF_ADAPTATION_DIR", "")
    cand = Path(root) / "adapter.py" if root else None
    if cand and cand.exists():
        spec = importlib.util.spec_from_file_location("user_adapter", cand)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


def run(value):
    mod = _adapter()
    if mod is None:
        raise NotImplementedError("尚无适配代码(direct 模式不实现该能力)")
    return mod.run(value)


def health():
    return "ok"
