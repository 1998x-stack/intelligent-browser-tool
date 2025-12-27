"""
智能浏览器工具 - 主入口
使用 Ollama + Selenium + Trafilatura 构建的智能网页浏览和分析系统

设计理念 (参考 CleanRL):
- 单文件自包含的核心逻辑
- 透明的数据流和处理过程
- 最小化抽象层,保持代码可读性
- 使用全局配置便于调试
"""

import argparse
from pathlib import Path
from loguru import logger
from browser_engine import BrowserEngine
from content_processor import ContentProcessor
from ai_analyzer import AIAnalyzer
from config import Config

# ============ 全局配置 (CleanRL风格: 使用全局变量便于调试) ============
VISITED_URLS = set()  # 已访问的URL集合
EXTRACTED_DATA = []   # 提取的数据列表


def setup_logging(log_level: str = "INFO", log_file: str = "browser_tool.log"):
    """配置日志系统"""
    logger.remove()  # 移除默认handler
    
    # 控制台输出 - 彩色格式
    logger.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True
    )
    
    # 文件输出 - 详细信息
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days"
    )
    
    logger.info("日志系统初始化完成")


def crawl_website(
    start_url: str,
    max_depth: int = 3,
    max_pages: int = 50,
    config: Config = None
):
    """
    主爬取流程 - 单函数包含所有核心逻辑 (CleanRL风格)
    
    Args:
        start_url: 起始URL
        max_depth: 最大爬取深度
        max_pages: 最大页面数
        config: 配置对象
    """
    config = config or Config()
    
    logger.info(f"开始爬取网站: {start_url}")
    logger.info(f"配置 - 最大深度: {max_depth}, 最大页面数: {max_pages}")
    
    # 初始化组件
    browser = BrowserEngine(config)
    processor = ContentProcessor(config)
    analyzer = AIAnalyzer(config)
    
    # 爬取队列: (url, depth)
    queue = [(start_url, 0)]
    pages_crawled = 0
    
    try:
        while queue and pages_crawled < max_pages:
            current_url, depth = queue.pop(0)
            
            # 检查是否已访问或超过深度
            if current_url in VISITED_URLS or depth > max_depth:
                continue
            
            logger.info(f"[{pages_crawled + 1}/{max_pages}] 爬取URL (深度{depth}): {current_url}")
            VISITED_URLS.add(current_url)
            
            # ========== Step 1: 使用Selenium获取页面 ==========
            html_content = browser.fetch_page(current_url)
            if not html_content:
                logger.warning(f"无法获取页面内容: {current_url}")
                continue
            
            # ========== Step 2: 使用Trafilatura提取内容 ==========
            extracted = processor.extract_content(html_content, current_url)
            if not extracted:
                logger.warning(f"内容提取失败: {current_url}")
                continue
            
            # ========== Step 3: 使用0.5b模型进行意图分类 ==========
            classification = analyzer.classify_page(
                title=extracted.get('title', ''),
                text_preview=extracted.get('text', '')[:600]  # 前500字符
            )
            
            logger.info(f"页面分类: {classification['category']} (置信度: {classification['confidence']:.2f})")
            
            # ========== Step 4: 使用4b模型提取核心信息 ==========
            if classification['should_extract']:
                core_info = analyzer.extract_core_info(
                    title=extracted.get('title', ''),
                    content=extracted.get('text', ''),
                    metadata=extracted
                )
                
                # 保存提取的数据
                data_entry = {
                    'url': current_url,
                    'depth': depth,
                    'classification': classification,
                    'extracted_info': core_info,
                    'metadata': extracted
                }
                EXTRACTED_DATA.append(data_entry)
                
                logger.success(f"成功提取核心信息: {core_info.get('summary', 'N/A')[:100]}")
            
            # ========== Step 5: 使用4b模型提取下一个URL列表 ==========
            next_urls = analyzer.extract_next_urls(
                current_url=current_url,
                page_content=extracted.get('text', ''),
                links=extracted.get('links', [])
            )
            
            # 将新URL加入队列
            for next_url in next_urls:
                if next_url not in VISITED_URLS:
                    queue.append((next_url, depth + 1))
                    logger.debug(f"添加到队列: {next_url}")
            
            pages_crawled += 1
            
    except KeyboardInterrupt:
        logger.warning("用户中断爬取")
    except Exception as e:
        logger.error(f"爬取过程出错: {e}", exc_info=True)
        import traceback
        logger.debug(traceback.format_exc())
    finally:
        browser.close()
        logger.info(f"爬取完成. 总页面数: {pages_crawled}, 提取数据条数: {len(EXTRACTED_DATA)}")
    
    return EXTRACTED_DATA


def save_results(data: list, output_path: str = "results.json"):
    """
    保存结果到文件 - 增强的JSON序列化处理
    
    Args:
        data: 要保存的数据列表
        output_path: 输出文件路径
    """
    import json
    from datetime import datetime
    from lxml.etree import _Element
    
    def json_serializer(obj):
        """自定义JSON序列化器 - 处理特殊对象"""
        # 处理 lxml._Element
        if isinstance(obj, _Element):
            from lxml import etree
            return etree.tostring(obj, encoding='unicode', method='text')
        
        # 处理 datetime
        elif isinstance(obj, datetime):
            return obj.isoformat()
        
        # 处理 set
        elif isinstance(obj, set):
            return list(obj)
        
        # 处理其他对象
        elif hasattr(obj, '__dict__'):
            return str(obj)
        
        # 默认处理
        else:
            return str(obj)
    
    try:
        output_file = Path(output_path)
        
        # 使用自定义序列化器
        with output_file.open('w', encoding='utf-8') as f:
            json.dump(
                data, 
                f, 
                ensure_ascii=False, 
                indent=2,
                default=json_serializer  # 关键：使用自定义序列化器
            )
        
        logger.info(f"结果已保存到: {output_file.absolute()}")
        
        # 验证文件大小
        file_size = output_file.stat().st_size
        logger.info(f"输出文件大小: {file_size / 1024:.2f} KB")
        
    except Exception as e:
        logger.error(f"保存结果时出错: {e}", exc_info=True)
        
        # 尝试保存为纯文本格式作为备份
        backup_path = output_path.replace('.json', '_backup.txt')
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(str(data))
            logger.warning(f"JSON保存失败，已保存纯文本备份到: {backup_path}")
        except:
            logger.error("备份保存也失败了")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="智能浏览器工具 - 使用AI分析和提取网页内容"
    )
    parser.add_argument(
        '--url',
        type=str,
        default='https://www.stanford.edu',
        help='起始URL (默认: Stanford大学官网)'
    )
    parser.add_argument(
        '--max-depth',
        type=int,
        default=2,
        help='最大爬取深度 (默认: 2)'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=20,
        help='最大页面数 (默认: 20)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='results.json',
        help='输出文件路径 (默认: results.json)'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='日志级别 (默认: INFO)'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='使用无头浏览器模式'
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(log_level=args.log_level)
    
    # 创建配置
    config = Config(
        headless=args.headless,
        ollama_host='http://localhost:11434'
    )
    
    # 执行爬取
    results = crawl_website(
        start_url=args.url,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        config=config
    )
    
    # 保存结果
    if results:
        save_results(results, args.output)
        logger.success(f"任务完成! 共提取 {len(results)} 个页面的数据")
    else:
        logger.warning("未提取到任何数据")


if __name__ == "__main__":
    main()