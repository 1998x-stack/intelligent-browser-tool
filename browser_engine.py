"""
浏览器引擎 - 基于Selenium的智能网页获取

设计理念:
- 单一职责：专注于获取完整渲染的HTML
- 反爬虫规避：模拟真实用户行为
- 智能等待：处理动态内容加载
- 资源管理：自动清理浏览器实例

参考: CleanRL单文件自包含设计
"""

import time
import random
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin
import hashlib

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, 
    WebDriverException,
    NoSuchElementException
)
from webdriver_manager.chrome import ChromeDriverManager
from loguru import logger

from config import Config, SeleniumConfig


class BrowserEngine:
    """
    浏览器引擎 - 负责获取动态渲染的网页内容
    
    功能:
    - 自动管理ChromeDriver
    - 处理JavaScript渲染
    - 智能滚动加载
    - 反爬虫检测规避
    
    使用示例:
        engine = BrowserEngine(config)
        html = engine.fetch_page("https://example.com")
        engine.close()
    """
    
    def __init__(self, config: Config):
        """
        初始化浏览器引擎
        
        Args:
            config: 全局配置对象
        """
        self.config = config
        self.selenium_config = config.selenium
        self.driver: Optional[webdriver.Chrome] = None
        self._init_driver()
        
        logger.info(f"浏览器引擎初始化完成 - headless={self.selenium_config.headless}")
    
    def _init_driver(self):
        """初始化Chrome WebDriver"""
        options = ChromeOptions()
        
        # 应用配置的Chrome选项
        for opt in self.selenium_config.chrome_options:
            options.add_argument(opt)
        
        # 无头模式
        if self.selenium_config.headless:
            options.add_argument('--headless=new')
        
        # 反检测设置
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 禁用日志输出
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        
        try:
            # 自动下载和管理ChromeDriver
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # 设置超时
            self.driver.set_page_load_timeout(self.selenium_config.page_load_timeout)
            self.driver.implicitly_wait(self.selenium_config.implicit_wait)
            
            # 执行反检测JavaScript
            self._execute_stealth_scripts()
            
            logger.debug("Chrome WebDriver初始化成功")
            
        except Exception as e:
            logger.error(f"WebDriver初始化失败: {e}")
            raise
    
    def _execute_stealth_scripts(self):
        """执行反检测脚本"""
        stealth_scripts = [
            # 隐藏webdriver属性
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            # 修改plugins
            "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})",
            # 修改languages
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})",
        ]
        
        for script in stealth_scripts:
            try:
                self.driver.execute_script(script)
            except:
                pass
    
    def fetch_page(
        self, 
        url: str, 
        wait_for_selector: Optional[str] = None,
        scroll: bool = True
    ) -> Optional[Dict]:
        """
        获取页面内容
        
        Args:
            url: 目标URL
            wait_for_selector: 等待特定元素出现的CSS选择器
            scroll: 是否滚动页面加载更多内容
            
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
    
    def _wait_for_page_load(self):
        """等待页面基本加载完成"""
        try:
            WebDriverWait(self.driver, 10).until(
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
    
    def _scroll_page(self):
        """
        滚动页面以触发懒加载内容
        
        策略:
        1. 逐步向下滚动
        2. 检测页面高度变化
        3. 达到底部或最大次数后停止
        """
        scroll_pause = self.selenium_config.scroll_pause
        max_attempts = self.selenium_config.max_scroll_attempts
        
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        attempts = 0
        
        while attempts < max_attempts:
            # 滚动到底部
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            
            # 等待加载
            time.sleep(scroll_pause)
            
            # 检查高度变化
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            
            if new_height == last_height:
                # 尝试滚动到中间位置再返回底部
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight / 2);"
                )
                time.sleep(0.3)
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                time.sleep(scroll_pause)
                
                final_height = self.driver.execute_script(
                    "return document.body.scrollHeight"
                )
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
        except:
            return False
    
    def click_element(self, selector: str) -> bool:
        """
        点击页面元素
        
        Args:
            selector: CSS选择器
            
        Returns:
            是否成功点击
        """
        try:
            element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            element.click()
            time.sleep(0.5)
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
    
    def get_links(self) -> list:
        """获取当前页面的所有链接"""
        try:
            elements = self.driver.find_elements(By.TAG_NAME, "a")
            links = []
            for elem in elements:
                href = elem.get_attribute("href")
                text = elem.text.strip()
                if href:
                    links.append({'url': href, 'text': text[:100]})
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
        return domain1 == domain2 or domain1.endswith('.' + domain2) or domain2.endswith('.' + domain1)
    except:
        return False


if __name__ == "__main__":
    # 测试浏览器引擎
    from config import get_fast_config
    
    config = get_fast_config()
    
    with BrowserEngine(config) as engine:
        result = engine.fetch_page("https://www.stanford.edu/")
        if result and result.get('success'):
            print(f"标题: {result['title']}")
            print(f"HTML长度: {result['html_length']}")
            print(f"获取时间: {result['fetch_time']:.2f}s")