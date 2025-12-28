"""
浏览器引擎模块 - 网页获取和交互 (优化版)

设计理念 (CleanRL哲学):
- 单文件自包含: Selenium和Requests两种模式集成
- 透明的处理流程: 获取流程清晰可追踪
- 最小化抽象: 直接的函数调用
- 便于调试: 详细的日志输出

优化特性:
- PageLoadStrategy: 使用"eager"策略加速加载
- 禁用图片/CSS/字体加载
- 支持undetected-chromedriver防检测
- 更好的超时处理
- 连接池优化
- 懒加载驱动初始化

支持两种模式:
- Selenium: 支持JavaScript渲染，适合动态网页
- Requests: 轻量快速，适合静态网页
"""

import time
import random
from typing import Optional, Dict, List, Tuple, Union
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from contextlib import contextmanager

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from config import BrowserConfig, get_err_message


# ============================================================================
# Selenium导入 (可选依赖)
# ============================================================================

SELENIUM_AVAILABLE = False
UNDETECTED_AVAILABLE = False
WEBDRIVER_MANAGER_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, 
        WebDriverException,
        NoSuchElementException,
        StaleElementReferenceException,
        SessionNotCreatedException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    logger.warning("Selenium未安装，将使用Requests模式")

# 尝试导入undetected-chromedriver (更好的反检测)
try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
    logger.info("undetected-chromedriver可用，将使用增强反检测模式")
except ImportError:
    pass

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    pass


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
    engine: str = ""                # 使用的引擎类型
    
    @property
    def content_length(self) -> int:
        """获取内容长度"""
        return len(self.html) if self.html else 0


# ============================================================================
# 用户代理池
# ============================================================================

USER_AGENTS = [
    # Chrome Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    # Chrome macOS
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Chrome Linux
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Firefox
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    # Safari
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    # Edge
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
]


def get_random_user_agent() -> str:
    """获取随机User-Agent"""
    return random.choice(USER_AGENTS)


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
        if not url:
            return False
        
        try:
            parsed = urlparse(url)
            
            # 协议检查
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # 域名检查
            if not parsed.netloc:
                return False
            
            # 排除模式检查
            for pattern in config.exclude_patterns:
                if pattern in url.lower():
                    logger.debug(f"URL匹配排除模式 ({pattern}): {url}")
                    return False
            
            # 白名单检查 (如果配置了)
            if config.allowed_domains:
                domain = parsed.netloc.lower()
                # 去掉www前缀进行比较
                domain_clean = domain.replace('www.', '')
                allowed = any(
                    d.replace('www.', '') in domain_clean or domain_clean in d.replace('www.', '')
                    for d in config.allowed_domains
                )
                if not allowed:
                    logger.debug(f"URL不在白名单中: {url}")
                    return False
            
            return True
            
        except Exception as e:
            logger.debug(f"URL验证失败 ({url}): {e}")
            return False


# ============================================================================
# Selenium引擎 (优化版)
# ============================================================================

class SeleniumEngine(BaseBrowserEngine):
    """
    Selenium浏览器引擎 (优化版)
    
    优化特性:
    - PageLoadStrategy: eager (不等待图片/CSS)
    - 禁用不必要的资源加载
    - 支持undetected-chromedriver
    - 更好的超时和错误处理
    - 懒加载初始化
    """
    
    def __init__(
        self, 
        config: BrowserConfig,
        use_undetected: bool = True,
        lazy_init: bool = False
    ):
        """
        初始化Selenium引擎
        
        Args:
            config: 浏览器配置
            use_undetected: 是否使用undetected-chromedriver
            lazy_init: 是否懒加载初始化 (首次使用时才初始化)
        """
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium未安装，请运行: pip install selenium")
        
        self.config = config
        self.use_undetected = use_undetected and UNDETECTED_AVAILABLE
        self.driver: Optional[Union[webdriver.Chrome, 'uc.Chrome']] = None
        self._initialized = False
        
        if not lazy_init:
            self._init_driver()
    
    def _ensure_initialized(self):
        """确保驱动已初始化"""
        if not self._initialized:
            self._init_driver()
    
    def _init_driver(self):
        """初始化WebDriver (优化版)"""
        if self._initialized:
            return
        
        try:
            if self.use_undetected:
                self._init_undetected_driver()
            else:
                self._init_standard_driver()
            
            self._initialized = True
            mode = "undetected" if self.use_undetected else "standard"
            logger.info(f"Selenium引擎初始化完成 (模式: {mode}, 无头: {self.config.headless})")
            
        except Exception as e:
            error_msg = get_err_message()
            logger.error(f"Selenium引擎初始化失败: {e}")
            logger.debug(error_msg)
            raise
    
    def _init_undetected_driver(self):
        """初始化undetected-chromedriver"""
        options = uc.ChromeOptions()
        
        # 基础配置
        if self.config.headless:
            options.add_argument('--headless=new')
        
        # 性能优化选项
        self._add_performance_options(options)
        
        # 创建驱动
        self.driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            version_main=None  # 自动检测Chrome版本
        )
        
        # 设置超时
        self._configure_timeouts()
    
    def _init_standard_driver(self):
        """初始化标准Selenium驱动"""
        options = ChromeOptions()
        
        # 添加配置选项
        for option in self.config.chrome_options:
            options.add_argument(option)
        
        # 无头模式
        if self.config.headless:
            options.add_argument('--headless=new')
        
        # 性能优化选项
        self._add_performance_options(options)
        
        # 反检测配置
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 【关键优化】PageLoadStrategy设为eager - 不等待所有资源加载
        options.page_load_strategy = 'eager'
        
        # 禁用图片、CSS、字体加载
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.stylesheets": 2,
            "profile.managed_default_content_settings.fonts": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        }
        options.add_experimental_option("prefs", prefs)
        
        # 初始化驱动
        if WEBDRIVER_MANAGER_AVAILABLE:
            try:
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            except Exception as e:
                logger.warning(f"ChromeDriverManager失败: {e}, 尝试直接初始化")
                self.driver = webdriver.Chrome(options=options)
        else:
            self.driver = webdriver.Chrome(options=options)
        
        # 设置超时
        self._configure_timeouts()
        
        # 反检测脚本
        self._inject_anti_detection_script()
    
    def _add_performance_options(self, options):
        """添加性能优化选项"""
        performance_args = [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-extensions',
            '--disable-infobars',
            '--disable-popup-blocking',
            '--disable-notifications',
            '--disable-translate',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-default-apps',
            '--disable-hang-monitor',
            '--disable-prompt-on-repost',
            '--disable-client-side-phishing-detection',
            '--disable-component-update',
            '--disable-domain-reliability',
            '--disable-features=TranslateUI',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-first-run',
            '--safebrowsing-disable-auto-update',
            # 禁用图片 (通过blink设置)
            '--blink-settings=imagesEnabled=false',
            # 窗口大小
            '--window-size=1920,1080',
            # 忽略证书错误
            '--ignore-certificate-errors',
            '--ignore-ssl-errors',
            # 禁用日志
            '--log-level=3',
            '--silent',
        ]
        
        for arg in performance_args:
            try:
                options.add_argument(arg)
            except Exception:
                pass  # 某些选项可能不支持
    
    def _configure_timeouts(self):
        """配置超时设置"""
        if self.driver:
            # 【关键优化】较短的页面加载超时
            self.driver.set_page_load_timeout(self.config.page_load_timeout)
            # 较短的隐式等待
            self.driver.implicitly_wait(min(self.config.implicit_wait, 5))
            # 脚本超时
            self.driver.set_script_timeout(10)
    
    def _inject_anti_detection_script(self):
        """注入反检测脚本"""
        if self.driver and not self.use_undetected:
            try:
                self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                    'source': '''
                        // 隐藏webdriver标志
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        
                        // 修改plugins
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5]
                        });
                        
                        // 修改languages
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['en-US', 'en']
                        });
                        
                        // 隐藏自动化标志
                        window.chrome = { runtime: {} };
                        
                        // 修改权限查询
                        const originalQuery = window.navigator.permissions.query;
                        window.navigator.permissions.query = (parameters) => (
                            parameters.name === 'notifications' ?
                                Promise.resolve({ state: Notification.permission }) :
                                originalQuery(parameters)
                        );
                    '''
                })
            except Exception as e:
                logger.debug(f"注入反检测脚本失败: {e}")
    
    def fetch_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        scroll: bool = False,
        timeout: Optional[int] = None
    ) -> FetchResult:
        """
        获取页面HTML内容 (优化版)
        
        Args:
            url: 目标URL
            wait_for_selector: 等待特定CSS选择器
            scroll: 是否滚动页面触发懒加载
            timeout: 自定义超时时间
            
        Returns:
            FetchResult对象
        """
        self._ensure_initialized()
        
        if not self.is_valid_url(url, self.config):
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=0,
                content_type="",
                fetch_time=0,
                success=False,
                error="无效的URL",
                engine="selenium"
            )
        
        start_time = time.time()
        timeout = timeout or self.config.page_load_timeout
        last_error = ""
        
        for attempt in range(self.config.max_retries):
            try:
                logger.debug(f"Selenium获取: {url} (尝试 {attempt + 1}/{self.config.max_retries})")
                
                # 【优化】使用较短超时，允许timeout后继续
                try:
                    self.driver.get(url)
                except TimeoutException:
                    # 超时但可能已经加载了部分内容
                    logger.debug(f"页面加载超时，尝试获取已加载内容: {url}")
                
                # 【优化】更短的等待时间
                wait_time = min(timeout, 5)
                
                # 等待body元素
                try:
                    if wait_for_selector:
                        WebDriverWait(self.driver, wait_time).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                        )
                    else:
                        WebDriverWait(self.driver, wait_time).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                except TimeoutException:
                    # 继续尝试获取内容
                    pass
                
                # 【优化】减少等待时间
                time.sleep(0.5)
                
                # 滚动页面 (可选)
                if scroll:
                    self._scroll_page_fast()
                
                # 获取HTML
                html_content = self.driver.page_source
                final_url = self.driver.current_url
                
                # 验证内容有效性
                if not html_content or len(html_content) < 100:
                    raise ValueError("获取的内容为空或过短")
                
                fetch_time = time.time() - start_time
                
                logger.success(f"成功获取: {url} (大小: {len(html_content)} 字节, 耗时: {fetch_time:.2f}s)")
                
                # 请求间隔 (随机化)
                delay = self.config.request_delay * random.uniform(0.8, 1.2)
                time.sleep(delay)
                
                return FetchResult(
                    url=url,
                    final_url=final_url,
                    html=html_content,
                    status_code=200,
                    content_type="text/html",
                    fetch_time=fetch_time,
                    success=True,
                    engine="selenium"
                )
                
            except TimeoutException as e:
                last_error = f"页面加载超时: {e}"
                logger.warning(f"页面加载超时: {url}")
                
            except SessionNotCreatedException as e:
                last_error = f"会话创建失败: {e}"
                logger.error(f"Selenium会话创建失败: {e}")
                # 尝试重新初始化
                self._reinitialize_driver()
                
            except WebDriverException as e:
                last_error = f"WebDriver错误: {e}"
                logger.warning(f"WebDriver错误: {e}")
                
                # 检查是否需要重新初始化
                if "session" in str(e).lower() or "connection" in str(e).lower():
                    self._reinitialize_driver()
                
            except Exception as e:
                last_error = f"获取页面异常: {e}"
                logger.error(f"获取页面异常: {e}")
                error_msg = get_err_message()
                logger.debug(error_msg)
            
            if attempt < self.config.max_retries - 1:
                # 递增延迟
                delay = self.config.retry_delay * (attempt + 1)
                time.sleep(delay)
        
        return FetchResult(
            url=url,
            final_url=url,
            html="",
            status_code=0,
            content_type="",
            fetch_time=time.time() - start_time,
            success=False,
            error=last_error or f"获取失败，已重试{self.config.max_retries}次",
            engine="selenium"
        )
    
    def _reinitialize_driver(self):
        """重新初始化驱动"""
        logger.info("正在重新初始化Selenium驱动...")
        try:
            self.close()
        except Exception:
            pass
        
        self._initialized = False
        time.sleep(2)
        self._init_driver()
    
    def _scroll_page_fast(self):
        """快速滚动页面"""
        try:
            # 直接滚动到底部再回顶部
            self.driver.execute_script("""
                window.scrollTo(0, document.body.scrollHeight);
            """)
            time.sleep(0.3)
            self.driver.execute_script("window.scrollTo(0, 0);")
        except Exception as e:
            logger.debug(f"页面滚动失败: {e}")
    
    def _scroll_page(self):
        """滚动页面触发懒加载 (完整版)"""
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            viewport_height = self.driver.execute_script("return window.innerHeight")
            current_position = 0
            max_scrolls = 10  # 限制最大滚动次数
            scroll_count = 0
            
            while current_position < total_height and scroll_count < max_scrolls:
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                time.sleep(0.2)
                current_position += viewport_height
                scroll_count += 1
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height > total_height:
                    total_height = new_height
            
            self.driver.execute_script("window.scrollTo(0, 0);")
            
        except Exception as e:
            logger.debug(f"页面滚动失败: {e}")
    
    def click_element(self, selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """点击元素"""
        self._ensure_initialized()
        try:
            element = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((by, selector))
            )
            element.click()
            time.sleep(0.5)
            logger.debug(f"成功点击: {selector}")
            return True
        except Exception as e:
            logger.warning(f"点击失败 ({selector}): {e}")
            return False
    
    def get_current_url(self) -> str:
        """获取当前URL"""
        self._ensure_initialized()
        return self.driver.current_url if self.driver else ""
    
    def take_screenshot(self, filename: str) -> bool:
        """截图"""
        self._ensure_initialized()
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
                logger.debug(f"关闭浏览器出错: {e}")
            finally:
                self.driver = None
                self._initialized = False
    
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ============================================================================
# Requests引擎 (优化版)
# ============================================================================

class RequestsEngine(BaseBrowserEngine):
    """
    Requests浏览器引擎 (优化版)
    
    优化特性:
    - 连接池复用
    - 自动重试
    - User-Agent轮换
    - 更好的错误处理
    """
    
    def __init__(self, config: BrowserConfig):
        """
        初始化Requests引擎
        
        Args:
            config: 浏览器配置
        """
        self.config = config
        self.session = self._create_session()
        self._request_count = 0
        
        logger.info("Requests引擎初始化完成")
    
    def _create_session(self) -> requests.Session:
        """创建带重试和连接池的Session"""
        session = requests.Session()
        
        # 重试策略
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        
        # 连接池配置
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
            pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 默认请求头
        session.headers.update({
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        })
        
        return session
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        self.session.headers['User-Agent'] = get_random_user_agent()
    
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
                error="无效的URL",
                engine="requests"
            )
        
        start_time = time.time()
        error_msg = ""
        
        # 每10个请求轮换User-Agent
        self._request_count += 1
        if self._request_count % 10 == 0:
            self._rotate_user_agent()
        
        try:
            logger.debug(f"Requests获取: {url}")
            
            response = self.session.get(
                url,
                timeout=self.config.page_load_timeout,
                allow_redirects=True,
                **kwargs
            )
            
            response.raise_for_status()
            
            # 尝试获取正确编码
            if response.encoding is None or response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding or 'utf-8'
            
            html_content = response.text
            fetch_time = time.time() - start_time
            
            logger.success(
                f"成功获取: {url} "
                f"(状态: {response.status_code}, "
                f"大小: {len(html_content)} 字节, "
                f"耗时: {fetch_time:.2f}s)"
            )
            
            # 请求间隔 (随机化)
            delay = self.config.request_delay * random.uniform(0.5, 1.0)
            time.sleep(delay)
            
            return FetchResult(
                url=url,
                final_url=str(response.url),
                html=html_content,
                status_code=response.status_code,
                content_type=response.headers.get('content-type', ''),
                fetch_time=fetch_time,
                success=True,
                engine="requests"
            )
            
        except requests.exceptions.Timeout:
            error_msg = f"请求超时: {url}"
            logger.warning(error_msg)
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP错误 ({e.response.status_code}): {url}"
            logger.warning(error_msg)
            
            return FetchResult(
                url=url,
                final_url=url,
                html="",
                status_code=e.response.status_code if e.response else 0,
                content_type="",
                fetch_time=time.time() - start_time,
                success=False,
                error=error_msg,
                engine="requests"
            )
            
        except requests.exceptions.ConnectionError:
            error_msg = f"连接错误: {url}"
            logger.warning(error_msg)
            
        except requests.exceptions.RequestException as e:
            error_msg = f"请求异常: {e}"
            logger.error(error_msg)
            
        except Exception as e:
            error_msg = f"未知错误: {e}"
            logger.error(error_msg)
            logger.debug(get_err_message())
        
        return FetchResult(
            url=url,
            final_url=url,
            html="",
            status_code=0,
            content_type="",
            fetch_time=time.time() - start_time,
            success=False,
            error=error_msg,
            engine="requests"
        )
    
    def close(self):
        """关闭Session"""
        if self.session:
            try:
                self.session.close()
                logger.info("Requests引擎已关闭")
            except Exception as e:
                logger.debug(f"关闭Session出错: {e}")
    
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ============================================================================
# 混合引擎 (智能切换)
# ============================================================================

class HybridEngine(BaseBrowserEngine):
    """
    混合浏览器引擎 - 智能选择Selenium或Requests
    
    策略:
    - 优先使用Requests (快速)
    - JavaScript页面或失败时回退到Selenium
    """
    
    def __init__(
        self, 
        config: BrowserConfig,
        prefer_selenium: bool = False,
        use_undetected: bool = True
    ):
        """
        初始化混合引擎
        
        Args:
            config: 浏览器配置
            prefer_selenium: 是否优先使用Selenium
            use_undetected: 是否使用undetected-chromedriver
        """
        self.config = config
        self.prefer_selenium = prefer_selenium
        self.use_undetected = use_undetected
        
        # 初始化Requests引擎
        self.requests_engine = RequestsEngine(config)
        
        # 懒加载Selenium引擎
        self._selenium_engine: Optional[SeleniumEngine] = None
        
        # 记录需要Selenium的域名
        self._selenium_domains: set = set()
        
        logger.info(f"混合引擎初始化完成 (优先{'Selenium' if prefer_selenium else 'Requests'})")
    
    @property
    def selenium_engine(self) -> SeleniumEngine:
        """懒加载Selenium引擎"""
        if self._selenium_engine is None:
            logger.info("初始化Selenium引擎...")
            self._selenium_engine = SeleniumEngine(
                self.config, 
                use_undetected=self.use_undetected,
                lazy_init=False
            )
        return self._selenium_engine
    
    def fetch_page(self, url: str, force_selenium: bool = False, **kwargs) -> FetchResult:
        """
        智能获取页面
        
        Args:
            url: 目标URL
            force_selenium: 强制使用Selenium
            **kwargs: 其他参数
            
        Returns:
            FetchResult对象
        """
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # 判断使用哪个引擎
        use_selenium = (
            force_selenium or 
            self.prefer_selenium or
            domain in self._selenium_domains
        )
        
        if use_selenium and SELENIUM_AVAILABLE:
            return self.selenium_engine.fetch_page(url, **kwargs)
        
        # 尝试Requests
        result = self.requests_engine.fetch_page(url, **kwargs)
        
        # 如果Requests失败或内容过短，尝试Selenium
        if not result.success or result.content_length < 500:
            if SELENIUM_AVAILABLE:
                logger.info(f"Requests获取不完整，切换到Selenium: {url}")
                self._selenium_domains.add(domain)
                return self.selenium_engine.fetch_page(url, **kwargs)
        
        return result
    
    def close(self):
        """关闭所有引擎"""
        self.requests_engine.close()
        if self._selenium_engine:
            self._selenium_engine.close()
        logger.info("混合引擎已关闭")
    
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ============================================================================
# 工厂函数
# ============================================================================

def create_browser_engine(
    config: BrowserConfig,
    use_selenium: bool = True,
    use_undetected: bool = True,
    use_hybrid: bool = False
) -> BaseBrowserEngine:
    """
    创建浏览器引擎
    
    Args:
        config: 浏览器配置
        use_selenium: 是否使用Selenium
        use_undetected: 是否使用undetected-chromedriver
        use_hybrid: 是否使用混合模式
        
    Returns:
        浏览器引擎实例
    """
    if use_hybrid:
        return HybridEngine(config, prefer_selenium=use_selenium, use_undetected=use_undetected)
    
    if use_selenium and SELENIUM_AVAILABLE:
        return SeleniumEngine(config, use_undetected=use_undetected)
    
    return RequestsEngine(config)


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    """测试浏览器引擎"""
    import sys
    
    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    
    # 创建配置
    config = BrowserConfig(
        headless=True,
        page_load_timeout=15,
        implicit_wait=5,
        request_delay=1.0,
        max_retries=2
    )
    
    test_url = "https://example.com"
    
    print("\n" + "="*60)
    print("测试Requests引擎")
    print("="*60)
    
    requests_engine = RequestsEngine(config)
    result = requests_engine.fetch_page(test_url)
    print(f"成功: {result.success}")
    print(f"内容长度: {result.content_length}")
    print(f"耗时: {result.fetch_time:.2f}s")
    requests_engine.close()
    
    if SELENIUM_AVAILABLE:
        print("\n" + "="*60)
        print("测试Selenium引擎")
        print("="*60)
        
        try:
            selenium_engine = SeleniumEngine(config, use_undetected=UNDETECTED_AVAILABLE)
            result = selenium_engine.fetch_page(test_url)
            print(f"成功: {result.success}")
            print(f"内容长度: {result.content_length}")
            print(f"耗时: {result.fetch_time:.2f}s")
            selenium_engine.close()
        except Exception as e:
            print(f"Selenium测试失败: {e}")
    
    print("\n" + "="*60)
    print("测试混合引擎")
    print("="*60)
    
    hybrid_engine = create_browser_engine(config, use_hybrid=True)
    result = hybrid_engine.fetch_page(test_url)
    print(f"成功: {result.success}")
    print(f"引擎: {result.engine}")
    print(f"内容长度: {result.content_length}")
    print(f"耗时: {result.fetch_time:.2f}s")
    hybrid_engine.close()
    
    print("\n测试完成!")