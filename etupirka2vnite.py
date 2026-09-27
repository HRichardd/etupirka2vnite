"""GUI 入口。

源码运行::

    python etupirka2vnite.py              启动界面
    python etupirka2vnite.py --selfcheck  把运行环境写成 selfcheck.txt 后退出

打包后双击 ``dist\\etupirka2vnite.exe`` 即可；``--selfcheck`` 在没有控制台的
``--windowed`` exe 里同样可用，因为它只写文件、不打印。
"""

import sys

from app import selfcheck
from app.gui import main as gui_main


def run(argv):
    if "--selfcheck" in argv:
        return selfcheck.main(argv)
    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
