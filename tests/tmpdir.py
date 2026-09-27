"""测试用临时目录。

刻意建在工程目录下的 ``.testtmp/``，而不是系统临时目录：

* 受限环境（沙箱、只读的 %TEMP%）下也能跑；
* 出问题时残留文件就在眼前，不用去翻 ``%TEMP%``。

**不用 ``tempfile.TemporaryDirectory``**：它以 ``mode=0o700`` 建目录，在 Windows
受限环境下会建出一个连当前进程都无法进入的目录（写文件、``os.scandir``、
``shutil.rmtree`` 全部 ``PermissionError``）。实测 ``os.mkdir`` 的默认模式和
``0o777`` 都正常，只有 ``0o700`` 会出问题，所以这里自己建。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / ".testtmp"


class TempDir:
    """最小可用的临时目录，接口对齐 ``tempfile.TemporaryDirectory``。"""

    def __init__(self, prefix: str = "t") -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        self.path = BASE / (prefix + uuid.uuid4().hex[:10])
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "TempDir":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()


def make_temp_dir(prefix: str = "t") -> TempDir:
    return TempDir(prefix)


def cleanup_base() -> None:
    """把整个 ``.testtmp/`` 清掉。"""
    shutil.rmtree(BASE, ignore_errors=True)
