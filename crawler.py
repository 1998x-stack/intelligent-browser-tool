#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网页爬虫主控制器 - Web Crawler Orchestrator

协调所有模块完成网页爬取、内容分析和数据提取任务。
Orchestrates all modules to perform web crawling, content analysis,
and data extraction tasks.

工作流程 (Workflow):
1. 用户输入URL和意图 → Intent Analyzer生成prompt组件
2. Browser Engine获取页面 → Content Extractor提取内容
3. Content Analyzer分析内容 → 提取数据和优先级URL
4. URL Queue管理待爬取URL → 循环处理直到完成
5. Report Generator生成报告 → Storage Manager保存数据

设计原则 (Design Principles):
- CleanRL哲学: 单文件自包含、透明处理流程、最小化抽象、便于调试
- 模块化协调: 各模块独立工作,通过清晰接口交互
- 容错处理: 单个页面失败不影响整体爬取

Author: AI Assistant
Date: 2024
"""

import sys
import argparse
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from loguru import logger

# 导入项目模块
from config import Config, URLPriority
from logger_config import setup_logger, ProgressLogger
from utils import normalize_url, extract_domain
from llm_client import LLMClient
from browser_engine import create_browser_engine, SeleniumEngine, RequestsEngine
from content_extractor import ContentExtractor
from intent_analyzer import IntentAnalyzer, IntentComponents
from content_analyzer import ContentAnalyzer, AnalysisResult
from file_namer import FileNamer
from url_queue import URLQueue, QueueItem
from storage_manager import StorageManager
from report_generator import (
    ReportGenerator, CrawlSummary, PageReport,
    create_summary_from_results, create_page_report_from_result
)
from search_engine import (
    SeedURLGenerator, SearchConfig, SeedURL,
    generate_seed_urls
)


# ============================================================================
# 错误处理 (Error Handling)
# ============================================================================

def get_err_message() -> str:
    """获取当前异常的详细错误信息"""
    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return "No exception"
    return f"{exc_type.__name__}: {exc_value} (line {exc_tb.tb_lineno})"


# ============================================================================
# 数据结构 (Data Structures)
# ============================================================================

@dataclass
class CrawlConfig:
    """
    爬取配置
    
    Attributes:
        start_url: 起始URL
        intent: 用户意图
        max_pages: 最大爬取页面数
        max_depth: 最大爬取深度
        use_selenium: 是否使用Selenium
        output_dir: 输出目录
        save_raw_html: 是否保存原始HTML
        generate_report: 是否生成报告
        use_search_seeds: 是否使用搜索引擎生成种子URL
        search_engines: 搜索引擎列表
        max_seed_urls: 最大种子URL数量
        language: 搜索语言
    """
    start_url: str = "https://www.stanford.edu/"
    intent: str = "招生"
    max_pages: int = 50
    max_depth: int = 3
    use_selenium: bool = True
    output_dir: str = "./outputs"
    save_raw_html: bool = True
    generate_report: bool = True
    # 搜索种子相关配置
    use_search_seeds: bool = True           # 是否使用搜索引擎生成种子URL
    search_engines: List[str] = field(default_factory=lambda: ["google", "bing"])
    max_seed_urls: int = 10                  # 最大种子URL数量
    language: str = "zh"                     # 搜索语言 (zh/en)


@dataclass
class PageResult:
    """
    单页面处理结果
    
    Attributes:
        url: 页面URL
        title: 页面标题
        success: 是否成功
        error: 错误信息
        fetch_time: 抓取耗时
        analysis_time: 分析耗时
        relevance_score: 相关性分数
        key_findings: 关键发现
        extracted_data: 提取的数据
        summary: 内容摘要
        priority_urls: 优先URL列表
        depth: 爬取深度
    """
    url: str
    title: str = ""
    success: bool = True
    error: Optional[str] = None
    fetch_time: float = 0.0
    analysis_time: float = 0.0
    relevance_score: float = 0.0
    key_findings: List[str] = field(default_factory=list)
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    priority_urls: List[Dict] = field(default_factory=list)
    depth: int = 0


# ============================================================================
# 爬虫控制器 (Crawler Controller)
# ============================================================================

class WebCrawler:
    """
    网页爬虫主控制器
    
    Coordinates all modules to perform web crawling with LLM-powered analysis.
    
    Features:
        - 多模式浏览器: Selenium (JS渲染) / Requests (轻量)
        - LLM驱动分析: 意图转换、内容分析、URL优先级
        - 优先级队列: 智能URL调度
        - 完整报告: Markdown/JSON输出
    
    Example:
        >>> crawler = WebCrawler(config)
        >>> crawler.run()
    """
    
    def __init__(self, crawl_config: CrawlConfig, config: Optional[Config] = None):
        """
        初始化爬虫控制器
        
        Args:
            crawl_config: 爬取配置
            config: 系统配置 (默认使用Config默认值)
        """
        self.crawl_config = crawl_config
        self.config = config or Config()
        
        # 同步爬取配置到系统配置
        self._sync_config()
        
        # 初始化组件
        self._init_components()
    
    def _sync_config(self) -> None:
        """同步爬取配置到系统配置"""
        # 同步爬取参数
        self.config.crawl.max_pages = self.crawl_config.max_pages
        self.config.crawl.max_depth = self.crawl_config.max_depth
        
        # 同步存储目录
        self.config.storage.base_dir = Path(self.crawl_config.output_dir)
        self.config.storage.create_dirs()
        
        # 设置允许的域名
        start_domain = extract_domain(self.crawl_config.start_url)
        if start_domain:
            self.config.browser.allowed_domains = [start_domain]
        
        # 状态追踪
        self.results: List[PageResult] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.intent_components: Optional[IntentComponents] = None
        
        logger.info(
            f"WebCrawler initialized: start_url={self.crawl_config.start_url}, "
            f"intent={self.crawl_config.intent}, max_pages={self.crawl_config.max_pages}"
        )
    
    def _init_components(self) -> None:
        """初始化所有组件"""
        try:
            # LLM客户端
            self.llm_client = LLMClient(self.config.llm)
            
            # 浏览器引擎
            self.browser = create_browser_engine(
                self.config.browser,
                use_selenium=self.crawl_config.use_selenium
            )
            
            # 内容提取器
            self.extractor = ContentExtractor(self.config.content)
            
            # 意图分析器 (只需要llm_client)
            self.intent_analyzer = IntentAnalyzer(self.llm_client)
            
            # 内容分析器 (只需要llm_client)
            self.content_analyzer = ContentAnalyzer(self.llm_client)
            
            # 文件命名器
            self.file_namer = FileNamer(self.llm_client)
            
            # URL队列 (需要完整Config对象)
            self.url_queue = URLQueue(self.config)
            
            # 存储管理器 (需要Config对象, 可选file_namer)
            self.storage = StorageManager(self.config, self.file_namer)
            
            # 报告生成器
            self.report_generator = ReportGenerator()
            
            # 种子URL生成器 (搜索引擎模块)
            if self.crawl_config.use_search_seeds:
                # 确定搜索引擎提供商
                from search_engine import SearchProvider
                provider_map = {
                    "google": SearchProvider.GOOGLE,
                    "bing": SearchProvider.BING,
                    "duckduckgo": SearchProvider.DUCKDUCKGO_API,  # 使用API版本(最稳定)
                    "duckduckgo_api": SearchProvider.DUCKDUCKGO_API,
                    "duckduckgo_html": SearchProvider.DUCKDUCKGO,
                }
                # 默认使用DuckDuckGo API (最稳定)
                primary_engine = self.crawl_config.search_engines[0] if self.crawl_config.search_engines else "duckduckgo"
                provider = provider_map.get(primary_engine.lower(), SearchProvider.DUCKDUCKGO_API)
                
                search_config = SearchConfig(
                    provider=provider,
                    max_results=self.crawl_config.max_seed_urls,
                    timeout=20,
                    use_selenium=self.crawl_config.use_selenium,
                    language=self.crawl_config.language[:2] if self.crawl_config.language else "en",
                    debug_mode=False,  # 生产环境关闭调试
                )
                self.seed_generator = SeedURLGenerator(
                    llm_client=self.llm_client,
                    search_config=search_config,
                    browser_engine=self.browser if self.crawl_config.use_selenium else None
                )
                logger.info("种子URL生成器已初始化 (搜索引擎: {})".format(provider.value))
            else:
                self.seed_generator = None
            
            # 进度追踪
            self.progress = ProgressLogger(
                total=self.crawl_config.max_pages,
                desc="Crawling"
            )
            
            logger.success("All components initialized successfully")
            
        except Exception:
            logger.error(f"Component initialization failed: {get_err_message()}")
            raise
    
    # ========================================================================
    # 核心爬取流程 (Core Crawling Process)
    # ========================================================================
    
    def run(self) -> Dict[str, Any]:
        """
        运行爬虫
        
        Returns:
            爬取结果摘要字典
        """
        self.start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("Starting Web Crawler")
        logger.info("=" * 60)
        
        try:
            # 步骤1: 分析用户意图
            self._analyze_intent()
            
            # 步骤2: 生成种子URL (通过搜索引擎)
            if self.crawl_config.use_search_seeds and self.seed_generator:
                self._generate_seed_urls()
            else:
                # 仅添加原始起始URL
                self._add_start_url()
            
            # 步骤3: 爬取循环
            self._crawl_loop()
            
            # 步骤4: 生成报告
            if self.crawl_config.generate_report:
                self._generate_report()
            
            self.end_time = datetime.now()
            
            # 返回摘要
            return self._create_summary()
            
        except KeyboardInterrupt:
            logger.warning("Crawling interrupted by user")
            self.end_time = datetime.now()
            return self._create_summary()
            
        except Exception:
            logger.error(f"Crawling failed: {get_err_message()}")
            self.end_time = datetime.now()
            return self._create_summary()
            
        finally:
            self._cleanup()
    
    def _analyze_intent(self) -> None:
        """分析用户意图,生成prompt组件"""
        logger.info(f"Analyzing intent: {self.crawl_config.intent}")
        
        try:
            self.intent_components = self.intent_analyzer.analyze_intent(
                intent=self.crawl_config.intent,
                url=self.crawl_config.start_url
            )
            
            logger.success(
                f"Intent analyzed: category={self.intent_components.category}, "
                f"keywords={self.intent_components.keywords[:3]}..."
            )
            
            # 保存意图分析结果
            self.storage.save_json(
                data={
                    'intent': self.crawl_config.intent,
                    'components': {
                        'category': self.intent_components.category,
                        'keywords': self.intent_components.keywords,
                        'search_focus': self.intent_components.search_focus,
                        'content_type': self.intent_components.content_type,
                        'priority_signals': self.intent_components.priority_signals,
                        'exclude_patterns': self.intent_components.exclude_patterns,
                        'prompt_background': self.intent_components.prompt_background
                    }
                },
                filename="intent_analysis.json",
                subdir="metadata"
            )
            
        except Exception:
            logger.warning(f"Intent analysis failed: {get_err_message()}")
            # 使用默认组件
            self.intent_components = self.intent_analyzer._create_default_components(
                self.crawl_config.intent,
                self.crawl_config.start_url
            )
    
    def _add_start_url(self) -> None:
        """添加起始URL到队列 (不使用搜索引擎时)"""
        self.url_queue.add(
            url=self.crawl_config.start_url,
            priority=URLPriority.HIGH,
            depth=0,
            context={"reason": "Start URL"}
        )
        logger.info(f"Start URL added: {self.crawl_config.start_url}")
    
    def _generate_seed_urls(self) -> None:
        """
        通过搜索引擎生成种子URL
        
        流程:
        1. 使用LLM根据意图生成搜索查询词
        2. 通过Google/Bing执行搜索
        3. 获取top N结果作为种子URL
        4. 与原始URL合并，按优先级排序
        """
        logger.info("="*40)
        logger.info("生成种子URL (通过搜索引擎)")
        logger.info("="*40)
        
        try:
            # 生成种子URL (使用search_engine.py的generate方法)
            seeds: List[SeedURL] = self.seed_generator.generate(
                intent=self.crawl_config.intent,
                original_url=self.crawl_config.start_url,
                include_original=True,
                use_site_filter=True,
                fallback_providers=True
            )
            
            if not seeds:
                logger.warning("搜索引擎未返回结果，使用原始URL")
                self._add_start_url()
                return
            
            # 添加种子URL到队列
            for i, seed in enumerate(seeds):
                # 根据来源设置优先级
                if seed.source == "original":
                    priority = URLPriority.HIGH
                else:
                    # 搜索结果优先级稍低于原始URL
                    priority = URLPriority.HIGH if i < 3 else URLPriority.MEDIUM
                
                self.url_queue.add(
                    url=seed.url,
                    priority=priority,
                    depth=0,
                    context={
                        "reason": f"Seed URL ({seed.source})",
                        "title": seed.title or "",
                        "snippet": seed.snippet or "",
                        "relevance_score": seed.relevance_score,
                        "search_rank": seed.rank
                    }
                )
                
                logger.info(f"  添加种子[{i+1}]: {seed.url[:60]}... (来源: {seed.source})")
            
            # 保存种子URL信息
            seed_data = {
                "intent": self.crawl_config.intent,
                "original_url": self.crawl_config.start_url,
                "search_engines": self.crawl_config.search_engines,
                "seeds": [seed.to_dict() for seed in seeds]
            }
            
            self.storage.save_json(
                data=seed_data,
                filename="seed_urls.json",
                subdir="metadata"
            )
            
            logger.success(f"成功添加 {len(seeds)} 个种子URL")
            
        except Exception as e:
            logger.error(f"种子URL生成失败: {e}")
            logger.debug(get_err_message())
            # 回退到原始URL
            logger.info("回退到原始URL")
            self._add_start_url()
    
    def _crawl_loop(self) -> None:
        """主爬取循环"""
        pages_processed = 0
        
        while self.url_queue.has_next() and pages_processed < self.crawl_config.max_pages:
            # 获取下一个URL
            item = self.url_queue.get_next()
            if not item:
                break
            
            logger.info(f"\n{'='*40}")
            logger.info(f"Processing [{pages_processed + 1}/{self.crawl_config.max_pages}]: {item.url}")
            logger.info(f"Priority: {item.priority}, Depth: {item.depth}")
            
            # 处理页面
            result = self._process_page(item)
            self.results.append(result)
            
            # 添加发现的URL到队列
            if result.success and result.priority_urls:
                self._add_discovered_urls(result.priority_urls, item)
            
            # 更新进度
            pages_processed += 1
            self.progress.update(1, f"Processed: {item.url[:50]}...")
            
            # 短暂延迟,避免过快请求
            time.sleep(0.5)
        
        logger.info(f"\nCrawling completed: {pages_processed} pages processed")
    
    def _process_page(self, item: QueueItem) -> PageResult:
        """
        处理单个页面
        
        Args:
            item: URL队列项
            
        Returns:
            页面处理结果
        """
        result = PageResult(url=item.url, depth=item.depth)
        
        try:
            # 步骤1: 获取页面
            fetch_start = time.time()
            fetch_result = self.browser.fetch_page(item.url)
            result.fetch_time = time.time() - fetch_start
            
            if not fetch_result.success:
                result.success = False
                result.error = fetch_result.error
                logger.warning(f"Fetch failed: {fetch_result.error}")
                return result
            
            logger.debug(f"Page fetched in {result.fetch_time:.2f}s")
            
            # 保存原始HTML
            if self.crawl_config.save_raw_html:
                html_filename = self.file_namer.generate_timestamped_name(
                    title=item.url.split('/')[-1] or "page",
                    content_type="html"
                )
                self.storage.save_raw_html(
                    url=item.url,
                    html_content=fetch_result.html,
                    filename=f"{html_filename}.html"
                )
            
            # 步骤2: 提取内容
            extracted = self.extractor.extract(
                html=fetch_result.html,
                url=item.url
            )
            
            if not extracted or not extracted.text:
                result.success = False
                result.error = "Content extraction failed"
                logger.warning("No content extracted")
                return result
            
            result.title = extracted.title or ""
            logger.debug(f"Content extracted: {len(extracted.text)} chars")
            
            # 步骤3: 快速相关性检查
            if self.intent_components:
                quick_match = self.intent_analyzer.quick_match_intent(
                    title=extracted.title or "",
                    summary=extracted.text[:500] if extracted.text else "",
                    intent_components=self.intent_components
                )
                
                if quick_match.confidence < 0.2:
                    logger.info(f"Low relevance ({quick_match.confidence:.2f}), skipping deep analysis")
                    result.relevance_score = quick_match.confidence
                    result.summary = "Low relevance to intent"
                    return result
            
            # 步骤4: 深度内容分析
            analysis_start = time.time()
            analysis = self.content_analyzer.analyze(
                content=extracted,
                intent_components=self.intent_components,
                base_url=item.url
            )
            result.analysis_time = time.time() - analysis_start
            
            # 填充结果
            result.relevance_score = analysis.relevance_score
            result.key_findings = analysis.key_findings
            result.extracted_data = analysis.extracted_data
            result.summary = analysis.summary
            result.priority_urls = [
                {
                    'url': u.url,
                    'priority': u.priority,
                    'reason': u.reason,
                    'link_text': u.link_text
                }
                for u in analysis.prioritized_urls
            ]
            
            logger.success(
                f"Analysis complete: relevance={result.relevance_score:.2f}, "
                f"findings={len(result.key_findings)}, urls={len(result.priority_urls)}"
            )
            
            # 保存处理结果
            self._save_page_result(result, extracted)
            
            return result
            
        except Exception:
            result.success = False
            result.error = get_err_message()
            logger.error(f"Page processing failed: {result.error}")
            return result
    
    def _add_discovered_urls(self, urls: List[Dict], parent_item: QueueItem) -> None:
        """
        添加发现的URL到队列
        
        Args:
            urls: 优先级URL列表
            parent_item: 父页面队列项
        """
        added = 0
        for url_info in urls:
            if self.url_queue.add(
                url=url_info.get('url', ''),
                priority=url_info.get('priority', 2),
                depth=parent_item.depth + 1,
                parent_url=parent_item.url,
                context={
                    "link_text": url_info.get('link_text'),
                    "reason": url_info.get('reason')
                }
            ):
                added += 1
        
        if added > 0:
            logger.info(f"Added {added} new URLs to queue")
    
    def _save_page_result(self, result: PageResult, extracted) -> None:
        """保存页面处理结果"""
        try:
            # 生成文件名
            filename = self.file_namer.generate_timestamped_name(
                title=result.title or result.url.split('/')[-1] or "analysis",
                summary=result.summary[:100] if result.summary else "",
                content_type="analysis"
            )
            
            # 保存分析结果
            self.storage.save_json(
                data={
                    'url': result.url,
                    'title': result.title,
                    'relevance_score': result.relevance_score,
                    'key_findings': result.key_findings,
                    'extracted_data': result.extracted_data,
                    'summary': result.summary,
                    'priority_urls': result.priority_urls,
                    'fetch_time': result.fetch_time,
                    'analysis_time': result.analysis_time,
                    'depth': result.depth,
                    'timestamp': datetime.now().isoformat()
                },
                filename=f"{filename}.json",
                subdir="processed"
            )
            
        except Exception:
            logger.warning(f"Failed to save page result: {get_err_message()}")
    
    # ========================================================================
    # 报告生成 (Report Generation)
    # ========================================================================
    
    def _generate_report(self) -> None:
        """生成爬取报告"""
        logger.info("Generating report...")
        
        try:
            # 创建摘要
            summary = CrawlSummary(
                start_time=self.start_time or datetime.now(),
                end_time=self.end_time or datetime.now(),
                total_pages=len(self.results),
                successful_pages=sum(1 for r in self.results if r.success),
                failed_pages=sum(1 for r in self.results if not r.success),
                total_urls_found=sum(len(r.priority_urls) for r in self.results),
                total_data_extracted=sum(len(r.extracted_data) for r in self.results),
                intent=self.crawl_config.intent,
                start_url=self.crawl_config.start_url
            )
            
            self.report_generator.set_summary(summary)
            
            # 添加页面报告
            for result in self.results:
                page_report = PageReport(
                    url=result.url,
                    title=result.title,
                    relevance_score=result.relevance_score,
                    key_findings=result.key_findings,
                    extracted_data=result.extracted_data,
                    summary=result.summary,
                    priority_urls=result.priority_urls,
                    fetch_time=result.fetch_time,
                    analysis_time=result.analysis_time,
                    success=result.success,
                    error=result.error
                )
                self.report_generator.add_page_report(page_report)
            
            # 添加元数据
            self.report_generator.add_metadata("crawler_version", "1.0.0")
            self.report_generator.add_metadata("max_pages", self.crawl_config.max_pages)
            self.report_generator.add_metadata("max_depth", self.crawl_config.max_depth)
            
            # 保存报告
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved = self.report_generator.save_report(
                output_dir=str(self.storage.reports_dir),
                filename=f"crawl_report_{timestamp}",
                formats=['md', 'json']
            )
            
            logger.success(f"Report saved: {saved}")
            
        except Exception:
            logger.error(f"Report generation failed: {get_err_message()}")
    
    def _create_summary(self) -> Dict[str, Any]:
        """创建爬取摘要"""
        successful = sum(1 for r in self.results if r.success)
        failed = len(self.results) - successful
        
        duration = 0
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        
        return {
            'start_url': self.crawl_config.start_url,
            'intent': self.crawl_config.intent,
            'total_pages': len(self.results),
            'successful_pages': successful,
            'failed_pages': failed,
            'duration_seconds': duration,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'output_dir': self.crawl_config.output_dir
        }
    
    def _cleanup(self) -> None:
        """清理资源"""
        try:
            if hasattr(self, 'browser') and self.browser:
                if isinstance(self.browser, SeleniumEngine):
                    self.browser.close()
            
            logger.info("Resources cleaned up")
            
        except Exception:
            logger.warning(f"Cleanup warning: {get_err_message()}")


# ============================================================================
# 命令行接口 (CLI Interface)
# ============================================================================

def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Web Crawler with LLM-powered Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python crawler.py -u https://www.stanford.edu/ -i "招生信息"
  python crawler.py -u https://example.com -i "contact info" --max-pages 20
  python crawler.py --url https://news.site.com --intent "latest news" --no-selenium
        """
    )
    
    parser.add_argument(
        '-u', '--url',
        default="https://www.stanford.edu/",
        help="Start URL (default: Stanford)"
    )
    
    parser.add_argument(
        '-i', '--intent',
        default="招生",
        help="User intent/search focus (default: 招生)"
    )
    
    parser.add_argument(
        '--max-pages',
        type=int,
        default=50,
        help="Maximum pages to crawl (default: 50)"
    )
    
    parser.add_argument(
        '--max-depth',
        type=int,
        default=3,
        help="Maximum crawl depth (default: 3)"
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        default="./outputs",
        help="Output directory (default: ./outputs)"
    )
    
    parser.add_argument(
        '--no-selenium',
        action='store_true',
        help="Use requests instead of selenium"
    )
    
    parser.add_argument(
        '--no-report',
        action='store_true',
        help="Skip report generation"
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable debug logging"
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    # 设置日志
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logger(
        log_dir=Path(args.output_dir) / "logs",
        log_level=log_level
    )
    
    # 创建配置
    crawl_config = CrawlConfig(
        start_url=args.url,
        intent=args.intent,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        use_selenium=not args.no_selenium,
        output_dir=args.output_dir,
        generate_report=not args.no_report
    )
    
    # 打印配置
    print("\n" + "=" * 60)
    print("Web Crawler Configuration")
    print("=" * 60)
    print(f"  Start URL: {crawl_config.start_url}")
    print(f"  Intent: {crawl_config.intent}")
    print(f"  Max Pages: {crawl_config.max_pages}")
    print(f"  Max Depth: {crawl_config.max_depth}")
    print(f"  Browser: {'Selenium' if crawl_config.use_selenium else 'Requests'}")
    print(f"  Output: {crawl_config.output_dir}")
    print("=" * 60 + "\n")
    
    # 运行爬虫
    crawler = WebCrawler(crawl_config)
    summary = crawler.run()
    
    # 打印结果摘要
    print("\n" + "=" * 60)
    print("Crawl Summary")
    print("=" * 60)
    print(f"  Total Pages: {summary['total_pages']}")
    print(f"  Successful: {summary['successful_pages']}")
    print(f"  Failed: {summary['failed_pages']}")
    print(f"  Duration: {summary['duration_seconds']:.1f}s")
    print(f"  Output: {summary['output_dir']}")
    print("=" * 60 + "\n")
    
    return 0


# ============================================================================
# 入口点 (Entry Point)
# ============================================================================

if __name__ == "__main__":
    sys.exit(main())