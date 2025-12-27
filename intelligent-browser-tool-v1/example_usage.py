"""
使用示例 - 展示如何使用智能浏览器工具

这个文件展示了几种常见的使用场景
"""

from config import Config, get_stanford_config, get_fast_config
from main import crawl_website, setup_logging, save_results


def example_1_basic_usage():
    """示例1: 基础使用 - 爬取Stanford首页"""
    print("=" * 60)
    print("示例1: 基础使用")
    print("=" * 60)
    
    setup_logging(log_level="INFO")
    
    # 使用默认配置
    config = Config()
    
    results = crawl_website(
        start_url="https://www.stanford.edu",
        max_depth=1,
        max_pages=5,
        config=config
    )
    
    save_results(results, "example_1_results.json")
    print(f"\n完成! 提取了 {len(results)} 个页面")


def example_2_custom_config():
    """示例2: 自定义配置 - 使用预定义的Stanford配置"""
    print("=" * 60)
    print("示例2: 使用预定义Stanford配置")
    print("=" * 60)
    
    setup_logging(log_level="INFO")
    
    # 使用Stanford专用配置
    config = get_stanford_config()
    
    results = crawl_website(
        start_url="https://www.stanford.edu/academics",
        max_depth=2,
        max_pages=10,
        config=config
    )
    
    save_results(results, "example_2_results.json")
    print(f"\n完成! 提取了 {len(results)} 个页面")


def example_3_fast_mode():
    """示例3: 快速模式 - 用于测试"""
    print("=" * 60)
    print("示例3: 快速测试模式")
    print("=" * 60)
    
    setup_logging(log_level="DEBUG")
    
    # 使用快速配置
    config = get_fast_config()
    
    results = crawl_website(
        start_url="https://www.stanford.edu/research",
        max_depth=1,
        max_pages=3,
        config=config
    )
    
    save_results(results, "example_3_results.json")
    print(f"\n完成! 提取了 {len(results)} 个页面")


def example_4_custom_categories():
    """示例4: 自定义分类类别"""
    print("=" * 60)
    print("示例4: 自定义分类")
    print("=" * 60)
    
    setup_logging(log_level="INFO")
    
    # 创建自定义配置
    config = Config(
        # 自定义页面类别
        page_categories=[
            "course",
            "lab",
            "publication",
            "people",
            "general"
        ],
        # 指定需要深度提取的类别
        extract_categories=["course", "lab", "publication"],
        
        # 只爬取特定域名
        allowed_domains=["cs.stanford.edu"],
        
        # 排除不需要的URL模式
        exclude_patterns=[
            "/login",
            "/search",
            ".pdf",
            "/calendar"
        ]
    )
    
    results = crawl_website(
        start_url="https://cs.stanford.edu",
        max_depth=2,
        max_pages=15,
        config=config
    )
    
    save_results(results, "example_4_results.json")
    print(f"\n完成! 提取了 {len(results)} 个页面")


def example_5_analyze_results():
    """示例5: 分析提取的结果"""
    import json
    from collections import Counter
    
    print("=" * 60)
    print("示例5: 分析结果")
    print("=" * 60)
    
    # 读取之前保存的结果
    try:
        with open("example_1_results.json", "r", encoding="utf-8") as f:
            results = json.load(f)
    except FileNotFoundError:
        print("请先运行 example_1_basic_usage() 生成结果文件")
        return
    
    print(f"\n总页面数: {len(results)}")
    
    # 统计页面类别
    categories = [r['classification']['category'] for r in results]
    category_counts = Counter(categories)
    
    print("\n页面类别分布:")
    for category, count in category_counts.most_common():
        print(f"  {category}: {count}")
    
    # 统计平均置信度
    confidences = [r['classification']['confidence'] for r in results]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    
    print(f"\n平均分类置信度: {avg_confidence:.2f}")
    
    # 找出被深度提取的页面
    extracted = [r for r in results if r['classification']['should_extract']]
    print(f"\n深度提取的页面数: {len(extracted)}")
    
    if extracted:
        print("\n深度提取的页面:")
        for item in extracted[:5]:  # 只显示前5个
            print(f"  - {item['url']}")
            if 'extracted_info' in item and 'summary' in item['extracted_info']:
                summary = item['extracted_info']['summary'][:100]
                print(f"    摘要: {summary}...")


def example_6_single_page_analysis():
    """示例6: 单页面深度分析"""
    print("=" * 60)
    print("示例6: 单页面深度分析")
    print("=" * 60)
    
    from browser_engine import BrowserEngine
    from content_processor import ContentProcessor
    from ai_analyzer import AIAnalyzer
    
    setup_logging(log_level="INFO")
    
    config = Config(headless=True)
    
    # 初始化组件
    browser = BrowserEngine(config)
    processor = ContentProcessor(config)
    analyzer = AIAnalyzer(config)
    
    # 分析单个页面
    url = "https://www.stanford.edu/academics"
    
    print(f"\n正在分析: {url}")
    
    # 获取页面
    html = browser.fetch_page(url)
    
    if html:
        # 提取内容
        content = processor.extract_content(html, url)
        
        if content:
            print(f"\n提取的文本长度: {len(content.get('text', ''))}")
            print(f"链接数量: {len(content.get('links', []))}")
            
            # 分类
            classification = analyzer.classify_page(
                title=content.get('title', ''),
                text_preview=content.get('text', '')[:500]
            )
            
            print(f"\n分类结果:")
            print(f"  类别: {classification['category']}")
            print(f"  置信度: {classification['confidence']:.2f}")
            print(f"  理由: {classification['reasoning']}")
            
            # 如果值得提取,进行深度分析
            if classification['should_extract']:
                core_info = analyzer.extract_core_info(
                    title=content.get('title', ''),
                    content=content.get('text', ''),
                    metadata=content
                )
                
                print(f"\n核心信息:")
                print(f"  摘要: {core_info.get('summary', 'N/A')}")
                print(f"  关键词: {', '.join(core_info.get('keywords', [])[:5])}")
    
    browser.close()


def main():
    """运行所有示例"""
    examples = [
        ("基础使用", example_1_basic_usage),
        ("Stanford配置", example_2_custom_config),
        ("快速模式", example_3_fast_mode),
        ("自定义分类", example_4_custom_categories),
        ("结果分析", example_5_analyze_results),
        ("单页面分析", example_6_single_page_analysis),
    ]
    
    print("智能浏览器工具 - 使用示例\n")
    print("可用示例:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"{i}. {name}")
    print("0. 运行所有示例")
    
    choice = input("\n请选择要运行的示例 (0-6): ").strip()
    
    try:
        choice = int(choice)
        if choice == 0:
            for name, func in examples:
                print(f"\n\n{'='*60}")
                print(f"运行: {name}")
                print('='*60)
                func()
                input("\n按回车继续...")
        elif 1 <= choice <= len(examples):
            examples[choice - 1][1]()
        else:
            print("无效选择")
    except ValueError:
        print("请输入数字")
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()