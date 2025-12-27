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

使用方法:
    python main.py --url https://www.stanford.edu --intent "招生信息"
    python main.py --config config.json
    python main.py --url https://www.stanford.edu --max-pages 20 --headless
"""

import sys
import time
import argparse
import json
from typing import Dict, List, Set, Optional
from pathlib import Path
from datetime import datetime
from collections import deque

from loguru import logger

# 项目模块
from config import Config, get_stanford_config, get_fast_config, get_deep_config
from browser_engine import BrowserEngine, normalize_url, is_same_domain
from content_processor import ContentProcessor
from ai_analyzer import AIAnalyzer
from data_manager import DataManager
from report_generator import ReportGenerator
from prompts import load_intent_from_file


# ============ 全局状态 (CleanRL风格) ============

VISITED_URLS: Set[str] = set()
URL_QUEUE: deque = deque()
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
        default='qwen2.5:0.5b',
        help='分类模型 (默认: qwen2.5:0.5b)'
    )
    
    parser.add_argument(
        '--large-model',
        type=str,
        default='qwen2.5:3b',
        help='分析模型 (默认: qwen2.5:3b)'
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
        from urllib.parse import urlparse
        domain = urlparse(config.start_url).netloc
        config.crawl.allowed_domains = [domain.replace('www.', '')]
    
    return config


def should_visit_url(url: str, config: Config) -> bool:
    """判断URL是否应该访问"""
    # 检查是否已访问
    if url in VISITED_URLS:
        return False
    
    # 规范化URL
    url_normalized = normalize_url(url)
    if url_normalized in VISITED_URLS:
        return False
    
    # 检查域名限制
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.replace('www.', '')
    
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
    url: str,
    depth: int,
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
    5. 3b/4b模型推荐URL
    
    Args:
        url: 目标URL
        depth: 当前深度
        browser: 浏览器引擎
        processor: 内容处理器
        analyzer: AI分析器
        data_manager: 数据管理器
        config: 配置
        
    Returns:
        页面分析结果
    """
    logger.info(f"{'='*60}")
    logger.info(f"[深度 {depth}] 开始处理: {url}")
    
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
    
    # ========== Step 5: 发现新URL (3b/4b模型) ==========
    if depth < config.crawl.max_depth:
        logger.info("Step 5: 使用3b/4b模型推荐下一步URL...")
        
        links = content.get('links', [])
        
        # 过滤已访问的链接
        unvisited_links = [
            l for l in links 
            if should_visit_url(l['url'], config)
        ]
        
        if unvisited_links:
            recommended = analyzer.recommend_urls(
                current_url=url,
                summary=analysis.get('summary', content.get('text_preview', '')),
                links=unvisited_links,
                visited_urls=VISITED_URLS
            )
            
            # 添加到队列
            for rec in recommended:
                rec_url = rec.get('url')
                if rec_url and should_visit_url(rec_url, config):
                    URL_QUEUE.append((rec_url, depth + 1))
                    logger.debug(f"添加到队列: {rec_url}")
            
            logger.info(f"推荐了 {len(recommended)} 个新URL")
    
    return analysis


def main():
    """主函数"""
    global VISITED_URLS, URL_QUEUE, EXTRACTED_DATA, ANALYZED_DATA
    
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
        sys.exit(1)
    
    # 重置状态
    VISITED_URLS.clear()
    URL_QUEUE.clear()
    EXTRACTED_DATA.clear()
    ANALYZED_DATA.clear()
    
    # 添加起始URL
    URL_QUEUE.append((config.start_url, 0))
    
    # 开始爬取
    logger.info("-"*60)
    logger.info("开始爬取...")
    
    start_time = time.time()
    pages_processed = 0
    
    try:
        while URL_QUEUE and pages_processed < config.crawl.max_pages:
            # 取出下一个URL
            current_url, depth = URL_QUEUE.popleft()
            
            # 检查是否应该访问
            if not should_visit_url(current_url, config):
                continue
            
            # 标记为已访问
            VISITED_URLS.add(current_url)
            VISITED_URLS.add(normalize_url(current_url))
            
            # 处理页面
            result = crawl_page(
                url=current_url,
                depth=depth,
                browser=browser,
                processor=processor,
                analyzer=analyzer,
                data_manager=data_manager,
                config=config
            )
            
            if result:
                pages_processed += 1
            
            # 请求间隔
            if URL_QUEUE:
                time.sleep(config.crawl.request_delay)
        
    except KeyboardInterrupt:
        logger.warning("用户中断爬取")
    
    except Exception as e:
        logger.error(f"爬取过程中发生错误: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    
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
        logger.error(f"报告生成失败: {e}")
    
    # 最终统计
    logger.info("="*60)
    logger.info("爬取完成!")
    logger.info("="*60)
    logger.info(f"处理页面: {pages_processed}")
    logger.info(f"已访问URL: {len(VISITED_URLS)}")
    logger.info(f"队列剩余: {len(URL_QUEUE)}")
    logger.info(f"总耗时: {elapsed:.2f}秒")
    logger.info(f"输出目录: {config.storage.base_dir}")
    
    stats = data_manager.get_stats()
    logger.info(f"数据统计: {json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()