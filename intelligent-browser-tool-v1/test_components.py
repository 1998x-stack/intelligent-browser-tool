"""
组件测试脚本 - 验证各个组件是否正常工作

使用这个脚本可以快速检查系统配置是否正确
"""

import sys
from loguru import logger


def test_imports():
    """测试1: 检查所有依赖是否已安装"""
    print("\n" + "="*60)
    print("测试1: 检查依赖包")
    print("="*60)
    
    required_packages = [
        ('selenium', 'Selenium'),
        ('webdriver_manager', 'WebDriver Manager'),
        ('trafilatura', 'Trafilatura'),
        ('requests', 'Requests'),
        ('lxml', 'LXML'),
        ('loguru', 'Loguru'),
    ]
    
    all_ok = True
    for package, name in required_packages:
        try:
            __import__(package)
            print(f"✓ {name} - 已安装")
        except ImportError:
            print(f"✗ {name} - 未安装")
            all_ok = False
    
    return all_ok


def test_ollama_connection():
    """测试2: 检查Ollama服务连接"""
    print("\n" + "="*60)
    print("测试2: Ollama服务连接")
    print("="*60)
    
    import requests
    
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✓ Ollama服务正在运行")
            
            # 检查模型
            data = response.json()
            models = [m['name'] for m in data.get('models', [])]
            
            print(f"\n已安装的模型:")
            for model in models:
                print(f"  - {model}")
            
            # 检查所需模型
            required_models = ['qwen3:1.7b', 'qwen3:1.7b']
            for model in required_models:
                if any(model in m for m in models):
                    print(f"✓ {model} - 已安装")
                else:
                    print(f"✗ {model} - 未安装,请运行: ollama pull {model}")
            
            return True
        else:
            print(f"✗ Ollama服务响应异常: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"✗ 无法连接到Ollama服务: {e}")
        print("\n请确保:")
        print("  1. Ollama已安装 (https://ollama.ai)")
        print("  2. Ollama服务正在运行")
        print("  3. 服务监听在 http://localhost:11434")
        return False


def test_browser_engine():
    """测试3: 测试浏览器引擎"""
    print("\n" + "="*60)
    print("测试3: 浏览器引擎")
    print("="*60)
    
    try:
        from config import Config
        from browser_engine import BrowserEngine
        
        config = Config(headless=True)
        browser = BrowserEngine(config)
        
        print("✓ 浏览器引擎初始化成功")
        
        # 测试获取页面
        print("\n正在测试页面获取...")
        html = browser.fetch_page("https://example.com")
        
        if html and len(html) > 0:
            print(f"✓ 成功获取页面 (大小: {len(html)} 字节)")
            browser.close()
            return True
        else:
            print("✗ 页面获取失败")
            browser.close()
            return False
            
    except Exception as e:
        print(f"✗ 浏览器引擎测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_content_processor():
    """测试4: 测试内容处理器"""
    print("\n" + "="*60)
    print("测试4: 内容处理器")
    print("="*60)
    
    try:
        from config import Config
        from content_processor import ContentProcessor
        
        config = Config()
        processor = ContentProcessor(config)
        
        print("✓ 内容处理器初始化成功")
        
        # 测试HTML
        test_html = """
        <html>
            <head><title>测试页面</title></head>
            <body>
                <h1>主标题</h1>
                <p>这是一段测试文本。</p>
                <p>这是另一段文本。</p>
                <a href="https://example.com">链接1</a>
                <a href="/page2">链接2</a>
            </body>
        </html>
        """
        
        print("\n正在测试内容提取...")
        result = processor.extract_content(test_html, "https://example.com")
        
        if result:
            print("✓ 内容提取成功")
            print(f"  标题: {result.get('title', 'N/A')}")
            print(f"  文本长度: {len(result.get('text', ''))}")
            print(f"  链接数: {len(result.get('links', []))}")
            return True
        else:
            print("✗ 内容提取失败")
            return False
            
    except Exception as e:
        print(f"✗ 内容处理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ai_analyzer():
    """测试5: 测试AI分析器"""
    print("\n" + "="*60)
    print("测试5: AI分析器")
    print("="*60)
    
    try:
        from config import Config
        from ai_analyzer import AIAnalyzer
        
        config = Config()
        analyzer = AIAnalyzer(config)
        
        print("✓ AI分析器初始化成功")
        
        # 测试分类
        print("\n正在测试页面分类...")
        classification = analyzer.classify_page(
            title="Stanford Computer Science Department",
            text_preview="The Computer Science Department at Stanford University offers undergraduate and graduate programs in computer science..."
        )
        
        if classification:
            print("✓ 页面分类成功")
            print(f"  类别: {classification.get('category', 'N/A')}")
            print(f"  置信度: {classification.get('confidence', 0):.2f}")
            print(f"  是否深度提取: {classification.get('should_extract', False)}")
            return True
        else:
            print("✗ 页面分类失败")
            return False
            
    except Exception as e:
        print(f"✗ AI分析器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_pipeline():
    """测试6: 完整流程测试"""
    print("\n" + "="*60)
    print("测试6: 完整流程")
    print("="*60)
    
    try:
        from config import Config
        from browser_engine import BrowserEngine
        from content_processor import ContentProcessor
        from ai_analyzer import AIAnalyzer
        
        config = Config(headless=True)
        
        # 初始化所有组件
        browser = BrowserEngine(config)
        processor = ContentProcessor(config)
        analyzer = AIAnalyzer(config)
        
        print("✓ 所有组件初始化成功")
        
        # 执行完整流程
        test_url = "https://example.com"
        print(f"\n正在测试完整流程: {test_url}")
        
        # Step 1: 获取页面
        html = browser.fetch_page(test_url)
        if not html:
            print("✗ 页面获取失败")
            browser.close()
            return False
        print("✓ 1. 页面获取成功")
        
        # Step 2: 提取内容
        content = processor.extract_content(html, test_url)
        if not content:
            print("✗ 内容提取失败")
            browser.close()
            return False
        print("✓ 2. 内容提取成功")
        
        # Step 3: 分类
        classification = analyzer.classify_page(
            title=content.get('title', ''),
            text_preview=content.get('text', '')[:500]
        )
        if not classification:
            print("✗ 页面分类失败")
            browser.close()
            return False
        print(f"✓ 3. 页面分类成功 ({classification['category']})")
        
        # Step 4: 深度提取 (如果需要)
        if classification['should_extract']:
            core_info = analyzer.extract_core_info(
                title=content.get('title', ''),
                content=content.get('text', ''),
                metadata=content
            )
            if core_info:
                print("✓ 4. 核心信息提取成功")
            else:
                print("⚠ 4. 核心信息提取返回空")
        else:
            print("○ 4. 页面不需要深度提取")
        
        browser.close()
        
        print("\n✓ 完整流程测试通过!")
        return True
        
    except Exception as e:
        print(f"✗ 完整流程测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("智能浏览器工具 - 组件测试")
    print("="*60)
    
    tests = [
        ("依赖包检查", test_imports),
        ("Ollama连接", test_ollama_connection),
        ("浏览器引擎", test_browser_engine),
        ("内容处理器", test_content_processor),
        ("AI分析器", test_ai_analyzer),
        ("完整流程", test_full_pipeline),
    ]
    
    results = {}
    
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = result
        except KeyboardInterrupt:
            print("\n\n测试被用户中断")
            break
        except Exception as e:
            print(f"\n测试 '{name}' 出现异常: {e}")
            results[name] = False
    
    # 总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    
    for name, result in results.items():
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status} - {name}")
    
    passed = sum(results.values())
    total = len(results)
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过! 系统配置正确。")
        return True
    else:
        print("\n⚠ 部分测试失败,请检查上述错误信息。")
        return False


if __name__ == "__main__":
    try:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n测试被中断")
        sys.exit(1)