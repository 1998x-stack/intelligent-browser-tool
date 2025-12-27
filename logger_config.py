"""
日志配置模块 - 基于loguru的统一日志系统

设计理念 (CleanRL哲学):
- 单文件自包含: 日志配置独立完整
- 透明的处理流程: 日志格式清晰可读
- 最小化抽象: 直接使用loguru，无过度封装
- 便于调试: 多级别日志，支持文件和控制台输出
"""

import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from loguru import logger

# ============================================================================
# 日志格式定义
# ============================================================================

# 控制台日志格式 (彩色)
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# 文件日志格式 (纯文本)
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} | "
    "{message}"
)

# 简洁格式 (用于进度显示)
SIMPLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)


# ============================================================================
# 日志配置函数
# ============================================================================

def setup_logger(
    log_dir: Optional[Path] = None,
    log_level: str = "DEBUG",
    console_level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "7 days",
    enable_file: bool = True,
    enable_console: bool = True,
    module_name: str = "web_automation"
) -> None:
    """
    配置日志系统
    
    Args:
        log_dir: 日志文件目录
        log_level: 文件日志级别
        console_level: 控制台日志级别
        rotation: 日志轮转大小
        retention: 日志保留时间
        enable_file: 是否启用文件日志
        enable_console: 是否启用控制台日志
        module_name: 模块名称
    """
    # 移除默认处理器
    logger.remove()
    
    # 控制台处理器
    if enable_console:
        logger.add(
            sys.stderr,
            format=CONSOLE_FORMAT,
            level=console_level,
            colorize=True,
            enqueue=True  # 异步写入，提高性能
        )
    
    # 文件处理器
    if enable_file and log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 主日志文件
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"{module_name}_{timestamp}.log"
        
        logger.add(
            str(log_file),
            format=FILE_FORMAT,
            level=log_level,
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
            enqueue=True
        )
        
        # 错误日志单独文件
        error_file = log_dir / f"{module_name}_error_{timestamp}.log"
        logger.add(
            str(error_file),
            format=FILE_FORMAT,
            level="ERROR",
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
            enqueue=True
        )
    
    logger.info(f"日志系统初始化完成 (控制台级别: {console_level}, 文件级别: {log_level})")


def get_logger(name: str = None):
    """
    获取带有上下文的logger
    
    Args:
        name: 模块名称
        
    Returns:
        配置好的logger实例
    """
    if name:
        return logger.bind(name=name)
    return logger


# ============================================================================
# 日志装饰器
# ============================================================================

def log_function_call(func):
    """
    函数调用日志装饰器
    
    记录函数的调用和返回，用于调试
    """
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.debug(f"调用函数: {func_name}")
        logger.debug(f"  参数: args={args}, kwargs={kwargs}")
        
        try:
            result = func(*args, **kwargs)
            logger.debug(f"  返回: {type(result).__name__}")
            return result
        except Exception as e:
            logger.error(f"  异常: {e}")
            raise
    
    return wrapper


def log_time(func):
    """
    函数执行时间日志装饰器
    """
    from functools import wraps
    import time
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start_time
        logger.debug(f"{func.__name__} 执行时间: {elapsed:.2f}秒")
        return result
    
    return wrapper


# ============================================================================
# 进度日志
# ============================================================================

class ProgressLogger:
    """
    进度日志记录器
    
    用于记录爬取进度，显示当前状态
    """
    
    def __init__(self, total: int, desc: str = "进度"):
        """
        初始化进度记录器
        
        Args:
            total: 总数
            desc: 描述文本
        """
        self.total = total
        self.current = 0
        self.desc = desc
        self.start_time = datetime.now()
    
    def update(self, n: int = 1, message: str = ""):
        """
        更新进度
        
        Args:
            n: 增加的数量
            message: 附加消息
        """
        self.current += n
        progress = (self.current / self.total) * 100 if self.total > 0 else 0
        
        elapsed = (datetime.now() - self.start_time).total_seconds()
        speed = self.current / elapsed if elapsed > 0 else 0
        
        eta = (self.total - self.current) / speed if speed > 0 else 0
        
        log_message = (
            f"{self.desc}: {self.current}/{self.total} ({progress:.1f}%) | "
            f"速度: {speed:.2f}/s | 剩余: {eta:.0f}s"
        )
        
        if message:
            log_message += f" | {message}"
        
        logger.info(log_message)
    
    def finish(self):
        """完成进度"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        logger.success(f"{self.desc}完成! 总计: {self.current}, 耗时: {elapsed:.2f}秒")


# ============================================================================
# 日志上下文管理
# ============================================================================

class LogContext:
    """
    日志上下文管理器
    
    用于在特定代码块添加上下文信息
    """
    
    def __init__(self, context_name: str, **extra):
        """
        初始化上下文
        
        Args:
            context_name: 上下文名称
            **extra: 额外的上下文信息
        """
        self.context_name = context_name
        self.extra = extra
    
    def __enter__(self):
        logger.info(f"开始: {self.context_name}")
        if self.extra:
            logger.debug(f"上下文: {self.extra}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            logger.error(f"失败: {self.context_name} - {exc_val}")
        else:
            logger.success(f"完成: {self.context_name}")
        return False


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    from pathlib import Path
    
    # 测试日志配置
    test_log_dir = Path("./test_logs")
    setup_logger(log_dir=test_log_dir, console_level="DEBUG")
    
    # 测试各级别日志
    logger.debug("这是一条DEBUG日志")
    logger.info("这是一条INFO日志")
    logger.success("这是一条SUCCESS日志")
    logger.warning("这是一条WARNING日志")
    logger.error("这是一条ERROR日志")
    
    # 测试进度日志
    print("\n测试进度日志:")
    progress = ProgressLogger(total=5, desc="测试进度")
    for i in range(5):
        import time
        time.sleep(0.1)
        progress.update(1, f"处理项目 {i+1}")
    progress.finish()
    
    # 测试上下文管理
    print("\n测试上下文管理:")
    with LogContext("测试任务", url="https://example.com"):
        logger.info("执行任务中...")
    
    # 测试装饰器
    print("\n测试装饰器:")
    
    @log_function_call
    @log_time
    def test_function(x, y):
        import time
        time.sleep(0.1)
        return x + y
    
    result = test_function(1, 2)
    print(f"结果: {result}")
    
    # 清理测试目录
    import shutil
    if test_log_dir.exists():
        shutil.rmtree(test_log_dir)
    
    print("\n日志模块测试完成!")