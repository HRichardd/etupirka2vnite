"""Etupirka → Vnite 迁移助手。

阶段 0 只包含数据层：定位并只读读取 Etupirka 的 ``user.db``。
界面（阶段 1）会直接调用 :mod:`app.etupirka_db`。
"""

__version__ = "0.1.1"
