"""
搜索引擎种子生成器 V2 - Search Engine Seed Generator V2

设计理念 (CleanRL哲学):
- 单文件自包含: 搜索查询构造、搜索执行、结果解析
- 透明的处理流程: 从意图到搜索词到种子URL
- 最小化抽象: 直接的搜索引擎交互
- 便于调试: 详细的搜索过程日志

核心改进 V2:
1. 优先使用 duckduckgo-search 库 (最稳定)
2. Bing: 修正URL参数和CSS选择器
3. DuckDuckGo: 使用lite版本，更好的表单处理
4. Google: 改进Selenium URL构造
5. 增加调试模式，保存HTML便于分析

Author: AI Assistant
Date: 2024
"""

import re
import time
import random
import json
import hashlib
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, quote_plus, urlencode
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from loguru import logger

try:
    from config import BrowserConfig, LLMConfig, get_err_message
except ImportError:
    def get_err_message():
        import sys
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_type is None:
            return "No exception"
        return f"{exc_type.__name__}: {exc_value}"


# ============================================================================
# 配置和数据结构
# ============================================================================

class SearchProvider(Enum):
    """搜索引擎提供商"""
    GOOGLE = "google"
    BING = "bing"
    DUCKDUCKGO = "duckduckgo"
    DUCKDUCKGO_API = "duckduckgo_api"  # 使用 duckduckgo-search 库


@dataclass
class SearchConfig:
    """
    搜索配置
    
    Attributes:
        provider: 搜索引擎提供商
        max_results: 最大结果数
        timeout: 请求超时
        use_selenium: 是否使用Selenium (Google需要)
        language: 搜索语言
        region: 搜索区域
        debug_mode: 调试模式 (保存HTML)
        bypass_proxy: 是否绕过系统代理
        proxy: 自定义代理地址 (如 http://proxy:8080)
    """
    provider: SearchProvider = SearchProvider.DUCKDUCKGO_API
    max_results: int = 5
    timeout: int = 20
    use_selenium: bool = False
    language: str = "en"
    region: str = "us"
    retry_count: int = 1
    delay_range: Tuple[float, float] = (1.0, 2.0)
    debug_mode: bool = False
    debug_dir: str = "/tmp/search_debug"
    bypass_proxy: bool = True   # 默认绕过系统代理
    proxy: Optional[str] = None  # 自定义代理


@dataclass
class SeedURL:
    """
    种子URL数据结构
    
    Attributes:
        url: URL地址
        title: 页面标题
        snippet: 搜索摘要
        source: 来源 (original/google/bing)
        rank: 搜索排名 (0表示原始URL)
        relevance_score: 相关性分数 (0-1)
    """
    url: str
    title: str = ""
    snippet: str = ""
    source: str = "original"
    rank: int = 0
    relevance_score: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "rank": self.rank,
            "relevance_score": self.relevance_score
        }


@dataclass
class SearchQuery:
    """
    搜索查询数据结构
    
    Attributes:
        raw_query: 原始查询
        keywords: 关键词列表
        site_filter: 站点限定 (site:xxx.com)
        full_query: 完整查询字符串
    """
    raw_query: str
    keywords: List[str] = field(default_factory=list)
    site_filter: str = ""
    
    @property
    def full_query(self) -> str:
        """构造完整查询字符串"""
        parts = []
        
        # 关键词 OR 组合
        if self.keywords:
            if len(self.keywords) > 1:
                kw_part = " OR ".join(f'"{kw}"' if ' ' in kw else kw for kw in self.keywords)
                parts.append(f"({kw_part})")
            else:
                parts.append(self.keywords[0])
        elif self.raw_query:
            parts.append(self.raw_query)
        
        # 站点限定
        if self.site_filter:
            parts.append(f"site:{self.site_filter}")
        
        return " ".join(parts)


# ============================================================================
# 搜索查询构造器 (使用LLM)
# ============================================================================

class SearchQueryBuilder:
    """
    搜索查询构造器 - 使用LLM智能生成搜索词
    
    根据用户意图和目标URL，生成优化的搜索查询。
    """
    
    # 搜索查询生成Prompt模板
    QUERY_GENERATION_PROMPT = '''你是一个搜索查询优化专家。根据用户的搜索意图和目标网站，生成最优的搜索查询词。

## 用户意图
{intent}

## 目标网站
{target_url}
域名: {domain}

## 任务
生成3-5个最相关的搜索关键词，用于在搜索引擎中找到相关内容。

## 输出格式 (严格JSON)
```json
{{
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "reasoning": "简短解释为什么选择这些关键词"
}}
```

## 要求
1. 关键词要具体、精准
2. 包含用户意图的核心概念
3. 考虑目标网站的内容特点
4. 优先使用目标网站可能使用的术语
5. 如果意图涉及特定内容类型（如招生、课程、新闻），包含相关词汇

直接输出JSON，不要其他内容:'''

    def __init__(self, llm_client: Optional[Any] = None):
        """
        初始化查询构造器
        
        Args:
            llm_client: LLM客户端实例 (可选，无则使用规则方法)
        """
        self.llm_client = llm_client
        logger.info("搜索查询构造器初始化完成")
    
    def build_query(
        self,
        intent: str,
        target_url: str,
        use_site_filter: bool = True
    ) -> SearchQuery:
        """
        构造搜索查询
        
        Args:
            intent: 用户搜索意图
            target_url: 目标URL
            use_site_filter: 是否使用site:限定符
            
        Returns:
            SearchQuery对象
        """
        # 提取域名
        domain = self._extract_domain(target_url)
        
        # 尝试使用LLM生成
        if self.llm_client:
            try:
                keywords = self._generate_keywords_with_llm(intent, target_url, domain)
                if keywords:
                    return SearchQuery(
                        raw_query=intent,
                        keywords=keywords,
                        site_filter=domain if use_site_filter else ""
                    )
            except Exception as e:
                logger.warning(f"LLM生成搜索词失败: {e}, 使用规则方法")
        
        # 回退到规则方法
        keywords = self._generate_keywords_by_rules(intent, domain)
        
        return SearchQuery(
            raw_query=intent,
            keywords=keywords,
            site_filter=domain if use_site_filter else ""
        )
    
    def _extract_domain(self, url: str) -> str:
        """提取域名"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # 去掉www前缀
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
    
    def _generate_keywords_with_llm(
        self,
        intent: str,
        target_url: str,
        domain: str
    ) -> List[str]:
        """使用LLM生成关键词"""
        prompt = self.QUERY_GENERATION_PROMPT.format(
            intent=intent,
            target_url=target_url,
            domain=domain
        )
        
        # 使用快速模型
        response = self.llm_client.generate(
            prompt=prompt,
            model=self.llm_client.config.fast_model,
            temperature=0.3,
            max_tokens=200
        )
        
        if not response.success:
            logger.warning(f"LLM调用失败: {response.error}")
            return []
        
        # 解析JSON
        keywords = self._parse_keywords_response(response.content)
        
        if keywords:
            logger.info(f"LLM生成关键词: {keywords}")
        
        return keywords
    
    def _parse_keywords_response(self, content: str) -> List[str]:
        """解析LLM响应中的关键词"""
        try:
            # 尝试提取JSON
            json_match = re.search(r'\{[^{}]*"keywords"[^{}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                keywords = data.get('keywords', [])
                if isinstance(keywords, list):
                    return [str(kw).strip() for kw in keywords if kw]
            
            # 尝试直接解析
            data = json.loads(content)
            if 'keywords' in data:
                return [str(kw).strip() for kw in data['keywords'] if kw]
                
        except json.JSONDecodeError:
            # 尝试从文本中提取关键词
            lines = content.strip().split('\n')
            keywords = []
            for line in lines:
                line = line.strip('- •*"\'[]')
                if line and len(line) < 50:
                    keywords.append(line)
            if keywords:
                return keywords[:5]
        
        return []
    
    def _generate_keywords_by_rules(self, intent: str, domain: str) -> List[str]:
        """使用规则生成关键词"""
        keywords = []
        
        # 提取意图中的核心词
        # 移除常见停用词
        stopwords = {
            'i', 'want', 'to', 'find', 'search', 'for', 'about', 'the', 'a', 'an',
            'of', 'in', 'on', 'at', 'from', 'with', 'is', 'are', 'was', 'were',
            'please', 'help', 'me', 'get', 'show', 'give', 'need', 'looking',
            '我', '想', '要', '找', '搜索', '关于', '的', '了', '和', '与', '在',
            '请', '帮', '给', '查', '看'
        }
        
        words = re.findall(r'\b\w+\b', intent.lower())
        meaningful_words = [w for w in words if w not in stopwords and len(w) > 1]
        
        # 保留前5个有意义的词
        keywords = meaningful_words[:5]
        
        # 尝试提取短语 (引号内的内容)
        phrases = re.findall(r'"([^"]+)"', intent)
        keywords.extend(phrases[:2])
        
        # 如果关键词太少，使用整个意图
        if len(keywords) < 2:
            keywords = [intent]
        
        logger.info(f"规则生成关键词: {keywords}")
        return keywords


# ============================================================================
# 搜索引擎抽象基类
# ============================================================================

class BaseSearchEngine(ABC):
    """搜索引擎基类"""
    
    # 更完整的User-Agents列表
    USER_AGENTS = [
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        # Firefox on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        # Safari on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    ]
    
    def __init__(self, config: SearchConfig):
        self.config = config
        self.session = self._create_session()
        
        # 调试目录
        if config.debug_mode:
            Path(config.debug_dir).mkdir(parents=True, exist_ok=True)
    
    def _create_session(self) -> requests.Session:
        """创建HTTP会话"""
        session = requests.Session()
        
        ua = random.choice(self.USER_AGENTS)
        
        session.headers.update({
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        
        # 处理代理设置
        if self.config.bypass_proxy:
            # 绕过系统代理 - 设置空代理
            session.proxies = {
                'http': None,
                'https': None,
            }
            # 清除环境变量中的代理设置
            session.trust_env = False
            logger.debug("已绕过系统代理")
        elif self.config.proxy:
            # 使用自定义代理
            session.proxies = {
                'http': self.config.proxy,
                'https': self.config.proxy,
            }
            logger.debug(f"使用代理: {self.config.proxy}")
        
        return session
    
    @abstractmethod
    def search(self, query: str) -> List[SeedURL]:
        """执行搜索"""
        pass
    
    def _random_delay(self):
        """随机延迟"""
        delay = random.uniform(*self.config.delay_range)
        time.sleep(delay)
    
    def _save_debug_html(self, html: str, prefix: str = "search"):
        """保存HTML用于调试"""
        if not self.config.debug_mode:
            return
        
        timestamp = int(time.time())
        hash_suffix = hashlib.md5(html[:100].encode()).hexdigest()[:8]
        filename = f"{prefix}_{timestamp}_{hash_suffix}.html"
        filepath = Path(self.config.debug_dir) / filename
        
        try:
            filepath.write_text(html, encoding='utf-8')
            logger.debug(f"调试HTML已保存: {filepath}")
        except Exception as e:
            logger.warning(f"保存调试HTML失败: {e}")


# ============================================================================
# DuckDuckGo API 搜索引擎 (推荐 - 使用duckduckgo-search库)
# ============================================================================

class DuckDuckGoAPIEngine(BaseSearchEngine):
    """
    DuckDuckGo API搜索引擎 - 使用duckduckgo-search库
    
    这是最稳定的方法，推荐优先使用。
    pip install duckduckgo-search
    """
    
    def __init__(self, config: SearchConfig):
        super().__init__(config)
        self._ddgs = None
        self._ddgs_available = self._check_ddgs()
    
    def _check_ddgs(self) -> bool:
        """检查duckduckgo-search库是否可用"""
        try:
            from duckduckgo_search import DDGS
            self._ddgs_class = DDGS
            logger.info("duckduckgo-search 库可用")
            return True
        except ImportError:
            logger.warning("duckduckgo-search 库未安装，使用HTML抓取方式")
            logger.info("建议安装: pip install duckduckgo-search")
            return False
    
    def search(self, query: str) -> List[SeedURL]:
        """执行DuckDuckGo搜索"""
        if self._ddgs_available:
            return self._search_with_ddgs(query)
        else:
            return self._search_with_lite(query)
    
    def _search_with_ddgs(self, query: str) -> List[SeedURL]:
        """使用duckduckgo-search库搜索"""
        results = []
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(f"DuckDuckGo API搜索: {query} (尝试 {attempt + 1})")
                
                # 设置代理选项
                proxy = None
                if self.config.proxy:
                    proxy = self.config.proxy
                elif self.config.bypass_proxy:
                    # 绕过代理 - 传入空字符串
                    proxy = ""
                
                # 使用 DDGS 上下文管理器
                ddgs_kwargs = {}
                if proxy is not None:
                    ddgs_kwargs['proxy'] = proxy if proxy else None
                
                with self._ddgs_class(**ddgs_kwargs) as ddgs:
                    # 使用text方法搜索
                    search_results = list(ddgs.text(
                        keywords=query,
                        region=f"{self.config.region}-{self.config.language}",
                        safesearch='moderate',
                        max_results=self.config.max_results + 5
                    ))
                
                if not search_results:
                    logger.warning("DuckDuckGo API返回空结果")
                    self._random_delay()
                    continue
                
                for rank, item in enumerate(search_results, 1):
                    url = item.get('href') or item.get('link', '')
                    title = item.get('title', '')
                    snippet = item.get('body') or item.get('snippet', '')
                    
                    if url and url.startswith('http'):
                        results.append(SeedURL(
                            url=url,
                            title=title,
                            snippet=snippet[:200] if snippet else "",
                            source="duckduckgo_api",
                            rank=rank,
                            relevance_score=1.0 - (rank - 1) * 0.08
                        ))
                
                if results:
                    logger.success(f"DuckDuckGo API搜索成功，获得 {len(results)} 个结果")
                    return results[:self.config.max_results]
                
            except Exception as e:
                logger.warning(f"DuckDuckGo API搜索失败 (尝试 {attempt + 1}): {e}")
                self._random_delay()
        
        # 如果API失败，尝试lite版本
        logger.info("DuckDuckGo API失败，尝试lite版本")
        return self._search_with_lite(query)
    
    def _search_with_lite(self, query: str) -> List[SeedURL]:
        """使用DuckDuckGo lite版本搜索 (备选)"""
        results = []
        
        # DuckDuckGo Lite版本 - 更简单的HTML
        lite_url = "https://lite.duckduckgo.com/lite/"
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(f"DuckDuckGo Lite搜索: {query} (尝试 {attempt + 1})")
                
                # 更新headers
                self.session.headers['User-Agent'] = random.choice(self.USER_AGENTS)
                self.session.headers['Referer'] = 'https://lite.duckduckgo.com/'
                self.session.headers['Origin'] = 'https://lite.duckduckgo.com'
                self.session.headers['Content-Type'] = 'application/x-www-form-urlencoded'
                
                # POST数据
                data = {
                    'q': query,
                    'kl': f'{self.config.region}-{self.config.language}',
                }
                
                response = self.session.post(
                    lite_url,
                    data=data,
                    timeout=self.config.timeout,
                    allow_redirects=True
                )
                
                logger.debug(f"DuckDuckGo Lite状态码: {response.status_code}")
                
                if response.status_code != 200:
                    logger.warning(f"DuckDuckGo Lite返回状态码: {response.status_code}")
                    self._random_delay()
                    continue
                
                # 保存调试HTML
                self._save_debug_html(response.text, "ddg_lite")
                
                # 解析结果
                results = self._parse_lite_results(response.text)
                
                if results:
                    logger.success(f"DuckDuckGo Lite搜索成功，获得 {len(results)} 个结果")
                    return results[:self.config.max_results]
                
                logger.warning("DuckDuckGo Lite未解析到结果")
                self._random_delay()
                
            except requests.exceptions.Timeout:
                logger.warning("DuckDuckGo Lite搜索超时")
            except Exception as e:
                logger.error(f"DuckDuckGo Lite搜索异常: {e}")
            
            self._random_delay()
        
        return results
    
    def _parse_lite_results(self, html: str) -> List[SeedURL]:
        """解析DuckDuckGo Lite结果"""
        results = []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # DuckDuckGo Lite的结果在表格中
            # 查找所有结果链接
            # Lite版本的结构: <table> -> <tr> -> 结果
            
            # 尝试多种选择器
            selectors = [
                'a.result-link',           # 结果链接
                'td a[href^="http"]',       # 表格中的外部链接
                '.result__a',               # 标准结果类
                'a[rel="nofollow"]',        # nofollow链接通常是结果
            ]
            
            links_found = []
            for selector in selectors:
                links = soup.select(selector)
                if links:
                    links_found = links
                    logger.debug(f"使用选择器 '{selector}' 找到 {len(links)} 个链接")
                    break
            
            # 如果还是没找到，尝试更宽泛的方法
            if not links_found:
                # 找所有外部链接
                all_links = soup.find_all('a', href=True)
                for link in all_links:
                    href = link.get('href', '')
                    # 过滤DuckDuckGo内部链接
                    if href.startswith('http') and 'duckduckgo.com' not in href:
                        links_found.append(link)
            
            seen_urls = set()
            for rank, link in enumerate(links_found, 1):
                try:
                    url = link.get('href', '')
                    
                    # 验证URL
                    if not url or not url.startswith('http'):
                        continue
                    
                    # 跳过DuckDuckGo内部链接
                    if 'duckduckgo.com' in url:
                        continue
                    
                    # 跳过重复
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    title = link.get_text(strip=True) or url
                    
                    # 尝试获取摘要 (在相邻元素中)
                    snippet = ""
                    parent = link.find_parent('td') or link.find_parent('tr')
                    if parent:
                        snippet_elem = parent.find_next('td') or parent.find('span')
                        if snippet_elem:
                            snippet = snippet_elem.get_text(strip=True)
                    
                    results.append(SeedURL(
                        url=url,
                        title=title[:100],
                        snippet=snippet[:200],
                        source="duckduckgo_lite",
                        rank=rank,
                        relevance_score=1.0 - (rank - 1) * 0.1
                    ))
                    
                    if len(results) >= self.config.max_results + 5:
                        break
                        
                except Exception as e:
                    logger.debug(f"解析DuckDuckGo Lite结果项失败: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"解析DuckDuckGo Lite结果页失败: {e}")
        
        return results


# ============================================================================
# Bing搜索引擎 (改进版)
# ============================================================================

class BingSearchEngine(BaseSearchEngine):
    """
    Bing搜索引擎 (改进版)
    
    改进:
    - 使用正确的URL参数 (first, rdr)
    - 更好的headers模拟
    - 多个CSS选择器备选
    """
    
    SEARCH_URL = "https://www.bing.com/search"
    
    def search(self, query: str) -> List[SeedURL]:
        """执行Bing搜索"""
        results = []
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(f"Bing搜索: {query} (尝试 {attempt + 1})")
                
                # 构造URL参数 - 使用正确的参数
                params = {
                    'q': query,
                    'first': '1',           # 从第1个结果开始
                    'FORM': 'PERE',         # 表单类型
                    'rdr': '1',             # 重定向标志
                    'setlang': self.config.language,
                    'cc': self.config.region.upper(),
                }
                
                # 更新headers
                ua = random.choice(self.USER_AGENTS)
                self.session.headers.update({
                    'User-Agent': ua,
                    'Referer': 'https://www.bing.com/',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                })
                
                response = self.session.get(
                    self.SEARCH_URL,
                    params=params,
                    timeout=self.config.timeout,
                    allow_redirects=True
                )
                
                logger.debug(f"Bing状态码: {response.status_code}, URL: {response.url}")
                
                if response.status_code != 200:
                    logger.warning(f"Bing返回状态码: {response.status_code}")
                    self._random_delay()
                    continue
                
                # 保存调试HTML
                self._save_debug_html(response.text, "bing")
                
                # 解析结果
                results = self._parse_results(response.text)
                
                if results:
                    logger.success(f"Bing搜索成功，获得 {len(results)} 个结果")
                    return results[:self.config.max_results]
                
                logger.warning("Bing搜索未解析到结果")
                
                # 尝试不同的参数组合
                if attempt == 0:
                    logger.info("尝试简化Bing参数...")
                    params = {'q': query}
                
                self._random_delay()
                
            except requests.exceptions.Timeout:
                logger.warning("Bing搜索超时")
            except Exception as e:
                logger.error(f"Bing搜索异常: {e}")
                logger.debug(get_err_message())
            
            self._random_delay()
        
        return results
    
    def _parse_results(self, html: str) -> List[SeedURL]:
        """解析Bing搜索结果"""
        results = []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 多个选择器尝试
            selectors = [
                ('li.b_algo', 'h2 a', '.b_caption p, p'),          # 标准Bing选择器
                ('div.b_algo', 'h2 a', '.b_caption p, p'),         # div版本
                ('.b_algo', 'a', 'p'),                             # 简化版本
                ('li[class*="algo"]', 'h2 a', 'p'),                # 模糊匹配
            ]
            
            items = []
            title_selector = 'h2 a'
            snippet_selector = 'p'
            
            for container_sel, title_sel, snip_sel in selectors:
                items = soup.select(container_sel)
                if items:
                    title_selector = title_sel
                    snippet_selector = snip_sel
                    logger.debug(f"使用Bing选择器: {container_sel} (找到 {len(items)} 项)")
                    break
            
            if not items:
                # 最后尝试: 直接找所有包含外部链接的元素
                logger.debug("尝试宽泛搜索Bing结果...")
                all_links = soup.find_all('a', href=True)
                seen_urls = set()
                
                for link in all_links:
                    url = link.get('href', '')
                    if (url.startswith('http') and 
                        'bing.com' not in url and 
                        'microsoft.com' not in url and
                        url not in seen_urls):
                        
                        seen_urls.add(url)
                        title = link.get_text(strip=True)
                        
                        if title and len(title) > 5:
                            results.append(SeedURL(
                                url=url,
                                title=title[:100],
                                snippet="",
                                source="bing",
                                rank=len(results) + 1,
                                relevance_score=0.8 - len(results) * 0.05
                            ))
                            
                            if len(results) >= self.config.max_results:
                                break
                
                return results
            
            for rank, item in enumerate(items, 1):
                try:
                    # 提取标题和URL
                    title_elem = item.select_one(title_selector)
                    if not title_elem:
                        # 尝试找任何链接
                        title_elem = item.select_one('a[href^="http"]')
                    
                    if not title_elem:
                        continue
                    
                    url = title_elem.get('href', '')
                    title = title_elem.get_text(strip=True)
                    
                    # 验证URL
                    if not url or not url.startswith('http'):
                        continue
                    
                    # 跳过Bing/Microsoft内部链接
                    if any(domain in url for domain in ['bing.com', 'microsoft.com', 'msn.com']):
                        continue
                    
                    # 提取摘要
                    snippet = ""
                    for snip_sel in snippet_selector.split(', '):
                        snippet_elem = item.select_one(snip_sel)
                        if snippet_elem:
                            snippet = snippet_elem.get_text(strip=True)
                            break
                    
                    results.append(SeedURL(
                        url=url,
                        title=title,
                        snippet=snippet[:200],
                        source="bing",
                        rank=rank,
                        relevance_score=1.0 - (rank - 1) * 0.1
                    ))
                    
                except Exception as e:
                    logger.debug(f"解析Bing结果项失败: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"解析Bing结果页失败: {e}")
        
        return results


# ============================================================================
# Google搜索引擎 (改进版)
# ============================================================================

class GoogleSearchEngine(BaseSearchEngine):
    """
    Google搜索引擎 (改进版)
    
    注意: Google有严格的反爬机制，可能需要:
    - 使用Selenium
    - 代理IP
    
    改进:
    - 更好的URL构造
    - 多个备选选择器
    """
    
    SEARCH_URL = "https://www.google.com/search"
    
    def __init__(self, config: SearchConfig, browser_engine: Optional[Any] = None):
        super().__init__(config)
        self.browser_engine = browser_engine
    
    def search(self, query: str) -> List[SeedURL]:
        """执行Google搜索"""
        # 如果有Selenium引擎，优先使用
        if self.config.use_selenium and self.browser_engine:
            return self._search_with_selenium(query)
        
        return self._search_with_requests(query)
    
    def _search_with_requests(self, query: str) -> List[SeedURL]:
        """使用Requests搜索 (可能被阻止)"""
        results = []
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(f"Google搜索 (Requests): {query} (尝试 {attempt + 1})")
                
                # 构造参数
                params = {
                    'q': query,
                    'num': str(self.config.max_results + 5),
                    'hl': self.config.language,
                    'gl': self.config.region,
                    'safe': 'off',
                }
                
                # 更新headers
                ua = random.choice(self.USER_AGENTS)
                self.session.headers.update({
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': f'{self.config.language}-{self.config.region.upper()},{self.config.language};q=0.9',
                })
                
                response = self.session.get(
                    self.SEARCH_URL,
                    params=params,
                    timeout=self.config.timeout,
                    allow_redirects=True
                )
                
                # 检查是否被阻止
                if response.status_code == 429:
                    logger.warning("Google检测到爬虫 (429 Too Many Requests)")
                    self._random_delay()
                    continue
                
                if 'captcha' in response.text.lower() or 'unusual traffic' in response.text.lower():
                    logger.warning("Google检测到爬虫，需要验证码")
                    self._random_delay()
                    continue
                
                if response.status_code != 200:
                    logger.warning(f"Google返回状态码: {response.status_code}")
                    self._random_delay()
                    continue
                
                # 保存调试HTML
                self._save_debug_html(response.text, "google")
                
                results = self._parse_results(response.text)
                
                if results:
                    logger.success(f"Google搜索成功，获得 {len(results)} 个结果")
                    return results[:self.config.max_results]
                
                logger.warning("Google搜索未解析到结果")
                self._random_delay()
                
            except requests.exceptions.Timeout:
                logger.warning("Google搜索超时")
            except Exception as e:
                logger.error(f"Google搜索异常: {e}")
            
            self._random_delay()
        
        return results
    
    def _search_with_selenium(self, query: str) -> List[SeedURL]:
        """使用Selenium搜索"""
        if not self.browser_engine:
            logger.warning("Selenium引擎未提供")
            return self._search_with_requests(query)
        
        try:
            logger.info(f"Google搜索 (Selenium): {query}")
            
            # 正确构造搜索URL
            encoded_query = quote_plus(query)
            search_url = f"{self.SEARCH_URL}?q={encoded_query}&num={self.config.max_results + 5}"
            
            logger.debug(f"Google Selenium URL: {search_url}")
            
            # 验证URL
            if not search_url.startswith('http'):
                logger.error(f"无效的URL: {search_url}")
                return []
            
            # 获取页面
            result = self.browser_engine.fetch_page(search_url)
            
            if not result.success:
                logger.warning(f"Selenium获取Google页面失败: {result.error}")
                return []
            
            # 保存调试HTML
            if result.html:
                self._save_debug_html(result.html, "google_selenium")
            
            # 解析结果
            return self._parse_results(result.html)
            
        except Exception as e:
            logger.error(f"Selenium Google搜索失败: {e}")
            return []
    
    def _parse_results(self, html: str) -> List[SeedURL]:
        """解析Google搜索结果"""
        results = []
        
        if not html:
            return results
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 多个选择器尝试
            selectors = [
                'div.g',                    # 主要结果容器
                'div[data-sokoban-container]',  # 新版容器
                'div.tF2Cxc',               # 结果容器
                'div[class*="g "]',         # 模糊匹配
            ]
            
            items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    logger.debug(f"使用Google选择器: {selector} (找到 {len(items)} 项)")
                    break
            
            for rank, item in enumerate(items, 1):
                try:
                    # 提取链接
                    link = item.select_one('a[href^="http"]')
                    if not link:
                        continue
                    
                    url = link.get('href', '')
                    
                    # 跳过Google内部链接
                    if 'google.com' in url or 'google.' in url:
                        continue
                    
                    # 提取标题
                    title_elem = item.select_one('h3') or link
                    title = title_elem.get_text(strip=True) if title_elem else ""
                    
                    # 提取摘要
                    snippet = ""
                    for snippet_sel in ['div.VwiC3b', 'span.aCOpRe', 'div.IsZvec', '.st']:
                        snippet_elem = item.select_one(snippet_sel)
                        if snippet_elem:
                            snippet = snippet_elem.get_text(strip=True)
                            break
                    
                    if url and title:
                        results.append(SeedURL(
                            url=url,
                            title=title,
                            snippet=snippet[:200],
                            source="google",
                            rank=rank,
                            relevance_score=1.0 - (rank - 1) * 0.1
                        ))
                        
                except Exception as e:
                    logger.debug(f"解析Google结果项失败: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"解析Google结果页失败: {e}")
        
        return results


# ============================================================================
# DuckDuckGo HTML搜索引擎 (备用)
# ============================================================================

class DuckDuckGoSearchEngine(BaseSearchEngine):
    """
    DuckDuckGo HTML版本搜索引擎 (备用)
    
    使用html.duckduckgo.com，需要JavaScript渲染可能会有问题。
    推荐使用DuckDuckGoAPIEngine。
    """
    
    SEARCH_URL = "https://html.duckduckgo.com/html/"
    
    def search(self, query: str) -> List[SeedURL]:
        """执行DuckDuckGo搜索"""
        results = []
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(f"DuckDuckGo HTML搜索: {query} (尝试 {attempt + 1})")
                
                # 更新headers
                self.session.headers['User-Agent'] = random.choice(self.USER_AGENTS)
                self.session.headers['Referer'] = 'https://html.duckduckgo.com/'
                self.session.headers['Origin'] = 'https://html.duckduckgo.com'
                
                # POST数据
                data = {
                    'q': query,
                    'b': '',
                    'kl': f'{self.config.region}-{self.config.language}',
                }
                
                response = self.session.post(
                    self.SEARCH_URL,
                    data=data,
                    timeout=self.config.timeout,
                    allow_redirects=True
                )
                
                logger.debug(f"DuckDuckGo HTML状态码: {response.status_code}")
                
                # 202表示正在处理，等待后重试
                if response.status_code == 202:
                    logger.info("DuckDuckGo返回202，等待后重试...")
                    time.sleep(2)
                    continue
                
                if response.status_code != 200:
                    logger.warning(f"DuckDuckGo返回状态码: {response.status_code}")
                    self._random_delay()
                    continue
                
                # 保存调试HTML
                self._save_debug_html(response.text, "ddg_html")
                
                results = self._parse_results(response.text)
                
                if results:
                    logger.success(f"DuckDuckGo HTML搜索成功，获得 {len(results)} 个结果")
                    return results[:self.config.max_results]
                
                logger.warning("DuckDuckGo HTML未解析到结果")
                self._random_delay()
                
            except requests.exceptions.Timeout:
                logger.warning("DuckDuckGo HTML搜索超时")
            except Exception as e:
                logger.error(f"DuckDuckGo HTML搜索异常: {e}")
            
            self._random_delay()
        
        return results
    
    def _parse_results(self, html: str) -> List[SeedURL]:
        """解析DuckDuckGo HTML版本结果"""
        results = []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 多个选择器
            selectors = [
                ('div.result', 'a.result__a', 'a.result__snippet'),
                ('div.results_links_deep', 'a.result__a', 'a.result__snippet'),
                ('div.links_deep', 'a.result__a', 'a.result__snippet'),
                ('tr', 'a[href^="http"]', 'td'),  # 表格形式
            ]
            
            items = []
            link_selector = 'a.result__a'
            snippet_selector = 'a.result__snippet'
            
            for container_sel, link_sel, snip_sel in selectors:
                items = soup.select(container_sel)
                if items:
                    link_selector = link_sel
                    snippet_selector = snip_sel
                    logger.debug(f"使用DuckDuckGo选择器: {container_sel} (找到 {len(items)} 项)")
                    break
            
            seen_urls = set()
            for rank, item in enumerate(items, 1):
                try:
                    link = item.select_one(link_selector)
                    if not link:
                        link = item.select_one('a[href^="http"]')
                    
                    if not link:
                        continue
                    
                    url = link.get('href', '')
                    title = link.get_text(strip=True)
                    
                    # 处理URL
                    if url.startswith('//'):
                        url = 'https:' + url
                    
                    # 验证URL
                    if not url.startswith('http'):
                        continue
                    
                    # 跳过DuckDuckGo内部链接
                    if 'duckduckgo.com' in url:
                        continue
                    
                    # 跳过重复
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    # 获取摘要
                    snippet = ""
                    snippet_elem = item.select_one(snippet_selector)
                    if snippet_elem:
                        snippet = snippet_elem.get_text(strip=True)
                    
                    results.append(SeedURL(
                        url=url,
                        title=title[:100],
                        snippet=snippet[:200],
                        source="duckduckgo_html",
                        rank=rank,
                        relevance_score=1.0 - (rank - 1) * 0.1
                    ))
                    
                except Exception as e:
                    logger.debug(f"解析DuckDuckGo HTML结果项失败: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"解析DuckDuckGo HTML结果页失败: {e}")
        
        return results


# ============================================================================
# 种子URL生成器 (主类)
# ============================================================================

class SeedURLGenerator:
    """
    种子URL生成器
    
    整合搜索查询构造和搜索执行，生成种子URL列表。
    
    使用方式:
        generator = SeedURLGenerator(llm_client, config)
        seeds = generator.generate(
            intent="找斯坦福大学的招生信息",
            original_url="https://www.stanford.edu"
        )
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        search_config: Optional[SearchConfig] = None,
        browser_engine: Optional[Any] = None
    ):
        """
        初始化种子URL生成器
        
        Args:
            llm_client: LLM客户端 (用于生成搜索词)
            search_config: 搜索配置
            browser_engine: 浏览器引擎 (用于Google Selenium搜索)
        """
        self.search_config = search_config or SearchConfig()
        self.query_builder = SearchQueryBuilder(llm_client)
        self.browser_engine = browser_engine
        
        # 创建搜索引擎实例
        self._search_engines: Dict[SearchProvider, BaseSearchEngine] = {}
        
        logger.info(f"种子URL生成器初始化完成 (搜索引擎: {self.search_config.provider.value})")
    
    def _get_search_engine(self, provider: SearchProvider) -> BaseSearchEngine:
        """获取搜索引擎实例 (懒加载)"""
        if provider not in self._search_engines:
            if provider == SearchProvider.DUCKDUCKGO_API:
                self._search_engines[provider] = DuckDuckGoAPIEngine(self.search_config)
            elif provider == SearchProvider.BING:
                self._search_engines[provider] = BingSearchEngine(self.search_config)
            elif provider == SearchProvider.GOOGLE:
                self._search_engines[provider] = GoogleSearchEngine(
                    self.search_config, 
                    self.browser_engine
                )
            elif provider == SearchProvider.DUCKDUCKGO:
                self._search_engines[provider] = DuckDuckGoSearchEngine(self.search_config)
        
        return self._search_engines[provider]
    
    def generate(
        self,
        intent: str,
        original_url: str,
        include_original: bool = True,
        use_site_filter: bool = True,
        fallback_providers: bool = True
    ) -> List[SeedURL]:
        """
        生成种子URL列表
        
        Args:
            intent: 用户搜索意图
            original_url: 原始URL
            include_original: 是否包含原始URL
            use_site_filter: 是否使用site:限定符
            fallback_providers: 是否在失败时尝试其他搜索引擎
            
        Returns:
            SeedURL列表 (已去重排序)
        """
        seeds: List[SeedURL] = []
        
        # 1. 添加原始URL作为种子
        if include_original:
            original_seed = SeedURL(
                url=original_url,
                title="原始URL / Original URL",
                snippet="用户提供的起始URL",
                source="original",
                rank=0,
                relevance_score=1.0
            )
            seeds.append(original_seed)
            logger.info(f"添加原始URL作为种子: {original_url}")
        
        # 2. 构造搜索查询
        query = self.query_builder.build_query(
            intent=intent,
            target_url=original_url,
            use_site_filter=use_site_filter
        )
        
        logger.info(f"生成搜索查询: {query.full_query}")
        
        # 3. 执行搜索
        search_results = self._execute_search(
            query.full_query,
            fallback_providers
        )
        
        # 4. 合并结果
        seeds.extend(search_results)
        
        # 5. 去重
        seeds = self._deduplicate(seeds)
        
        # 6. 排序 (原始URL优先，然后按相关性)
        seeds = self._sort_seeds(seeds)
        
        logger.info(f"生成种子URL完成，共 {len(seeds)} 个")
        for i, seed in enumerate(seeds):
            logger.debug(f"  [{i+1}] [{seed.source}] {seed.title[:30]}... - {seed.url}")
        
        return seeds
    
    def _execute_search(
        self,
        query: str,
        fallback_providers: bool
    ) -> List[SeedURL]:
        """执行搜索"""
        results = []
        
        # 获取主搜索引擎
        engine = self._get_search_engine(self.search_config.provider)
        results = engine.search(query)
        
        # 如果主搜索引擎失败，尝试备选
        if not results and fallback_providers:
            # 备选顺序: DuckDuckGo API -> Bing -> DuckDuckGo HTML -> Google
            fallback_order = [
                SearchProvider.DUCKDUCKGO_API,
                SearchProvider.BING,
                SearchProvider.DUCKDUCKGO,
                SearchProvider.GOOGLE
            ]
            
            for provider in fallback_order:
                if provider == self.search_config.provider:
                    continue
                
                logger.info(f"尝试备选搜索引擎: {provider.value}")
                engine = self._get_search_engine(provider)
                results = engine.search(query)
                
                if results:
                    logger.success(f"备选搜索引擎 {provider.value} 成功")
                    break
        
        return results
    
    def _deduplicate(self, seeds: List[SeedURL]) -> List[SeedURL]:
        """去重"""
        seen_urls = set()
        unique_seeds = []
        
        for seed in seeds:
            # 规范化URL用于去重
            normalized = self._normalize_url(seed.url)
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                unique_seeds.append(seed)
        
        return unique_seeds
    
    def _normalize_url(self, url: str) -> str:
        """规范化URL"""
        try:
            parsed = urlparse(url)
            # 去掉协议、www、尾部斜杠
            normalized = parsed.netloc.replace('www.', '') + parsed.path.rstrip('/')
            return normalized.lower()
        except Exception:
            return url.lower()
    
    def _sort_seeds(self, seeds: List[SeedURL]) -> List[SeedURL]:
        """排序种子URL"""
        # 原始URL排最前，然后按来源和相关性排序
        def sort_key(seed: SeedURL):
            source_priority = {
                'original': 0,
                'duckduckgo_api': 1,
                'google': 2,
                'bing': 3,
                'duckduckgo_lite': 4,
                'duckduckgo_html': 5,
                'duckduckgo': 6,
            }
            return (
                source_priority.get(seed.source, 99),
                -seed.relevance_score,
                seed.rank
            )
        
        return sorted(seeds, key=sort_key)
    
    def generate_multiple_queries(
        self,
        intent: str,
        original_url: str,
        num_queries: int = 2
    ) -> List[SeedURL]:
        """
        使用多个查询变体生成更多种子
        
        Args:
            intent: 用户意图
            original_url: 原始URL
            num_queries: 查询变体数量
            
        Returns:
            合并去重后的SeedURL列表
        """
        all_seeds = []
        
        # 查询1: 带site:限定符
        seeds1 = self.generate(intent, original_url, use_site_filter=True)
        all_seeds.extend(seeds1)
        
        # 查询2: 不带site:限定符 (扩大搜索范围)
        if num_queries > 1:
            seeds2 = self.generate(
                intent, original_url, 
                include_original=False, 
                use_site_filter=False
            )
            all_seeds.extend(seeds2)
        
        # 去重并返回
        return self._deduplicate(all_seeds)


# ============================================================================
# 便捷函数
# ============================================================================

def generate_seed_urls(
    intent: str,
    original_url: str,
    llm_client: Optional[Any] = None,
    search_config: Optional[SearchConfig] = None,
    max_results: int = 5,
    include_original: bool = True
) -> List[SeedURL]:
    """
    便捷函数 - 生成种子URL
    
    Args:
        intent: 用户搜索意图
        original_url: 原始URL
        llm_client: LLM客户端 (可选)
        search_config: 搜索配置 (可选)
        max_results: 最大结果数
        include_original: 是否包含原始URL
        
    Returns:
        SeedURL列表
    
    Example:
        seeds = generate_seed_urls(
            intent="找斯坦福大学的招生信息",
            original_url="https://www.stanford.edu",
            max_results=5
        )
    """
    if search_config is None:
        search_config = SearchConfig(
            provider=SearchProvider.DUCKDUCKGO_API,  # 默认使用最稳定的
            max_results=max_results
        )
    
    generator = SeedURLGenerator(llm_client, search_config)
    return generator.generate(
        intent=intent,
        original_url=original_url,
        include_original=include_original
    )


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    """测试搜索引擎种子生成器"""
    import sys
    
    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level:<8} | {message}")
    
    print("\n" + "="*70)
    print("搜索引擎种子生成器 V2 测试")
    print("="*70)
    
    # 测试配置
    test_cases = [
        {
            "intent": "Stanford University undergraduate admission requirements",
            "url": "https://www.stanford.edu"
        },
        {
            "intent": "Python web scraping tutorial",
            "url": "https://www.python.org"
        },
    ]
    
    # 测试不同的搜索引擎
    providers_to_test = [
        SearchProvider.DUCKDUCKGO_API,
        SearchProvider.BING,
    ]
    
    for provider in providers_to_test:
        print(f"\n{'='*70}")
        print(f"测试搜索引擎: {provider.value}")
        print("="*70)
        
        config = SearchConfig(
            provider=provider,
            max_results=5,
            timeout=20,
            debug_mode=True,
            debug_dir="/tmp/search_debug"
        )
        
        generator = SeedURLGenerator(
            llm_client=None,
            search_config=config
        )
        
        for i, case in enumerate(test_cases, 1):
            print(f"\n--- 测试用例 {i}: {case['intent'][:40]}... ---")
            print(f"原始URL: {case['url']}")
            
            try:
                seeds = generator.generate(
                    intent=case['intent'],
                    original_url=case['url']
                )
                
                print(f"\n找到 {len(seeds)} 个种子URL:")
                for j, seed in enumerate(seeds):
                    print(f"\n[{j+1}] {seed.source.upper()}")
                    print(f"    标题: {seed.title[:50]}...")
                    print(f"    URL: {seed.url}")
                    print(f"    相关度: {seed.relevance_score:.2f}")
                    if seed.snippet:
                        print(f"    摘要: {seed.snippet[:80]}...")
            
            except Exception as e:
                print(f"测试失败: {e}")
                logger.exception("详细错误")
            
            # 每个测试之间等待
            time.sleep(2)
    
    print("\n" + "="*70)
    print("测试完成!")
    print("="*70)