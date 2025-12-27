ollama & selenium/requests（两者可选） & trafilatura构建一个浏览器自动化工具。
- 首先用户输入一个网址（必须，默认为斯坦福官方网站）和意图（必须，或者默认为招生）
- 根据意图，使用qwen3-1.7b 将意图转化为AI的prompt背景/组件（如包含意图类别（必须），例子：需要内容、数据、邮件、政策、邮件（根据用户输入意图可选））
- 从初始网站开始，selenium/requests获取网页html，trafilatura提取网页内容
- ollama qwen3 0.6b模型结合上述prompt背景/组件，直接输出意图，然后采用正则提取匹配，获取精准意图
- qwen3-1.7b提取网页内容，结合上述prompt背景/组件，获取核心内容数据等等，尤其要注意，输出下一个值得关注的url列表，以及URL的1-3优先级；
- 首先需要搜索调查selenium，requests ，trafilatura的工作机制/skills，思考网页提取的方法，构建分块网页的技巧和功能
- 思考prompts体系
- 收集各方面的数据，数据&llm结果 保存需要分层次保存，参考skills的文件涉及哲学，以及命名方式采用qwen3-0.6b模型命名，方便后续提取整合
- 最后生成全方面的报告体系folder，包含各方面内容的markdowns

design code category and give me file by file

采用loguru
```
for exception
def get_err_message():
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message
```
以及参考cleanRL代码设计原则和哲学 系统设计代码框架，give me file by file
参考 **CleanRL** 的设计哲学：
1. **单文件自包含**: 每个模块独立完整
2. **透明的处理流程**: 主流程清晰可见
3. **最小化抽象**: 直接的函数调用
4. **便于调试**: 详细的日志输出




reference code:

```
"""
浏览器引擎 - 基于Selenium的网页获取和交互

设计理念:
- 封装Selenium的复杂性
- 提供简单的fetch_page接口
- 智能等待和错误处理
- 支持多种浏览器
"""

import time
from typing import Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from loguru import logger

from config import Config


class BrowserEngine:
    """
    浏览器引擎 - 负责网页获取和基本交互
    
    使用Selenium WebDriver控制浏览器,支持:
    - 自动处理JavaScript渲染
    - 智能等待页面加载
    - 反爬虫检测规避
    """
    
    def __init__(self, config: Config):
        """
        初始化浏览器引擎
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
        self._init_driver()
        
        logger.info(f"浏览器引擎初始化完成 (类型: {config.browser_type}, 无头模式: {config.headless})")
    
    def _init_driver(self):
        """初始化WebDriver"""
        if self.config.browser_type == "chrome":
            self.driver = self._init_chrome_driver()
        elif self.config.browser_type == "firefox":
            self.driver = self._init_firefox_driver()
        else:
            raise ValueError(f"不支持的浏览器类型: {self.config.browser_type}")
        
        # 设置超时
        self.driver.set_page_load_timeout(self.config.page_load_timeout)
        self.driver.implicitly_wait(self.config.implicit_wait)
    
    def _init_chrome_driver(self) -> webdriver.Chrome:
        """初始化Chrome驱动"""
        options = ChromeOptions()
        
        # 添加配置的选项
        for option in self.config.chrome_options:
            options.add_argument(option)
        
        # 无头模式
        if self.config.headless:
            options.add_argument('--headless=new')  # 新版无头模式
        
        # 反检测配置
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 禁用图片加载以提高速度(可选)
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        
        # 自动下载和管理ChromeDriver
        service = ChromeService(ChromeDriverManager().install())
        
        driver = webdriver.Chrome(service=service, options=options)
        
        # 执行CDP命令以进一步反检测
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        
        return driver
    
    def _init_firefox_driver(self) -> webdriver.Firefox:
        """初始化Firefox驱动"""
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        from selenium.webdriver.firefox.service import Service as FirefoxService
        from webdriver_manager.firefox import GeckoDriverManager
        
        options = FirefoxOptions()
        if self.config.headless:
            options.add_argument('--headless')
        
        service = FirefoxService(GeckoDriverManager().install())
        return webdriver.Firefox(service=service, options=options)
    
    def fetch_page(self, url: str, wait_for_selector: Optional[str] = None) -> Optional[str]:
        """
        获取页面HTML内容
        
        Args:
            url: 目标URL
            wait_for_selector: 可选的CSS选择器,等待特定元素加载
            
        Returns:
            页面HTML内容,失败返回None
        """
        if not self._is_valid_url(url):
            logger.warning(f"无效的URL: {url}")
            return None
        
        retries = 0
        while retries < self.config.max_retries:
            try:
                logger.debug(f"正在获取页面: {url} (尝试 {retries + 1}/{self.config.max_retries})")
                
                # 加载页面
                self.driver.get(url)
                
                # 等待特定元素(如果指定)
                if wait_for_selector:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                    )
                else:
                    # 等待body元素加载
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                
                # 额外等待JavaScript执行
                time.sleep(1)
                
                # 滚动页面以触发懒加载
                self._scroll_page()
                
                # 获取渲染后的HTML
                html_content = self.driver.page_source
                
                logger.success(f"成功获取页面: {url} (大小: {len(html_content)} 字节)")
                
                # 请求间隔
                time.sleep(self.config.request_delay)
                
                return html_content
                
            except TimeoutException:
                logger.warning(f"页面加载超时: {url}")
                retries += 1
                if retries < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
            
            except WebDriverException as e:
                logger.error(f"WebDriver错误: {e}")
                retries += 1
                if retries < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
            
            except Exception as e:
                logger.error(f"获取页面时发生错误: {e}", exc_info=True)
                break
        
        return None
    
    def _scroll_page(self):
        """
        滚动页面以触发懒加载内容
        使用平滑滚动,模拟真实用户行为
        """
        try:
            # 获取页面总高度
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            
            # 分段滚动
            viewport_height = self.driver.execute_script("return window.innerHeight")
            current_position = 0
            
            while current_position < total_height:
                # 滚动一个视口的距离
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                time.sleep(0.3)  # 短暂等待内容加载
                current_position += viewport_height
                
                # 重新获取高度(可能有新内容加载)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height > total_height:
                    total_height = new_height
            
            # 滚动回顶部
            self.driver.execute_script("window.scrollTo(0, 0);")
            
        except Exception as e:
            logger.debug(f"页面滚动失败: {e}")
    
    def _is_valid_url(self, url: str) -> bool:
        """
        验证URL是否有效且符合配置的域名限制
        
        Args:
            url: 待验证的URL
            
        Returns:
            是否有效
        """
        try:
            parsed = urlparse(url)
            
            # 基本验证
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 域名白名单检查
            if self.config.allowed_domains:
                domain_match = any(
                    domain in parsed.netloc 
                    for domain in self.config.allowed_domains
                )
                if not domain_match:
                    logger.debug(f"域名不在白名单: {parsed.netloc}")
                    return False
            
            # 排除模式检查
            if any(pattern in url for pattern in self.config.exclude_patterns):
                logger.debug(f"URL匹配排除模式: {url}")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"URL验证失败: {e}")
            return False
    
    def click_element(self, selector: str, by: By = By.CSS_SELECTOR) -> bool:
        """
        点击页面元素
        
        Args:
            selector: 元素选择器
            by: 选择器类型
            
        Returns:
            是否成功
        """
        try:
            element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((by, selector))
            )
            element.click()
            time.sleep(1)  # 等待页面响应
            logger.debug(f"成功点击元素: {selector}")
            return True
        except Exception as e:
            logger.warning(f"点击元素失败 ({selector}): {e}")
            return False
    
    def get_current_url(self) -> str:
        """获取当前页面URL"""
        return self.driver.current_url if self.driver else ""
    
    def take_screenshot(self, filename: str) -> bool:
        """
        截图当前页面
        
        Args:
            filename: 保存的文件名
            
        Returns:
            是否成功
        """
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
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.error(f"关闭浏览器时出错: {e}")
    
    def __del__(self):
        """析构函数 - 确保浏览器关闭"""
        self.close()
```