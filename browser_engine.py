"""
浏览器引擎模块 - 网页获取和交互

设计理念 (CleanRL哲学):
- 单文件自包含: Selenium和Requests两种模式集成
- 透明的处理流程: 获取流程清晰可追踪
- 最小化抽象: 直接的函数调用
- 便于调试: 详细的日志输出

支持两种模式:
- Selenium: 支持JavaScript渲染，适合动态网页
- Requests: 轻量快速，适合静态网页
"""

import time
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass
from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from config import BrowserConfig, get_err_message

# ============================================================================
# Selenium导入 (可选依赖)
# ============================================================================

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logger.warning("Selenium未安装，将使用Requests模式")

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class FetchResult:
    """网页获取结果"""
    url: str                        # 请求的URL
    final_url: str                  # 最终URL (可能有重定向)
    html: str                       # HTML内容
    status_code: int                # HTTP状态码
    content_type: str               # 内容类型
    fetch_time: float              # 获取耗时 (秒)
    success: bool                   # 是否成功
    error: str = ""                 # 错误信息
    
    @property
    def content_length(self) -> int:
        """获取内容长度"""
        return len(self.html) if self.html else 0


# ============================================================================
# 抽象基类
# ============================================================================

class BaseBrowserEngine(ABC):
    """浏览器引擎基类"""
    
    @abstractmethod
    def fetch_page(self, url: str, **kwargs) -> FetchResult:
        """获取页面"""
        pass
    
    @abstractmethod
    def close(self):
        """关闭引擎"""
        pass
    
    def is_valid_url(self, url: str, config: BrowserConfig) -> bool:
        """
        验证URL是否有效
        
        Args:
            url: 待验证的URL
            config: 浏览器配置
            
        Returns:
            是否有效
        """
        try:
            parsed = urlparse(url)
            
            # 基本验证
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 协议检查
            if parsed.scheme not in ('http', 'https'):
                return False
            
            # 域名白名单检查
            if config.allowed_domains:
                domain_match = any(
                    domain in parsed.netloc 
                    for domain in config.allowed_domains
                )
                if not domain_match:
                    logger.debug(f"域名不在白名单: {parsed.netloc}")
                    return False
            
            # 排除模式检查
            if any(pattern in url for pattern in config.exclude_patterns):
                logger.debug(f"URL匹配排除模式: {url}")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"URL验证失败: {e}")
            return False


# ============================================================================
# Selenium引擎
# ============================================================================

class SeleniumEngine(BaseBrowserEngine):
    """
    Selenium浏览器引擎
    
    特点:
    - 支持JavaScript渲染
    - 可处理动态内容
    - 支持页面交互
    """
    
    def __init__(self, config: BrowserConfig):
        """
        初始化Selenium引擎
        
        Args:
            config: 浏览器配置
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium未安装，请运行: pip install selenium")
        
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
        self._init_driver()
        
        logger.info(f"Selenium引擎初始化完成 (无头模式: {config.headless})")
    
    def _init_driver(self):
        """初始化WebDriver"""
        options = ChromeOptions()
        
        # 添加配置选项
        for option in self.config.chrome_options:
            options.add_argument(option)
        
        # 无头模式
        if self.config.headless:
            options.add_argument('--headless=new')
        
        # 反检测配置
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 禁用图片加载
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        
        # 初始化驱动
        if WEBDRIVER_MANAGER_AVAILABLE:
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            self.driver = webdriver.Chrome(options=options)
        
        # 设置超时
        self.driver.set_page_load_timeout(self.config.page_load_timeout)
        self.driver.implicitly_wait(self.config.implicit_wait)
        
        # 反检测脚本
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            '''
        })
    
    def fetch_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        scroll: bool = True
    ) -> FetchResult:
        """
        获取页面HTML内容
        
        Args:
            url: 目标URL
            wait_for_selector: 等待特定CSS选择器
            scroll: 是否滚动页面触发懒加载
            
        Returns:
            FetchResult对象
        """
        if not self.is_valid_url(url, self.config):
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=0,
                success=False,
                error="无效的URL"
            )
        
        start_time = time.time()
        
        for attempt in range(self.config.max_retries):
            try:
                logger.debug(f"Selenium获取: {url} (尝试 {attempt + 1}/{self.config.max_retries})")
                
                # 加载页面
                self.driver.get(url)
                
                # 等待元素
                if wait_for_selector:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                    )
                else:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                
                # 等待JavaScript执行
                time.sleep(1)
                
                # 滚动页面
                if scroll:
                    self._scroll_page()
                
                # 获取HTML
                html_content = self.driver.page_source
                final_url = self.driver.current_url
                
                fetch_time = time.time() - start_time
                
                logger.success(f"成功获取: {url} (大小: {len(html_content)} 字节, 耗时: {fetch_time:.2f}s)")
                
                # 请求间隔
                time.sleep(self.config.request_delay)
                
                return FetchResult(
                    url=url,
                    final_url=final_url,
                    html=html_content,
                    status_code=200,
                    content_type="text/html",
                    fetch_time=fetch_time,
                    success=True
                )
                
            except TimeoutException:
                logger.warning(f"页面加载超时: {url}")
            except WebDriverException as e:
                logger.warning(f"WebDriver错误: {e}")
            except Exception as e:
                logger.error(f"获取页面异常: {e}")
                error_msg = get_err_message()
                logger.debug(error_msg)
            
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay)
        
        return FetchResult(
            url=url,
            final_url=url,
            html="",
            status_code=0,
            content_type="",
            fetch_time=time.time() - start_time,
            success=False,
            error=f"获取失败，已重试{self.config.max_retries}次"
        )
    
    def _scroll_page(self):
        """滚动页面触发懒加载"""
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            viewport_height = self.driver.execute_script("return window.innerHeight")
            current_position = 0
            
            while current_position < total_height:
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                time.sleep(0.3)
                current_position += viewport_height
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height > total_height:
                    total_height = new_height
            
            self.driver.execute_script("window.scrollTo(0, 0);")
            
        except Exception as e:
            logger.debug(f"页面滚动失败: {e}")
    
    def click_element(self, selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """点击元素"""
        try:
            element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((by, selector))
            )
            element.click()
            time.sleep(1)
            logger.debug(f"成功点击: {selector}")
            return True
        except Exception as e:
            logger.warning(f"点击失败 ({selector}): {e}")
            return False
    
    def get_current_url(self) -> str:
        """获取当前URL"""
        return self.driver.current_url if self.driver else ""
    
    def take_screenshot(self, filename: str) -> bool:
        """截图"""
        try:
            self.driver.save_screenshot(filename)
            logger.info(f"截图已保存: {filename}")
            return True
        except Exception as e:
            logger.error(f"截图失败: {e}")
            return False
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Selenium浏览器已关闭")
            except Exception as e:
                logger.error(f"关闭浏览器出错: {e}")
    
    def __del__(self):
        self.close()


# ============================================================================
# Requests引擎
# ============================================================================

class RequestsEngine(BaseBrowserEngine):
    """
    Requests浏览器引擎
    
    特点:
    - 轻量快速
    - 低资源占用
    - 适合静态页面
    """
    
    def __init__(self, config: BrowserConfig):
        """
        初始化Requests引擎
        
        Args:
            config: 浏览器配置
        """
        self.config = config
        self.session = self._create_session()
        
        logger.info("Requests引擎初始化完成")
    
    def _create_session(self) -> requests.Session:
        """创建带重试的Session"""
        session = requests.Session()
        
        # 重试策略
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 默认请求头
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        return session
    
    def fetch_page(self, url: str, **kwargs) -> FetchResult:
        """
        获取页面HTML内容
        
        Args:
            url: 目标URL
            **kwargs: 其他requests参数
            
        Returns:
            FetchResult对象
        """
        if not self.is_valid_url(url, self.config):
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=0,
                success=False,
                error="无效的URL"
            )
        
        start_time = time.time()
        
        try:
            logger.debug(f"Requests获取: {url}")
            
            response = self.session.get(
                url,
                timeout=self.config.page_load_timeout,
                **kwargs
            )
            
            fetch_time = time.time() - start_time
            
            # 检查状态码
            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code}: {url}")
            
            # 检查内容类型
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type.lower():
                logger.debug(f"非HTML内容类型: {content_type}")
            
            logger.success(f"成功获取: {url} (大小: {len(response.text)} 字节, 耗时: {fetch_time:.2f}s)")
            
            # 请求间隔
            time.sleep(self.config.request_delay)
            
            return FetchResult(
                url=url,
                final_url=response.url,
                html=response.text,
                status_code=response.status_code,
                content_type=content_type,
                fetch_time=fetch_time,
                success=True
            )
            
        except requests.exceptions.Timeout:
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=time.time() - start_time,
                success=False,
                error="请求超时"
            )
        except requests.exceptions.RequestException as e:
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=time.time() - start_time,
                success=False,
                error=str(e)
            )
        except Exception as e:
            error_msg = get_err_message()
            logger.error(f"获取页面异常: {e}")
            logger.debug(error_msg)
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=time.time() - start_time,
                success=False,
                error=str(e)
            )
    
    def close(self):
        """关闭Session"""
        if self.session:
            self.session.close()
            logger.info("Requests Session已关闭")


# ============================================================================
# 工厂函数
# ============================================================================

def create_browser_engine(config: BrowserConfig, use_selenium: bool = True) -> BaseBrowserEngine:
    """
    创建浏览器引擎实例
    
    Args:
        config: 浏览器配置
        use_selenium: 是否使用Selenium
        
    Returns:
        浏览器引擎实例
    """
    if use_selenium and SELENIUM_AVAILABLE:
        try:
            return SeleniumEngine(config)
        except Exception as e:
            logger.warning(f"Selenium初始化失败，回退到Requests: {e}")
            return RequestsEngine(config)
    else:
        return RequestsEngine(config)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("浏览器引擎模块测试")
    print("=" * 60)
    
    # 创建配置
    config = BrowserConfig()
    config.headless = True
    
    # 测试URL
    test_url = "https://www.example.com"
    
    # 测试Requests引擎
    print("\n--- 测试Requests引擎 ---")
    requests_engine = RequestsEngine(config)
    result = requests_engine.fetch_page(test_url)
    
    print(f"URL: {result.url}")
    print(f"状态码: {result.status_code}")
    print(f"内容长度: {result.content_length}")
    print(f"耗时: {result.fetch_time:.2f}秒")
    print(f"成功: {result.success}")
    
    requests_engine.close()
    
    # 测试Selenium引擎 (如果可用)
    if SELENIUM_AVAILABLE:
        print("\n--- 测试Selenium引擎 ---")
        try:
            selenium_engine = SeleniumEngine(config)
            result = selenium_engine.fetch_page(test_url)
            
            print(f"URL: {result.url}")
            print(f"最终URL: {result.final_url}")
            print(f"内容长度: {result.content_length}")
            print(f"耗时: {result.fetch_time:.2f}秒")
            print(f"成功: {result.success}")
            
            selenium_engine.close()
        except Exception as e:
            print(f"Selenium测试失败: {e}")
    else:
        print("\nSelenium未安装，跳过测试")
    
    print("\n" + "=" * 60)
    print("测试完成!")