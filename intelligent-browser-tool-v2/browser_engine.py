"""
浏览器引擎 - 基于Selenium的智能网页获取

设计理念:
- 单一职责：专注于获取完整渲染的HTML
- 反爬虫规避：多层防检测策略
- 智能等待：处理动态内容加载
- 资源管理：自动清理浏览器实例

反检测策略:
1. selenium-stealth: 修改浏览器指纹
2. 自定义CDP命令: 隐藏webdriver属性
3. 随机化行为: 模拟人类操作
4. 可选undetected-chromedriver: 高级反检测

参考: CleanRL单文件自包含设计, Selenium最佳实践2024
"""

import time
import random
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, urljoin
import hashlib

from loguru import logger

# 核心Selenium导入
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, 
    WebDriverException,
    NoSuchElementException,
    StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

from config import Config, SeleniumConfig


# ============ 可选依赖检测 ============

def _check_selenium_stealth():
    """检查selenium-stealth是否可用"""
    try:
        from selenium_stealth import stealth
        return True
    except ImportError:
        return False

def _check_undetected_chromedriver():
    """检查undetected-chromedriver是否可用"""
    try:
        import undetected_chromedriver as uc
        return True
    except ImportError:
        return False


HAS_SELENIUM_STEALTH = _check_selenium_stealth()
HAS_UNDETECTED_CHROMEDRIVER = _check_undetected_chromedriver()


# ============ 用户代理池 ============

USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class BrowserEngine:
    """
    浏览器引擎 - 负责获取动态渲染的网页内容
    
    功能:
    - 自动管理ChromeDriver
    - 处理JavaScript渲染
    - 智能滚动加载
    - 多层反爬虫检测规避
    - 人类行为模拟
    
    使用示例:
        engine = BrowserEngine(config)
        result = engine.fetch_page("https://example.com")
        engine.close()
        
    或使用上下文管理器:
        with BrowserEngine(config) as engine:
            result = engine.fetch_page("https://example.com")
    """
    
    def __init__(self, config: Config, use_undetected: bool = False):
        """
        初始化浏览器引擎
        
        Args:
            config: 全局配置对象
            use_undetected: 是否使用undetected-chromedriver (需要安装)
        """
        self.config = config
        self.selenium_config = config.selenium
        self.driver: Optional[webdriver.Chrome] = None
        self.use_undetected = use_undetected and HAS_UNDETECTED_CHROMEDRIVER
        
        # 随机选择User-Agent
        self.user_agent = random.choice(USER_AGENTS)
        
        # 初始化驱动
        self._init_driver()
        
        logger.info(
            f"浏览器引擎初始化完成 - "
            f"headless={self.selenium_config.headless}, "
            f"stealth={HAS_SELENIUM_STEALTH}, "
            f"undetected={self.use_undetected}"
        )
    
    def _init_driver(self):
        """初始化WebDriver，选择最佳反检测策略"""
        if self.use_undetected:
            self._init_undetected_driver()
        else:
            self._init_standard_driver()
    
    def _init_undetected_driver(self):
        """初始化undetected-chromedriver (最强反检测)"""
        import undetected_chromedriver as uc
        
        options = uc.ChromeOptions()
        
        # 基本选项
        for opt in self.selenium_config.chrome_options:
            if '--user-agent' not in opt:  # uc自己处理UA
                options.add_argument(opt)
        
        # 无头模式
        if self.selenium_config.headless:
            options.add_argument('--headless=new')
        
        try:
            self.driver = uc.Chrome(options=options, use_subprocess=True)
            self.driver.set_page_load_timeout(self.selenium_config.page_load_timeout)
            self.driver.implicitly_wait(self.selenium_config.implicit_wait)
            
            logger.debug("Undetected ChromeDriver初始化成功")
            
        except Exception as e:
            logger.warning(f"Undetected ChromeDriver初始化失败，回退到标准驱动: {e}")
            self.use_undetected = False
            self._init_standard_driver()
    
    def _init_standard_driver(self):
        """初始化标准Chrome WebDriver + selenium-stealth"""
        options = ChromeOptions()
        
        # 添加配置的Chrome选项
        for opt in self.selenium_config.chrome_options:
            options.add_argument(opt)
        
        # 设置随机User-Agent
        options.add_argument(f'--user-agent={self.user_agent}')
        
        # 无头模式
        if self.selenium_config.headless:
            options.add_argument('--headless=new')
        
        # 反检测配置 - 关键设置
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 禁用自动化提示
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # 禁用日志输出
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        options.add_argument('--disable-logging')
        
        # 性能优化
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--disable-notifications')
        
        # 禁用图片加载以提高速度 (可选)
        # prefs = {"profile.managed_default_content_settings.images": 2}
        # options.add_experimental_option("prefs", prefs)
        
        try:
            # 自动下载和管理ChromeDriver
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # 设置超时
            self.driver.set_page_load_timeout(self.selenium_config.page_load_timeout)
            self.driver.implicitly_wait(self.selenium_config.implicit_wait)
            
            # 应用selenium-stealth (如果可用)
            if HAS_SELENIUM_STEALTH:
                self._apply_selenium_stealth()
            else:
                # 回退到手动反检测脚本
                self._execute_stealth_scripts()
            
            logger.debug("Chrome WebDriver初始化成功")
            
        except Exception as e:
            logger.error(f"WebDriver初始化失败: {e}")
            raise
    
    def _apply_selenium_stealth(self):
        """应用selenium-stealth插件"""
        from selenium_stealth import stealth
        
        stealth(
            self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            run_on_insecure_origins=False
        )
        
        logger.debug("selenium-stealth已应用")
    
    def _execute_stealth_scripts(self):
        """执行反检测JavaScript脚本 (selenium-stealth不可用时的回退)"""
        stealth_scripts = [
            # 隐藏webdriver属性
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """,
            # 修改plugins
            """
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            """,
            # 修改languages
            """
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            """,
            # 隐藏Chrome特征
            """
            window.chrome = {
                runtime: {}
            };
            """,
            # 修改permissions
            """
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            """
        ]
        
        for script in stealth_scripts:
            try:
                self.driver.execute_cdp_cmd(
                    'Page.addScriptToEvaluateOnNewDocument',
                    {'source': script}
                )
            except Exception:
                try:
                    self.driver.execute_script(script)
                except Exception:
                    pass
        
        logger.debug("反检测脚本已执行")
    
    def fetch_page(
        self, 
        url: str, 
        wait_for_selector: Optional[str] = None,
        scroll: bool = True,
        humanize: bool = True
    ) -> Optional[Dict]:
        """
        获取页面内容
        
        Args:
            url: 目标URL
            wait_for_selector: 等待特定元素出现的CSS选择器
            scroll: 是否滚动页面加载更多内容
            humanize: 是否模拟人类行为
            
        Returns:
            包含HTML和元数据的字典，失败返回None
        """
        if not self._is_valid_url(url):
            logger.warning(f"无效URL: {url}")
            return None
        
        try:
            logger.info(f"正在获取: {url}")
            start_time = time.time()
            
            # 访问页面
            self.driver.get(url)
            
            # 等待页面基本加载
            self._wait_for_page_load()
            
            # 等待特定元素
            if wait_for_selector:
                self._wait_for_element(wait_for_selector)
            
            # 模拟人类行为
            if humanize:
                self._humanize_behavior()
            
            # 滚动页面加载动态内容
            if scroll:
                self._scroll_page()
            
            # 随机延迟，模拟人类行为
            time.sleep(random.uniform(0.5, 1.5))
            
            # 获取页面信息
            html = self.driver.page_source
            final_url = self.driver.current_url
            title = self.driver.title
            
            elapsed = time.time() - start_time
            
            result = {
                'url': url,
                'final_url': final_url,
                'title': title,
                'html': html,
                'html_length': len(html),
                'fetch_time': elapsed,
                'success': True,
                'content_hash': hashlib.md5(html.encode()).hexdigest()[:16]
            }
            
            logger.success(
                f"页面获取成功 - {title[:50]}... "
                f"({len(html):,} bytes, {elapsed:.2f}s)"
            )
            
            return result
            
        except TimeoutException:
            logger.warning(f"页面加载超时: {url}")
            return {'url': url, 'success': False, 'error': 'timeout'}
            
        except WebDriverException as e:
            logger.error(f"WebDriver错误: {e}")
            return {'url': url, 'success': False, 'error': str(e)}
            
        except Exception as e:
            logger.error(f"获取页面时发生错误: {e}")
            return {'url': url, 'success': False, 'error': str(e)}
    
    def _wait_for_page_load(self, timeout: int = 10):
        """等待页面基本加载完成"""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            logger.debug("页面加载等待超时，继续处理")
    
    def _wait_for_element(self, selector: str, timeout: int = 10):
        """等待特定元素出现"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            logger.debug(f"元素已出现: {selector}")
        except TimeoutException:
            logger.debug(f"等待元素超时: {selector}")
    
    def _humanize_behavior(self):
        """模拟人类行为以避免检测"""
        try:
            actions = ActionChains(self.driver)
            
            # 随机鼠标移动
            for _ in range(random.randint(1, 3)):
                x_offset = random.randint(-100, 100)
                y_offset = random.randint(-100, 100)
                actions.move_by_offset(x_offset, y_offset)
                time.sleep(random.uniform(0.1, 0.3))
            
            actions.perform()
            
            # 随机短暂停顿
            time.sleep(random.uniform(0.3, 0.8))
            
        except Exception as e:
            logger.debug(f"人类行为模拟失败: {e}")
    
    def _scroll_page(self):
        """
        滚动页面以触发懒加载内容
        
        策略:
        1. 逐步向下滚动
        2. 检测页面高度变化
        3. 达到底部或最大次数后停止
        4. 随机化滚动行为
        """
        scroll_pause = self.selenium_config.scroll_pause
        max_attempts = self.selenium_config.max_scroll_attempts
        
        try:
            last_height = self.driver.execute_script("return document.body.scrollHeight")
        except Exception:
            return
        
        attempts = 0
        
        while attempts < max_attempts:
            # 随机滚动距离 (模拟人类)
            scroll_amount = random.randint(300, 700)
            
            # 滚动
            self.driver.execute_script(
                f"window.scrollBy(0, {scroll_amount});"
            )
            
            # 随机等待
            time.sleep(scroll_pause + random.uniform(0, 0.5))
            
            # 检查是否到达底部
            try:
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                current_scroll = self.driver.execute_script("return window.pageYOffset + window.innerHeight")
            except Exception:
                break
            
            if current_scroll >= new_height:
                # 已到达底部，尝试再滚动一次确认
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                time.sleep(scroll_pause)
                
                final_height = self.driver.execute_script("return document.body.scrollHeight")
                if final_height == new_height:
                    break
                    
            last_height = new_height
            attempts += 1
        
        # 滚动回顶部
        self.driver.execute_script("window.scrollTo(0, 0);")
        
        logger.debug(f"页面滚动完成，共滚动 {attempts} 次")
    
    def _is_valid_url(self, url: str) -> bool:
        """验证URL是否有效"""
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc)
        except Exception:
            return False
    
    def click_element(self, selector: str, timeout: int = 10) -> bool:
        """
        点击页面元素
        
        Args:
            selector: CSS选择器
            timeout: 等待超时
            
        Returns:
            是否成功点击
        """
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            
            # 滚动到元素
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element
            )
            time.sleep(0.3)
            
            # 模拟人类点击
            actions = ActionChains(self.driver)
            actions.move_to_element(element).pause(random.uniform(0.1, 0.3)).click().perform()
            
            time.sleep(0.5)
            logger.debug(f"成功点击元素: {selector}")
            return True
            
        except Exception as e:
            logger.warning(f"点击元素失败: {selector} - {e}")
            return False
    
    def take_screenshot(self, filepath: str) -> bool:
        """
        截取页面截图
        
        Args:
            filepath: 保存路径
            
        Returns:
            是否成功保存
        """
        try:
            self.driver.save_screenshot(filepath)
            logger.debug(f"截图已保存: {filepath}")
            return True
        except Exception as e:
            logger.warning(f"截图保存失败: {e}")
            return False
    
    def get_links(self) -> List[Dict]:
        """获取当前页面的所有链接"""
        try:
            elements = self.driver.find_elements(By.TAG_NAME, "a")
            links = []
            for elem in elements:
                try:
                    href = elem.get_attribute("href")
                    text = elem.text.strip()
                    if href and self._is_valid_url(href):
                        links.append({'url': href, 'text': text[:100]})
                except StaleElementReferenceException:
                    continue
            return links
        except Exception as e:
            logger.warning(f"获取链接失败: {e}")
            return []
    
    def execute_script(self, script: str) -> any:
        """执行JavaScript脚本"""
        try:
            return self.driver.execute_script(script)
        except Exception as e:
            logger.warning(f"执行脚本失败: {e}")
            return None
    
    def get_cookies(self) -> List[Dict]:
        """获取当前cookies"""
        try:
            return self.driver.get_cookies()
        except Exception:
            return []
    
    def set_cookies(self, cookies: List[Dict]):
        """设置cookies"""
        try:
            for cookie in cookies:
                self.driver.add_cookie(cookie)
        except Exception as e:
            logger.warning(f"设置cookies失败: {e}")
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.warning(f"关闭浏览器时出错: {e}")
            finally:
                self.driver = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()
        return False
    
    def __del__(self):
        """析构函数 - 确保浏览器关闭"""
        self.close()


# ============ 辅助函数 ============

def normalize_url(url: str, base_url: str = None) -> str:
    """
    规范化URL
    
    Args:
        url: 原始URL
        base_url: 基础URL（用于相对路径）
        
    Returns:
        规范化后的URL
    """
    if base_url and not url.startswith(('http://', 'https://')):
        url = urljoin(base_url, url)
    
    # 移除锚点
    url = url.split('#')[0]
    
    # 移除尾部斜杠
    url = url.rstrip('/')
    
    return url


def is_same_domain(url1: str, url2: str) -> bool:
    """检查两个URL是否属于同一域名"""
    try:
        domain1 = urlparse(url1).netloc.replace('www.', '')
        domain2 = urlparse(url2).netloc.replace('www.', '')
        return (
            domain1 == domain2 or 
            domain1.endswith('.' + domain2) or 
            domain2.endswith('.' + domain1)
        )
    except Exception:
        return False


if __name__ == "__main__":
    # 测试浏览器引擎
    from config import get_fast_config
    
    config = get_fast_config()
    
    print(f"selenium-stealth可用: {HAS_SELENIUM_STEALTH}")
    print(f"undetected-chromedriver可用: {HAS_UNDETECTED_CHROMEDRIVER}")
    
    with BrowserEngine(config) as engine:
        result = engine.fetch_page("https://bot.sannysoft.com/")
        if result and result.get('success'):
            print(f"标题: {result['title']}")
            print(f"HTML长度: {result['html_length']}")
            print(f"获取时间: {result['fetch_time']:.2f}s")