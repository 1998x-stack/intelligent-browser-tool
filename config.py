"""
配置文件 - 所有可配置参数的中心化管理

设计理念:
- 单一数据类，包含所有配置
- 使用dataclass减少样板代码
- 提供合理的默认值
- 支持从环境变量和文件加载

参考: CleanRL配置哲学
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path
import os
import json


@dataclass
class OllamaConfig:
    """Ollama模型配置"""
    host: str = "http://localhost:11434"
    small_model: str = "qwen2.5:0.5b"  # 分类和意图判断
    large_model: str = "qwen2.5:0.5b"    # 内容分析和提取
    temperature: float = 0.1           # 低温度保证稳定性
    max_tokens: int = 2048
    timeout: int = 60


@dataclass
class SeleniumConfig:
    """Selenium浏览器配置"""
    headless: bool = True
    browser_type: str = "chrome"
    page_load_timeout: int = 30
    implicit_wait: int = 10
    scroll_pause: float = 1.0
    max_scroll_attempts: int = 5
    
    # Chrome特定选项
    chrome_options: List[str] = field(default_factory=lambda: [
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-extensions',
        '--disable-infobars',
        '--window-size=1920,1080',
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    ])


@dataclass
class TrafilaturaConfig:
    """Trafilatura内容提取配置"""
    extract_comments: bool = False
    include_links: bool = True
    include_images: bool = True
    include_tables: bool = True
    output_format: str = "json"
    min_text_length: int = 100
    max_text_length: int = 10000
    favor_recall: bool = False
    favor_precision: bool = True


@dataclass
class CrawlConfig:
    """爬取策略配置"""
    max_pages: int = 50
    max_depth: int = 3
    request_delay: float = 1.5
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # URL过滤
    allowed_domains: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=lambda: [
        '/login', '/logout', '/signin', '/signup',
        '/search', '/cart', '/checkout',
        '.pdf', '.jpg', '.png', '.gif', '.zip',
        '/calendar', '/map', '/sitemap',
        '#', 'javascript:', 'mailto:', 'tel:'
    ])
    
    # 优先URL模式
    priority_patterns: List[str] = field(default_factory=lambda: [
        '/admission', '/apply', '/international',
        '/program', '/degree', '/graduate', '/undergraduate',
        '/research', '/faculty', '/about'
    ])


@dataclass
class StorageConfig:
    """数据存储配置"""
    base_dir: str = "./output"
    raw_dir: str = "01_raw"           # 原始HTML
    extracted_dir: str = "02_extracted"  # 提取的内容
    analyzed_dir: str = "03_analyzed"    # AI分析结果
    reports_dir: str = "04_reports"      # 最终报告
    
    # 缓存
    enable_cache: bool = True
    cache_dir: str = ".cache"
    cache_ttl: int = 3600  # 秒


@dataclass
class Config:
    """
    全局配置类 - 聚合所有配置模块
    
    使用示例:
        config = Config()
        config = Config.from_file("config.json")
        config = Config.for_stanford()
    """
    
    # 子配置
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    selenium: SeleniumConfig = field(default_factory=SeleniumConfig)
    trafilatura: TrafilaturaConfig = field(default_factory=TrafilaturaConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    
    # 任务配置
    task_name: str = "browser_crawl"
    start_url: str = ""
    user_intent: str = ""
    
    # 日志配置
    log_level: str = "INFO"
    log_file: str = "browser_tool.log"
    
    def __post_init__(self):
        """初始化后验证和设置"""
        self._validate()
        self._setup_directories()
    
    def _validate(self):
        """验证配置参数"""
        assert self.ollama.temperature >= 0 and self.ollama.temperature <= 2, \
            "温度应在 0-2 之间"
        assert self.crawl.max_pages > 0, "最大页面数必须大于0"
        assert self.crawl.max_depth > 0, "最大深度必须大于0"
        assert self.selenium.browser_type in ["chrome", "firefox", "edge"], \
            f"不支持的浏览器类型: {self.selenium.browser_type}"
    
    def _setup_directories(self):
        """创建必要的目录结构"""
        base = Path(self.storage.base_dir)
        for dir_name in [
            self.storage.raw_dir,
            self.storage.extracted_dir,
            self.storage.analyzed_dir,
            self.storage.reports_dir,
            self.storage.cache_dir
        ]:
            (base / dir_name).mkdir(parents=True, exist_ok=True)
    
    def get_storage_path(self, stage: str, filename: str) -> Path:
        """获取存储路径"""
        stage_map = {
            'raw': self.storage.raw_dir,
            'extracted': self.storage.extracted_dir,
            'analyzed': self.storage.analyzed_dir,
            'reports': self.storage.reports_dir,
            'cache': self.storage.cache_dir
        }
        return Path(self.storage.base_dir) / stage_map.get(stage, '') / filename
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'ollama': {
                'host': self.ollama.host,
                'small_model': self.ollama.small_model,
                'large_model': self.ollama.large_model,
                'temperature': self.ollama.temperature
            },
            'selenium': {
                'headless': self.selenium.headless,
                'browser_type': self.selenium.browser_type,
                'page_load_timeout': self.selenium.page_load_timeout
            },
            'trafilatura': {
                'include_links': self.trafilatura.include_links,
                'max_text_length': self.trafilatura.max_text_length
            },
            'crawl': {
                'max_pages': self.crawl.max_pages,
                'max_depth': self.crawl.max_depth,
                'allowed_domains': self.crawl.allowed_domains
            },
            'task': {
                'task_name': self.task_name,
                'start_url': self.start_url,
                'user_intent': self.user_intent
            }
        }
    
    @classmethod
    def from_file(cls, filepath: str) -> 'Config':
        """从JSON文件加载配置"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        config = cls()
        
        # 更新Ollama配置
        if 'ollama' in data:
            for k, v in data['ollama'].items():
                if hasattr(config.ollama, k):
                    setattr(config.ollama, k, v)
        
        # 更新其他配置...
        if 'crawl' in data:
            for k, v in data['crawl'].items():
                if hasattr(config.crawl, k):
                    setattr(config.crawl, k, v)
        
        if 'task' in data:
            config.task_name = data['task'].get('task_name', config.task_name)
            config.start_url = data['task'].get('start_url', config.start_url)
            config.user_intent = data['task'].get('user_intent', config.user_intent)
        
        return config
    
    def save_to_file(self, filepath: str):
        """保存配置到JSON文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ============ 预定义配置模板 ============

def get_stanford_config() -> Config:
    """Stanford大学专用配置"""
    config = Config()
    config.crawl.allowed_domains = ["stanford.edu"]
    config.crawl.priority_patterns = [
        '/admission', '/apply', '/international',
        '/graduate', '/undergraduate', '/programs',
        '/financial-aid', '/tuition', '/housing'
    ]
    config.task_name = "stanford_crawl"
    config.start_url = "https://www.stanford.edu/"
    return config


def get_fast_config() -> Config:
    """快速模式配置 - 适合测试"""
    config = Config()
    config.selenium.headless = True
    config.selenium.page_load_timeout = 15
    config.crawl.max_pages = 10
    config.crawl.max_depth = 2
    config.crawl.request_delay = 0.5
    config.trafilatura.max_text_length = 5000
    return config


def get_deep_config() -> Config:
    """深度分析配置 - 详细提取"""
    config = Config()
    config.crawl.max_pages = 100
    config.crawl.max_depth = 5
    config.trafilatura.extract_comments = True
    config.trafilatura.include_tables = True
    config.trafilatura.max_text_length = 20000
    config.trafilatura.favor_recall = True
    return config


if __name__ == "__main__":
    # 测试配置
    config = get_stanford_config()
    print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))