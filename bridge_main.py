"""打包后的桥接入口（WolverineDS5-bridge.exe）：--pc 走 Sensa 握把，否则走 Xbox 模式四马达。"""
import os
import sys

import gip_bridge

if __name__ == "__main__":
    # capture 按相对路径启动；打包后它和 SDL3.dll 都在 _internal（sys._MEIPASS）。
    os.chdir(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
    if "--pc" in sys.argv[1:]:
        import pc_bridge
        sys.exit(gip_bridge.run(pc_bridge.main))
    sys.exit(gip_bridge.run())
