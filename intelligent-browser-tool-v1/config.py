"""
配置文件 - 所有可配置参数的中心化管理

设计理念:
- 单一数据类,包含所有配置
- 使用dataclass减少样板代码
- 提供合理的默认值
"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Config:
    """
    全局配置类 - 使用dataclass简化配置管理
    """
    
    # ============ Ollama 配置 ============
    ollama_host: str = "http://localhost:11434"
    small_model: str = "qwen3:0.6b"  # 用于分类和意图判断
    large_model: str = "qwen3:1.7b"    # 用于内容分析和提取
    
    # ============ Selenium 配置 ============
    headless: bool = False  # 是否使用无头模式
    browser_type: str = "chrome"  # chrome, firefox, edge
    page_load_timeout: int = 10  # 页面加载超时(秒)
    implicit_wait: int = 5  # 隐式等待时间(秒)
    
    # Chrome特定选项
    chrome_options: List[str] = field(default_factory=lambda: [
        '--disable-blink-features=AutomationControlled',  # 反检测
        '--disable-dev-shm-usage',  # 避免共享内存问题
        '--no-sandbox',  # 沙箱模式(Docker中需要)
        '--disable-gpu',  # 禁用GPU
    ])
    
    # ============ Trafilatura 配置 ============
    extract_comments: bool = False  # 是否提取评论
    include_links: bool = True  # 是否包含链接
    include_images: bool = True  # 是否包含图片
    output_format: str = "python"  # python, json, xml, txt
    
    # 内容提取选项
    min_text_length: int = 100  # 最小文本长度
    max_text_length: int = 10000  # 最大文本长度(用于分块)
    
    # ============ AI 分析配置 ============
    # 分类阈值
    classification_confidence_threshold: float = 0.6
    
    # 页面分类类型
    page_categories: List[str] = field(default_factory=lambda: [
        "academic_program",  # 学术项目
        "research",          # 研究内容
        "news",              # 新闻
        "event",             # 活动
        "faculty",           # 教职员工
        "admission",         # 招生
        "general_info",      # 一般信息
        "navigation"         # 导航页面
    ])
    
    # 值得深入分析的类别
    extract_categories: List[str] = field(default_factory=lambda: [
        "academic_program",
        "research",
        "faculty"
    ])
    
    # ============ URL 过滤配置 ============
    # 允许的域名(留空则允许所有)
    allowed_domains: List[str] = field(default_factory=lambda: [
        "stanford.edu"
    ])
    
    # 排除的URL模式
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "/login",
        "/logout",
        "/search",
        ".pdf",
        ".jpg",
        ".png",
        ".gif",
        "/calendar",
        "/map"
    ])
    
    # ============ 性能配置 ============
    max_retries: int = 1  # 最大重试次数
    retry_delay: int = 1  # 重试延迟(秒)
    request_delay: float = 1.0  # 请求间隔(秒)
    
    # ============ 缓存配置 ============
    enable_cache: bool = True
    cache_dir: str = ".cache"
    
    def __post_init__(self):
        """初始化后验证配置"""
        # 验证模型名称格式
        assert ":" in self.small_model, "模型名称应包含版本,如 qwen3:0.6b"
        assert ":" in self.large_model, "模型名称应包含版本,如 qwen3:1.7b"
        
        # 验证阈值范围
        assert 0 <= self.classification_confidence_threshold <= 1, \
            "置信度阈值应在 0-1 之间"
        
        # 验证浏览器类型
        assert self.browser_type in ["chrome", "firefox", "edge"], \
            f"不支持的浏览器类型: {self.browser_type}"
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'ollama': {
                'host': self.ollama_host,
                'small_model': self.small_model,
                'large_model': self.large_model
            },
            'selenium': {
                'headless': self.headless,
                'browser_type': self.browser_type,
                'page_load_timeout': self.page_load_timeout
            },
            'trafilatura': {
                'extract_comments': self.extract_comments,
                'include_links': self.include_links,
                'output_format': self.output_format
            }
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'Config':
        """从字典创建配置对象"""
        # 展平嵌套字典
        flat_dict = {}
        for section, params in config_dict.items():
            if isinstance(params, dict):
                flat_dict.update(params)
        return cls(**flat_dict)


# ============ 预定义配置模板 ============

def get_stanford_config() -> Config:
    """Stanford大学专用配置"""
    return Config(
        allowed_domains=["stanford.edu"],
        page_categories=[
            "academic_program",
            "research",
            "faculty",
            "admission",
            "news"
        ],
        extract_categories=["academic_program", "research", "faculty"]
    )


def get_fast_config() -> Config:
    """快速模式配置 - 适合测试"""
    return Config(
        headless=True,
        page_load_timeout=15,
        max_text_length=5000,
        request_delay=0.5
    )


def get_deep_config() -> Config:
    """深度分析配置 - 详细提取"""
    return Config(
        extract_comments=True,
        include_links=True,
        include_images=True,
        min_text_length=50,
        max_text_length=20000
    )