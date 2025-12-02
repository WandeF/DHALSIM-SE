"""
未来扩展计划（挂在 middleware 里）：

1. OpenPLC 集成：
   - 将 state 中的传感器值写入 OpenPLC 对应寄存器
   - 从 OpenPLC 中读取执行器控制命令，填充到 commands

2. ns-3 网络仿真：
   - state/commands 在进入/离开 PLC/SCADA 之前，先调用 ns-3 计算网络时延/丢包
   - 使用事件队列或异步机制模拟消息到达时间

3. SCADA 逻辑：
   - 聚合多台 PLC 数据
   - 做高层调度决策（setpoint 下发）
   - 记录历史数据、告警
"""

from typing import Any, Dict


def middleware(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    CPS 中间层占位函数。
    当前阶段：
      - 不做任何复杂逻辑
      - 直接返回一个“默认控制命令”（例如全不动）
    未来将扩展为：
      1. 从 state 中抽取传感器数据
      2. 调用 OpenPLC 读取/写入寄存器
      3. 通过 ns-3 模拟网络延迟/丢包
      4. SCADA 收集/聚合数据并生成控制命令

    输入:
      state: 物理世界当前状态快照

    输出:
      commands: 控制命令 dict，格式与 ClosedLoopPhysicalSimulator.apply_actuator_commands 一致
    """
    # TODO: 未来扩展为真正的 CPS 中间逻辑
    commands: Dict[str, Any] = {
        "pumps": {},
        "valves": {},
    }
    return commands
