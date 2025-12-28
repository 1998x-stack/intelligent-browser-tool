#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web Automation Tool / 网页自动化工具

基于Ollama LLM、Selenium/Requests和Trafilatura的智能网页爬取与分析工具。
A smart web crawling and analysis tool powered by Ollama LLM, Selenium/Requests, 
and Trafilatura.

设计原则 (Design Principles):
- CleanRL哲学: 单文件自包含、透明处理流程、最小化抽象、便于调试
- 模块化设计: 各模块独立工作,通过清晰接口交互
- 多模型策略: qwen3:0.6b快速任务, qwen3:1.7b复杂分析

Modules:
    - config: Configuration management
    - logger_config: Logging configuration  
    - utils: Utility functions
    - llm_client: Ollama API wrapper
    - browser_engine: Selenium/Requests browser (optimized with PageLoadStrategy)
    - content_extractor: Trafilatura extraction
    - intent_analyzer: Intent to prompt components
    - content_analyzer: LLM content analysis
    - file_namer: Semantic file naming
    - url_queue: Priority queue management
    - storage_manager: Data persistence
    - report_generator: Markdown/JSON reports
    - search_engine: Search query generation and web search
    - crawler: Main orchestrator

Example:
    >>> from web_automation import WebCrawler, CrawlConfig
    >>> config = CrawlConfig(
    ...     start_url="https://www.stanford.edu/",
    ...     intent="招生信息",
    ...     use_search_seeds=True  # 启用搜索引擎种子生成
    ... )
    >>> crawler = WebCrawler(config)
    >>> summary = crawler.run()

Author: AI Assistant
Date: 2024
Version: 1.1.0
"""

__version__ = "1.1.0"
__author__ = "AI Assistant"

# Core components
from .config import Config, BrowserConfig, LLMConfig, ContentConfig, StorageConfig
from .config import CrawlConfig as BaseCrawlConfig, IntentCategory, URLPriority

# Logging
from .logger_config import setup_logger, ProgressLogger, LogContext

# Utilities
from .utils import (
    normalize_url, extract_domain, is_same_domain,
    clean_text, truncate_text, chunk_text,
    extract_emails, extract_phones, extract_json_from_text,
    safe_write_file, safe_read_file, safe_write_json, safe_read_json
)

# LLM
from .llm_client import LLMClient, LLMResponse

# Browser (Optimized with PageLoadStrategy, undetected-chromedriver support)
from .browser_engine import (
    create_browser_engine, 
    SeleniumEngine, 
    RequestsEngine,
    HybridEngine,
    FetchResult
)

# Content Extraction
from .content_extractor import ContentExtractor, ExtractedContent, ExtractedLink

# Intent Analysis
from .intent_analyzer import IntentAnalyzer, IntentComponents, MatchedIntent

# Content Analysis
from .content_analyzer import ContentAnalyzer, AnalysisResult, PrioritizedURL

# File Naming
from .file_namer import FileNamer

# URL Queue
from .url_queue import URLQueue, QueueItem, QueueStats

# Storage
from .storage_manager import StorageManager

# Report Generation
from .report_generator import ReportGenerator, CrawlSummary, PageReport

# Search Engine (NEW: intelligent seed URL generation)
from .search_engine import (
    SeedURLGenerator,
    SearchQueryBuilder,
    SearchConfig,
    SearchQuery,
    SearchProvider,
    SeedURL,
    GoogleSearchEngine,
    BingSearchEngine,
    DuckDuckGoSearchEngine,
    DuckDuckGoAPIEngine,
    generate_seed_urls
)

# Main Crawler
from .crawler import WebCrawler, CrawlConfig, PageResult


__all__ = [
    # Version info
    "__version__",
    "__author__",
    
    # Config
    "Config",
    "BrowserConfig",
    "LLMConfig", 
    "ContentConfig",
    "StorageConfig",
    "CrawlConfig",
    "BaseCrawlConfig",
    "IntentCategory",
    "URLPriority",
    
    # Logging
    "setup_logger",
    "ProgressLogger",
    "LogContext",
    
    # Utilities
    "normalize_url",
    "extract_domain",
    "is_same_domain",
    "clean_text",
    "truncate_text",
    "chunk_text",
    "extract_emails",
    "extract_phones",
    "extract_json_from_text",
    "safe_write_file",
    "safe_read_file",
    "safe_write_json",
    "safe_read_json",
    
    # LLM
    "LLMClient",
    "LLMResponse",
    
    # Browser
    "create_browser_engine",
    "SeleniumEngine",
    "RequestsEngine",
    "HybridEngine",
    "FetchResult",
    
    # Content Extraction
    "ContentExtractor",
    "ExtractedContent",
    "ExtractedLink",
    
    # Intent Analysis
    "IntentAnalyzer",
    "IntentComponents",
    "MatchedIntent",
    
    # Content Analysis
    "ContentAnalyzer",
    "AnalysisResult",
    "PrioritizedURL",
    
    # File Naming
    "FileNamer",
    
    # URL Queue
    "URLQueue",
    "QueueItem",
    "QueueStats",
    
    # Storage
    "StorageManager",
    
    # Report Generation
    "ReportGenerator",
    "CrawlSummary",
    "PageReport",
    
    # Search Engine
    "SeedURLGenerator",
    "SearchQueryBuilder",
    "SearchConfig",
    "SearchQuery",
    "SearchProvider",
    "SeedURL",
    "GoogleSearchEngine",
    "BingSearchEngine",
    "DuckDuckGoSearchEngine",
    "DuckDuckGoAPIEngine",
    "generate_seed_urls",
    
    # Crawler
    "WebCrawler",
    "PageResult",
]