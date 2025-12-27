#!/usr/bin/env python3
"""
智能浏览器工具 - 主入口

设计理念 (参考CleanRL):
- 单文件包含主要流程
- 透明的处理步骤
- 详细的日志输出
- 命令行参数支持

工作流程:
1. 加载配置和用户意图
2. 初始化各组件
3. 获取起始页面
4. 循环: 提取 -> 分类 -> 分析 -> 发现新URL
5. 生成报告

URL队列策略:
- 优先级队列: 高相关性URL优先
- 探索/利用平衡: 随机探索 vs 贪心利用
- 多样性控制: 避免同一路径过深
- 深度惩罚: 较深URL优先级降低

使用方法:
    python main.py --url https://www.stanford.edu --intent "招生信息"
    python main.py --config config.json
    python main.py --url https://www.stanford.edu --max-pages 20 --headless
"""

import sys
import time
import argparse
import json
import heapq
import random
import traceback
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from urllib.parse import urlparse

from loguru import logger

# 项目模块
from config import Config, get_stanford_config, get_fast_config, get_deep_config
from browser_engine import BrowserEngine, normalize_url, is_same_domain
from content_processor import ContentProcessor
from ai_analyzer import AIAnalyzer
from data_manager import DataManager
from report_generator import ReportGenerator
from prompts import load_intent_from_file

import traceback

def get_err_message():
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message

# ============ URL优先级队列 ============

@dataclass(order=True)
class PrioritizedURL:
    """
    优先级URL数据类
    
    优先级计算: 
    - 负数表示高优先级 (heapq是最小堆)
    - 考虑: AI评分, 深度, 类型, 随机因子
    """
    priority: float
    url: str = field(compare=False)
    depth: int = field(compare=False)
    source_url: str = field(compare=False, default="")
    link_type: str = field(compare=False, default="general")
    ai_score: float = field(compare=False, default=0.0)
    reason: str = field(compare=False, default="")


class URLFrontier:
    """
    URL边界队列 - 智能URL管理
    
    特性:
    1. 优先级队列: 高价值URL优先处理
    2. 探索/利用平衡: epsilon-greedy策略
    3. 域名多样性: 避免过度集中
    4. 深度控制: 防止过深爬取
    5. 去重: 避免重复访问
    """
    
    def __init__(
        self, 
        exploration_rate: float = 0.2,
        depth_penalty: float = 0.1,
        max_depth: int = 5
    ):
        """
        初始化URL边界
        
        Args:
            exploration_rate: 探索率 (0-1), 随机选择的概率
            depth_penalty: 深度惩罚系数
            max_depth: 最大深度
        """
        self._heap: List[PrioritizedURL] = []
        self._visited: Set[str] = set()
        self._in_queue: Set[str] = set()
        self._domain_counts: Dict[str, int] = {}
        
        self.exploration_rate = exploration_rate
        self.depth_penalty = depth_penalty
        self.max_depth = max_depth
        
        # 统计
        self.total_added = 0
        self.total_popped = 0
        self.duplicates_skipped = 0
    
    def add(
        self,
        url: str,
        depth: int,
        priority: float = 0.0,
        source_url: str = "",
        link_type: str = "general",
        ai_score: float = 0.0,
        reason: str = ""
    ) -> bool:
        """
        添加URL到队列
        
        Args:
            url: URL地址
            depth: 深度
            priority: 基础优先级 (越高越优先)
            source_url: 来源URL
            link_type: 链接类型
            ai_score: AI评分
            reason: 添加原因
            
        Returns:
            是否成功添加
        """
        # 规范化URL
        normalized = normalize_url(url)
        
        # 检查是否已访问或在队列中
        if normalized in self._visited or normalized in self._in_queue:
            self.duplicates_skipped += 1
            return False
        
        # 深度检查
        if depth > self.max_depth:
            return False
        
        # 计算最终优先级 (负数，因为heapq是最小堆)
        final_priority = self._calculate_priority(
            priority, depth, link_type, ai_score
        )
        
        # 创建优先级URL对象
        p_url = PrioritizedURL(
            priority=final_priority,
            url=url,
            depth=depth,
            source_url=source_url,
            link_type=link_type,
            ai_score=ai_score,
            reason=reason
        )
        
        # 添加到堆
        heapq.heappush(self._heap, p_url)
        self._in_queue.add(normalized)
        
        # 更新域名计数
        domain = self._get_domain(url)
        self._domain_counts[domain] = self._domain_counts.get(domain, 0) + 1
        
        self.total_added += 1
        
        return True
    
    def pop(self) -> Optional[PrioritizedURL]:
        """
        获取下一个URL (探索/利用策略)
        
        Returns:
            下一个要访问的URL，队列空返回None
        """
        if not self._heap:
            return None
        
        # 探索/利用策略
        if random.random() < self.exploration_rate and len(self._heap) > 1:
            # 探索: 随机选择
            idx = random.randint(0, min(len(self._heap) - 1, 10))
            # 交换到堆顶然后pop
            self._heap[0], self._heap[idx] = self._heap[idx], self._heap[0]
            heapq.heapify(self._heap)
        
        # 获取最高优先级URL
        p_url = heapq.heappop(self._heap)
        
        # 更新状态
        normalized = normalize_url(p_url.url)
        self._in_queue.discard(normalized)
        self._visited.add(normalized)
        
        # 更新域名计数
        domain = self._get_domain(p_url.url)
        self._domain_counts[domain] = max(0, self._domain_counts.get(domain, 1) - 1)
        
        self.total_popped += 1
        
        return p_url
    
    def _calculate_priority(
        self,
        base_priority: float,
        depth: int,
        link_type: str,
        ai_score: float
    ) -> float:
        """
        计算最终优先级
        
        公式: -(base + ai_score + type_bonus - depth_penalty)
        负数因为heapq是最小堆
        """
        # 类型加成
        type_bonuses = {
            'admission': 3.0,
            'international': 2.5,
            'financial': 2.0,
            'academic': 1.5,
            'research': 1.0,
            'faculty': 0.5,
            'news': -0.5,
            'navigation': -1.0,
            'general': 0.0
        }
        type_bonus = type_bonuses.get(link_type, 0.0)
        
        # 深度惩罚
        depth_cost = depth * self.depth_penalty
        
        # 最终优先级 (负数，越小越优先)
        final = -(base_priority + ai_score * 2 + type_bonus - depth_cost)
        
        return final
    
    def _get_domain(self, url: str) -> str:
        """获取URL的域名"""
        try:
            return urlparse(url).netloc.replace('www.', '')
        except Exception:
            return ""
    
    def mark_visited(self, url: str):
        """标记URL为已访问"""
        normalized = normalize_url(url)
        self._visited.add(normalized)
    
    def is_visited(self, url: str) -> bool:
        """检查URL是否已访问"""
        normalized = normalize_url(url)
        return normalized in self._visited
    
    def get_visited_count(self) -> int:
        """获取已访问URL数量"""
        return len(self._visited)
    
    def get_queue_size(self) -> int:
        """获取队列大小"""
        return len(self._heap)
    
    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return len(self._heap) == 0
    
    def clear(self):
        """清空队列"""
        self._heap.clear()
        self._visited.clear()
        self._in_queue.clear()
        self._domain_counts.clear()
        self.total_added = 0
        self.total_popped = 0
        self.duplicates_skipped = 0
    
    def get_stats(self) -> Dict:
        """获取队列统计"""
        return {
            'queue_size': len(self._heap),
            'visited_count': len(self._visited),
            'total_added': self.total_added,
            'total_popped': self.total_popped,
            'duplicates_skipped': self.duplicates_skipped,
            'unique_domains': len(self._domain_counts)
        }
    
    def peek_top(self, n: int = 5) -> List[Dict]:
        """查看队列前N个URL (不移除)"""
        # 复制堆以避免修改
        temp_heap = self._heap.copy()
        result = []
        
        for _ in range(min(n, len(temp_heap))):
            p_url = heapq.heappop(temp_heap)
            result.append({
                'url': p_url.url,
                'priority': -p_url.priority,  # 还原为正数
                'depth': p_url.depth,
                'type': p_url.link_type,
                'ai_score': p_url.ai_score
            })
        
        return result


# ============ 全局状态 (CleanRL风格) ============

URL_FRONTIER: URLFrontier = URLFrontier()
EXTRACTED_DATA: List[Dict] = []
ANALYZED_DATA: List[Dict] = []


def setup_logging(config: Config):
    """配置日志系统"""
    # 移除默认处理器
    logger.remove()
    
    # 控制台输出
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level=config.log_level,
        colorize=True
    )
    
    # 文件输出
    log_file = Path(config.storage.base_dir) / config.log_file
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="10 MB"
    )
    
    logger.info("日志系统初始化完成")


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='智能浏览器工具 - 基于AI的网页内容分析',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --url https://www.stanford.edu --intent "招生信息"
  %(prog)s --url https://www.stanford.edu --max-pages 20 --headless
  %(prog)s --config my_config.json
  %(prog)s --preset stanford --intent-file prompt.txt
        """
    )
    
    # 必需参数
    parser.add_argument(
        '--url', '-u',
        type=str,
        help='起始URL'
    )
    
    # 用户意图
    parser.add_argument(
        '--intent', '-i',
        type=str,
        default='',
        help='用户意图描述'
    )
    
    parser.add_argument(
        '--intent-file',
        type=str,
        help='从文件加载用户意图 (prompt.txt)'
    )
    
    # 配置选项
    parser.add_argument(
        '--config', '-c',
        type=str,
        help='配置文件路径 (JSON)'
    )
    
    parser.add_argument(
        '--preset', '-p',
        type=str,
        choices=['stanford', 'fast', 'deep'],
        help='使用预设配置'
    )
    
    # 爬取参数
    parser.add_argument(
        '--max-pages', '-m',
        type=int,
        default=50,
        help='最大爬取页面数 (默认: 50)'
    )
    
    parser.add_argument(
        '--max-depth', '-d',
        type=int,
        default=3,
        help='最大爬取深度 (默认: 3)'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=1.5,
        help='请求间隔秒数 (默认: 1.5)'
    )
    
    # 探索/利用参数
    parser.add_argument(
        '--exploration-rate',
        type=float,
        default=0.2,
        help='探索率 (默认: 0.2, 范围0-1)'
    )
    
    # 浏览器选项
    parser.add_argument(
        '--headless',
        action='store_true',
        help='无头模式运行'
    )
    
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help='显示浏览器窗口'
    )
    
    # 输出选项
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='./output',
        help='输出目录 (默认: ./output)'
    )
    
    parser.add_argument(
        '--task-name', '-n',
        type=str,
        help='任务名称'
    )
    
    # 模型选项
    parser.add_argument(
        '--small-model',
        type=str,
        default='qwen3:1.7b',
        help='分类模型 (默认: qwen3:1.7b)'
    )
    
    parser.add_argument(
        '--large-model',
        type=str,
        default='qwen3:1.7b',
        help='分析模型 (默认: qwen3:1.7b)'
    )
    
    # 其他
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细输出'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='仅显示配置，不执行爬取'
    )
    
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> Config:
    """根据参数构建配置"""
    # 加载基础配置
    if args.config:
        config = Config.from_file(args.config)
    elif args.preset == 'stanford':
        config = get_stanford_config()
    elif args.preset == 'fast':
        config = get_fast_config()
    elif args.preset == 'deep':
        config = get_deep_config()
    else:
        config = Config()
    
    # 应用命令行参数
    if args.url:
        config.start_url = args.url
    
    if args.intent:
        config.user_intent = args.intent
    elif args.intent_file:
        config.user_intent = load_intent_from_file(args.intent_file)
    
    if args.max_pages:
        config.crawl.max_pages = args.max_pages
    
    if args.max_depth:
        config.crawl.max_depth = args.max_depth
    
    if args.delay:
        config.crawl.request_delay = args.delay
    
    if args.headless:
        config.selenium.headless = True
    elif args.no_headless:
        config.selenium.headless = False
    
    if args.output:
        config.storage.base_dir = args.output
    
    if args.task_name:
        config.task_name = args.task_name
    
    if args.small_model:
        config.ollama.small_model = args.small_model
    
    if args.large_model:
        config.ollama.large_model = args.large_model
    
    if args.verbose:
        config.log_level = "DEBUG"
    
    # 从URL推断域名限制
    if config.start_url and not config.crawl.allowed_domains:
        domain = urlparse(config.start_url).netloc
        config.crawl.allowed_domains = [domain.replace('www.', '')]
    
    return config


def should_visit_url(url: str, config: Config) -> bool:
    """判断URL是否应该访问"""
    # 检查是否已访问
    if URL_FRONTIER.is_visited(url):
        return False
    
    # 规范化URL
    url_normalized = normalize_url(url)
    if URL_FRONTIER.is_visited(url_normalized):
        return False
    
    # 检查域名限制
    try:
        domain = urlparse(url).netloc.replace('www.', '')
    except Exception:
        return False
    
    if config.crawl.allowed_domains:
        allowed = any(
            d in domain or domain.endswith('.' + d)
            for d in config.crawl.allowed_domains
        )
        if not allowed:
            return False
    
    # 检查排除模式
    url_lower = url.lower()
    for pattern in config.crawl.exclude_patterns:
        if pattern in url_lower:
            return False
    
    return True


def crawl_page(
    p_url: PrioritizedURL,
    browser: BrowserEngine,
    processor: ContentProcessor,
    analyzer: AIAnalyzer,
    data_manager: DataManager,
    config: Config
) -> Optional[Dict]:
    """
    爬取单个页面的完整流程
    
    步骤:
    1. Selenium获取页面
    2. Trafilatura提取内容
    3. 0.5b模型分类
    4. 3b/4b模型深度分析 (如果需要)
    5. 3b/4b模型推荐URL并添加到队列
    
    Args:
        p_url: 优先级URL对象
        browser: 浏览器引擎
        processor: 内容处理器
        analyzer: AI分析器
        data_manager: 数据管理器
        config: 配置
        
    Returns:
        页面分析结果
    """
    url = p_url.url
    depth = p_url.depth
    
    logger.info(f"{'='*60}")
    logger.info(
        f"[深度 {depth} | 优先级 {-p_url.priority:.2f}] "
        f"处理: {url[:60]}..."
    )
    
    # ========== Step 1: 获取页面 ==========
    logger.info("Step 1: 使用Selenium获取页面...")
    
    page_result = browser.fetch_page(url)
    
    if not page_result or not page_result.get('success'):
        logger.warning(f"页面获取失败: {url}")
        return None
    
    html = page_result['html']
    title = page_result.get('title', '')
    
    # 保存原始HTML
    data_manager.save_raw(url, html, title)
    
    # ========== Step 2: 提取内容 ==========
    logger.info("Step 2: 使用Trafilatura提取内容...")
    
    content = processor.extract_content(html, url)
    
    if not content or not content.get('text'):
        logger.warning(f"内容提取失败: {url}")
        return None
    
    # 保存提取的内容
    content['url'] = url
    content['depth'] = depth
    data_manager.save_extracted(url, content)
    
    EXTRACTED_DATA.append(content)
    
    # ========== Step 3: 页面分类 (0.5b模型) ==========
    logger.info("Step 3: 使用0.5b模型进行页面分类...")
    
    classification = analyzer.classify_page(
        title=content.get('title', title),
        text_preview=content.get('text_preview', content.get('text', '')[:500])
    )
    
    category = classification.get('category', 'general')
    should_extract = classification.get('should_extract', True)
    confidence = classification.get('confidence', 0)
    
    logger.info(
        f"分类结果: {category} (置信度: {confidence:.2f}, "
        f"深度分析: {'是' if should_extract else '否'})"
    )
    
    content['category'] = category
    content['classification'] = classification
    
    # ========== Step 4: 深度分析 (3b/4b模型) ==========
    analysis = None
    
    if should_extract or confidence < 0.6:
        logger.info("Step 4: 使用3b/4b模型进行深度分析...")
        
        analysis = analyzer.analyze_content(
            title=content.get('title', title),
            url=url,
            content=content.get('text', ''),
            metadata={
                'category': category,
                'links_count': len(content.get('links', []))
            }
        )
        
        # 合并分析结果
        analysis['category'] = category
        analysis['depth'] = depth
        analysis['classification'] = classification
        
        # 保存分析结果
        data_manager.save_analyzed(url, analysis)
        ANALYZED_DATA.append(analysis)
        
        logger.info(
            f"分析完成 - 相关性: {analysis.get('relevance_score', 0):.2f}, "
            f"关键点: {len(analysis.get('key_points', []))}"
        )
    else:
        logger.info("Step 4: 跳过深度分析 (页面类型不需要)")
        
        # 保存基本分析
        analysis = {
            'url': url,
            'title': content.get('title', title),
            'category': category,
            'summary': content.get('text_preview', ''),
            'skipped_deep_analysis': True
        }
        data_manager.save_analyzed(url, analysis)
        ANALYZED_DATA.append(analysis)
    
    # ========== Step 5: 发现新URL (智能队列管理) ==========
    if depth < config.crawl.max_depth:
        logger.info("Step 5: 分析链接并添加到优先级队列...")
        
        links = content.get('links', [])
        
        # 过滤已访问的链接
        unvisited_links = [
            l for l in links 
            if should_visit_url(l['url'], config)
        ]
        
        if unvisited_links:
            # 使用AI推荐URL
            recommended = analyzer.recommend_urls(
                current_url=url,
                summary=analysis.get('summary', content.get('text_preview', '')),
                links=unvisited_links,
                visited_urls=set()  # 已在should_visit_url中检查
            )
            
            # 添加推荐的URL到优先级队列
            added_count = 0
            for rec in recommended:
                rec_url = rec.get('url')
                if rec_url and should_visit_url(rec_url, config):
                    # 计算优先级
                    ai_score = rec.get('priority', 0)
                    link_type = rec.get('type', 'general')
                    reason = rec.get('reason', '')
                    
                    # 添加到边界队列
                    if URL_FRONTIER.add(
                        url=rec_url,
                        depth=depth + 1,
                        priority=ai_score,
                        source_url=url,
                        link_type=link_type,
                        ai_score=ai_score,
                        reason=reason
                    ):
                        added_count += 1
                        logger.debug(
                            f"添加URL: {rec_url[:50]}... "
                            f"(优先级: {ai_score}, 类型: {link_type})"
                        )
            
            # 同时添加一些未被AI推荐但可能有用的链接 (探索)
            recommended_urls = {r.get('url') for r in recommended}
            exploration_links = [
                l for l in unvisited_links 
                if l['url'] not in recommended_urls
            ]
            
            # 随机添加一些探索链接
            random.shuffle(exploration_links)
            for link in exploration_links[:5]:  # 最多5个探索链接
                if should_visit_url(link['url'], config):
                    URL_FRONTIER.add(
                        url=link['url'],
                        depth=depth + 1,
                        priority=link.get('priority', 0),
                        source_url=url,
                        link_type=link.get('type', 'general'),
                        ai_score=0,  # 探索链接无AI评分
                        reason='exploration'
                    )
            
            logger.info(
                f"添加了 {added_count} 个推荐URL, "
                f"队列大小: {URL_FRONTIER.get_queue_size()}"
            )
    
    return analysis


def main():
    """主函数"""
    global URL_FRONTIER, EXTRACTED_DATA, ANALYZED_DATA
    
    # 解析参数
    args = parse_args()
    
    # 构建配置
    config = build_config(args)
    
    # 验证必需参数
    if not config.start_url:
        print("错误: 请指定起始URL (--url)")
        sys.exit(1)
    
    # 设置日志
    setup_logging(config)
    
    # 显示配置
    logger.info("="*60)
    logger.info("智能浏览器工具启动")
    logger.info("="*60)
    logger.info(f"起始URL: {config.start_url}")
    logger.info(f"用户意图: {config.user_intent or '未指定'}")
    logger.info(f"最大页面: {config.crawl.max_pages}")
    logger.info(f"最大深度: {config.crawl.max_depth}")
    logger.info(f"探索率: {args.exploration_rate}")
    logger.info(f"输出目录: {config.storage.base_dir}")
    logger.info(f"小模型: {config.ollama.small_model}")
    logger.info(f"大模型: {config.ollama.large_model}")
    
    if args.dry_run:
        logger.info("Dry run模式 - 仅显示配置")
        config.save_to_file(Path(config.storage.base_dir) / 'config.json')
        return
    
    # 初始化组件
    logger.info("-"*60)
    logger.info("初始化组件...")
    
    try:
        data_manager = DataManager(config)
        browser = BrowserEngine(config)
        processor = ContentProcessor(config)
        analyzer = AIAnalyzer(config, config.user_intent)
    except Exception as e:
        logger.error(f"组件初始化失败: {e}")
        logger.debug(get_err_message())
        sys.exit(1)
    
    # 初始化URL边界队列
    URL_FRONTIER = URLFrontier(
        exploration_rate=args.exploration_rate,
        depth_penalty=0.1,
        max_depth=config.crawl.max_depth
    )
    
    # 重置状态
    EXTRACTED_DATA.clear()
    ANALYZED_DATA.clear()
    
    # 添加起始URL (最高优先级)
    URL_FRONTIER.add(
        url=config.start_url,
        depth=0,
        priority=10.0,  # 高优先级
        source_url="",
        link_type="seed",
        ai_score=10.0,
        reason="seed_url"
    )
    
    # 开始爬取
    logger.info("-"*60)
    logger.info("开始爬取...")
    
    start_time = time.time()
    pages_processed = 0
    
    try:
        while not URL_FRONTIER.is_empty() and pages_processed < config.crawl.max_pages:
            # 获取下一个URL (使用探索/利用策略)
            p_url = URL_FRONTIER.pop()
            
            if not p_url:
                break
            
            # 双重检查是否应该访问
            if not should_visit_url(p_url.url, config):
                continue
            
            # 标记为已访问
            URL_FRONTIER.mark_visited(p_url.url)
            
            # 处理页面
            result = crawl_page(
                p_url=p_url,
                browser=browser,
                processor=processor,
                analyzer=analyzer,
                data_manager=data_manager,
                config=config
            )
            
            if result:
                pages_processed += 1
                
                # 显示队列状态
                if pages_processed % 5 == 0:
                    stats = URL_FRONTIER.get_stats()
                    logger.info(
                        f"进度: {pages_processed}/{config.crawl.max_pages} | "
                        f"队列: {stats['queue_size']} | "
                        f"已访问: {stats['visited_count']}"
                    )
                    
                    # 显示队列顶部URL
                    top_urls = URL_FRONTIER.peek_top(3)
                    if top_urls:
                        logger.debug("队列顶部URL:")
                        for u in top_urls:
                            logger.debug(
                                f"  - {u['url'][:50]}... "
                                f"(优先级: {u['priority']:.2f})"
                            )
            
            # 请求间隔
            if not URL_FRONTIER.is_empty():
                delay = config.crawl.request_delay + random.uniform(-0.5, 0.5)
                delay = max(0.5, delay)  # 至少0.5秒
                time.sleep(delay)
        
    except KeyboardInterrupt:
        logger.warning("用户中断爬取")
    
    except Exception as e:
        logger.error(f"爬取过程中发生错误: {e}")
        logger.debug(get_err_message())
    
    finally:
        # 关闭浏览器
        browser.close()
    
    elapsed = time.time() - start_time
    
    # 生成报告
    logger.info("-"*60)
    logger.info("生成报告...")
    
    try:
        report_gen = ReportGenerator(config, data_manager)
        
        # 生成所有报告
        reports = report_gen.generate_all_reports()
        
        # 如果有分析数据，生成意图报告
        if ANALYZED_DATA and config.user_intent:
            synthesized = analyzer.synthesize_info(ANALYZED_DATA)
            if synthesized:
                report_gen.generate_intent_report(synthesized)
        
    except Exception as e:
        logger.error(f"报告生成失败: {get_err_message()}")
    
    # 最终统计
    frontier_stats = URL_FRONTIER.get_stats()
    
    logger.info("="*60)
    logger.info("爬取完成!")
    logger.info("="*60)
    logger.info(f"处理页面: {pages_processed}")
    logger.info(f"已访问URL: {frontier_stats['visited_count']}")
    logger.info(f"队列剩余: {frontier_stats['queue_size']}")
    logger.info(f"总添加URL: {frontier_stats['total_added']}")
    logger.info(f"跳过重复: {frontier_stats['duplicates_skipped']}")
    logger.info(f"唯一域名: {frontier_stats['unique_domains']}")
    logger.info(f"总耗时: {elapsed:.2f}秒")
    logger.info(f"输出目录: {config.storage.base_dir}")
    
    stats = data_manager.get_stats()
    logger.info(f"数据统计: {json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()