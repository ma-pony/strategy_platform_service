"""freqtrade 集成层。

封装所有 freqtrade 交互，对上层服务暴露简单接口。
内部处理子进程调用和进程池信号获取，不向上泄漏引擎细节。

模块结构：
  - exceptions.py   freqtrade 专用异常类
  - runner.py       配置生成与目录清理工具
  - backtester.py   回测子进程封装
  - signal_fetcher.py 信号获取进程池封装
"""
