"""
配置管理模块 - 集中管理所有系统配置

设计理念 (CleanRL哲学):
- 单文件自包含: 所有配置集中在一个文件
- 透明的处理流程: 配置项清晰可见
- 最小化抽象: 直接使用dataclass，无复杂继承
- 便于调试: 支持配置打印和验证
"""

import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
from datetime import datetime

# ============================================================================
# 错误处理工具
# ============================================================================

def get_err_message() -> str:
    """获取详细的错误信息"""
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message


# ============================================================================
# 配置数据类
# ============================================================================

@dataclass
class BrowserConfig:
    """浏览器配置"""
    browser_type: str = "chrome"
    headless: bool = True
    page_load_timeout: int = 30
    implicit_wait: int = 10
    request_delay: float = 1.0
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # Chrome选项
    chrome_options: List[str] = field(default_factory=lambda: [
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-extensions',
        '--disable-infobars',
        '--window-size=1920,1080',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ])
    
    # 域名限制
    allowed_domains: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=lambda: [
        '/login', '/logout', '/signin', '/signout',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.zip', '.tar', '.gz', '.rar',
        '.jpg', '.jpeg', '.png', '.gif', '.svg',
        'javascript:', 'mailto:', 'tel:'
    ])


@dataclass
class LLMConfig:
    """LLM配置 (Ollama)"""
    base_url: str = "http://localhost:11434"
    
    # 模型配置
    intent_model: str = "qwen3:1.7b"      # 意图转换模型
    fast_model: str = "qwen3:0.6b"        # 快速处理模型 (意图匹配、命名)
    analysis_model: str = "qwen3:1.7b"    # 内容分析模型
    
    # 生成参数
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 60
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class ContentConfig:
    """内容提取配置"""
    # Trafilatura配置
    include_comments: bool = False
    include_tables: bool = True
    include_links: bool = True
    include_images: bool = False
    favor_precision: bool = True
    favor_recall: bool = False
    
    # 分块配置
    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_chunk_size: int = 100
    
    # URL配置
    max_urls_per_page: int = 20
    max_crawl_depth: int = 3


@dataclass
class StorageConfig:
    """存储配置"""
    base_dir: Path = field(default_factory=lambda: Path("./outputs"))
    
    # 子目录结构
    raw_dir: str = "raw"
    processed_dir: str = "processed"
    reports_dir: str = "reports"
    logs_dir: str = "logs"
    
    # 文件命名
    timestamp_format: str = "%Y%m%d_%H%M%S"
    
    def __post_init__(self):
        """初始化后创建目录结构"""
        self.base_dir = Path(self.base_dir)
        
    @property
    def raw_path(self) -> Path:
        return self.base_dir / self.raw_dir
    
    @property
    def processed_path(self) -> Path:
        return self.base_dir / self.processed_dir
    
    @property
    def reports_path(self) -> Path:
        return self.base_dir / self.reports_dir
    
    @property
    def logs_path(self) -> Path:
        return self.base_dir / self.logs_dir
    
    def create_dirs(self):
        """创建所有必要的目录"""
        for path in [self.raw_path, self.processed_path, 
                     self.reports_path, self.logs_path]:
            path.mkdir(parents=True, exist_ok=True)
    
    def get_timestamp(self) -> str:
        """获取当前时间戳字符串"""
        return datetime.now().strftime(self.timestamp_format)


@dataclass
class CrawlConfig:
    """爬取配置"""
    # 默认值
    default_url: str = "https://www.stanford.edu"
    default_intent: str = "招生信息"
    
    # 爬取限制
    max_pages: int = 50
    max_depth: int = 3
    concurrent_requests: int = 1
    
    # 超时设置
    page_timeout: int = 30
    total_timeout: int = 3600  # 1小时


@dataclass
class Config:
    """
    主配置类 - 聚合所有子配置
    
    使用方式:
        config = Config()
        config.browser.headless = False
        config.llm.temperature = 0.5
    """
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    content: ContentConfig = field(default_factory=ContentConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    
    # 运行模式
    debug: bool = False
    verbose: bool = True
    use_selenium: bool = True  # True=Selenium, False=Requests
    
    def __post_init__(self):
        """初始化后的处理"""
        self.storage.create_dirs()
    
    def validate(self) -> bool:
        """验证配置有效性"""
        errors = []
        
        # 验证LLM配置
        if not self.llm.base_url:
            errors.append("LLM base_url不能为空")
        
        # 验证存储配置
        if not self.storage.base_dir:
            errors.append("存储base_dir不能为空")
        
        # 验证爬取配置
        if self.crawl.max_pages < 1:
            errors.append("max_pages必须大于0")
        
        if errors:
            for err in errors:
                print(f"配置错误: {err}")
            return False
        
        return True
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        from dataclasses import asdict
        return asdict(self)
    
    def print_config(self):
        """打印当前配置"""
        import json
        
        # 转换Path为字符串
        config_dict = self.to_dict()
        config_dict['storage']['base_dir'] = str(self.storage.base_dir)
        
        print("=" * 60)
        print("当前配置:")
        print("=" * 60)
        print(json.dumps(config_dict, indent=2, ensure_ascii=False))
        print("=" * 60)


# ============================================================================
# 意图类别定义
# ============================================================================

class IntentCategory:
    """意图类别常量"""
    CONTENT = "content"          # 内容获取
    DATA = "data"                # 数据提取
    EMAIL = "email"              # 邮件信息
    POLICY = "policy"            # 政策规定
    CONTACT = "contact"          # 联系方式
    ADMISSION = "admission"      # 招生信息
    RESEARCH = "research"        # 研究信息
    NEWS = "news"                # 新闻资讯
    EVENT = "event"              # 活动信息
    GENERAL = "general"          # 通用信息
    
    @classmethod
    def all_categories(cls) -> List[str]:
        """获取所有类别"""
        return [
            cls.CONTENT, cls.DATA, cls.EMAIL, cls.POLICY,
            cls.CONTACT, cls.ADMISSION, cls.RESEARCH,
            cls.NEWS, cls.EVENT, cls.GENERAL
        ]


# ============================================================================
# URL优先级定义
# ============================================================================

class URLPriority:
    """URL优先级常量"""
    HIGH = 1      # 高优先级
    MEDIUM = 2    # 中等优先级
    LOW = 3       # 低优先级
    
    @classmethod
    def from_int(cls, value: int) -> int:
        """从整数值获取优先级"""
        if value <= 1:
            return cls.HIGH
        elif value == 2:
            return cls.MEDIUM
        else:
            return cls.LOW


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    # 测试配置
    config = Config()
    config.print_config()
    
    print("\n验证配置...")
    if config.validate():
        print("配置验证通过!")
    else:
        print("配置验证失败!")
    
    print("\n意图类别:", IntentCategory.all_categories())
    print("URL优先级:", [URLPriority.HIGH, URLPriority.MEDIUM, URLPriority.LOW])
