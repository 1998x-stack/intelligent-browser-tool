"""
内容提取器模块 - 基于Trafilatura的网页内容提取

设计理念 (CleanRL哲学):
- 单文件自包含: 所有内容提取逻辑集中管理
- 透明的处理流程: 提取步骤清晰可追踪
- 最小化抽象: 直接调用Trafilatura
- 便于调试: 详细的提取日志

Trafilatura特点:
- 自动移除广告、导航等噪声
- 保留主要文章内容
- 支持表格和链接提取
- 多语言支持
"""

import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from loguru import logger

from config import ContentConfig, get_err_message

# ============================================================================
# Trafilatura导入
# ============================================================================

try:
    import trafilatura
    from trafilatura import extract, bare_extraction
    from trafilatura.settings import use_config
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    logger.warning("Trafilatura未安装，请运行: pip install trafilatura")


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ExtractedLink:
    """提取的链接"""
    url: str                # 链接URL
    text: str               # 链接文本
    context: str = ""       # 链接上下文
    is_internal: bool = True  # 是否内部链接


@dataclass
class ExtractedContent:
    """提取的内容"""
    url: str                        # 来源URL
    title: str = ""                 # 页面标题
    text: str = ""                  # 主要文本内容
    description: str = ""           # 页面描述
    author: str = ""                # 作者
    date: str = ""                  # 发布日期
    language: str = ""              # 语言
    
    # 结构化内容
    links: List[ExtractedLink] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    
    # 元数据
    word_count: int = 0
    extraction_time: float = 0.0
    success: bool = True
    error: str = ""
    
    # 原始数据 (可选保存)
    raw_html: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'url': self.url,
            'title': self.title,
            'text': self.text,
            'description': self.description,
            'author': self.author,
            'date': self.date,
            'language': self.language,
            'links': [{'url': l.url, 'text': l.text} for l in self.links],
            'emails': self.emails,
            'phones': self.phones,
            'word_count': self.word_count,
        }


# ============================================================================
# 内容提取器类
# ============================================================================

class ContentExtractor:
    """
    内容提取器 - 使用Trafilatura提取网页主要内容
    
    使用方式:
        extractor = ContentExtractor(config)
        content = extractor.extract(html, url)
        print(content.title)
        print(content.text)
    """
    
    def __init__(self, config: ContentConfig):
        """
        初始化内容提取器
        
        Args:
            config: 内容提取配置
        """
        if not TRAFILATURA_AVAILABLE:
            raise ImportError("Trafilatura未安装，请运行: pip install trafilatura")
        
        self.config = config
        
        # 配置Trafilatura
        self.trafilatura_config = use_config()
        self.trafilatura_config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "200")
        self.trafilatura_config.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
        
        logger.info("内容提取器初始化完成")
    
    def extract(self, html: str, url: str) -> ExtractedContent:
        """
        从HTML提取主要内容
        
        Args:
            html: HTML内容
            url: 页面URL
            
        Returns:
            ExtractedContent对象
        """
        import time
        start_time = time.time()
        
        if not html:
            return ExtractedContent(
                url=url,
                success=False,
                error="HTML内容为空"
            )
        
        try:
            # 使用Trafilatura提取
            result = bare_extraction(
                html,
                url=url,
                include_comments=self.config.include_comments,
                include_tables=self.config.include_tables,
                include_links=self.config.include_links,
                include_images=self.config.include_images,
                favor_precision=self.config.favor_precision,
                favor_recall=self.config.favor_recall,
                config=self.trafilatura_config
            )
            
            extraction_time = time.time() - start_time
            
            if not result:
                logger.warning(f"Trafilatura未能提取内容: {url}")
                # 回退到BeautifulSoup
                return self._fallback_extract(html, url, extraction_time)
            
            # 提取链接
            links = self._extract_links(html, url)
            
            # 兼容处理: trafilatura新版本返回Document对象,旧版本返回dict
            # Handle both Document object (new API) and dict (old API)
            if isinstance(result, dict):
                # 旧版本API - 字典
                text_content = result.get('text', '')
                title = result.get('title', '')
                description = result.get('description', '')
                author = result.get('author', '')
                date = result.get('date', '')
                language = result.get('language', '')
            else:
                # 新版本API - Document对象
                text_content = getattr(result, 'text', '') or ''
                title = getattr(result, 'title', '') or ''
                description = getattr(result, 'description', '') or ''
                author = getattr(result, 'author', '') or ''
                date = getattr(result, 'date', '') or ''
                language = getattr(result, 'language', '') or ''
            
            # 提取联系信息
            emails = self._extract_emails(text_content + html)
            phones = self._extract_phones(text_content + html)
            
            content = ExtractedContent(
                url=url,
                title=title,
                text=text_content,
                description=description,
                author=author,
                date=date,
                language=language,
                links=links,
                emails=emails,
                phones=phones,
                word_count=len(text_content.split()) if text_content else 0,
                extraction_time=extraction_time,
                success=True
            )
            
            logger.debug(
                f"提取完成: {url} | "
                f"标题: {content.title[:30]}... | "
                f"字数: {content.word_count} | "
                f"链接: {len(links)} | "
                f"耗时: {extraction_time:.2f}s"
            )
            
            return content
            
        except Exception as e:
            error_msg = get_err_message()
            logger.error(f"内容提取失败: {e}")
            logger.debug(error_msg)
            
            return ExtractedContent(
                url=url,
                extraction_time=time.time() - start_time,
                success=False,
                error=str(e)
            )
    
    def _fallback_extract(
        self,
        html: str,
        url: str,
        extraction_time: float
    ) -> ExtractedContent:
        """
        回退提取方法 - 使用BeautifulSoup
        
        Args:
            html: HTML内容
            url: 页面URL
            extraction_time: 已用时间
            
        Returns:
            ExtractedContent对象
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 移除脚本和样式
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                tag.decompose()
            
            # 提取标题
            title = ""
            if soup.title:
                title = soup.title.string or ""
            
            # 提取主要文本
            text = soup.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)
            
            # 提取链接
            links = self._extract_links(html, url)
            
            return ExtractedContent(
                url=url,
                title=title,
                text=text,
                links=links,
                word_count=len(text.split()),
                extraction_time=extraction_time,
                success=True
            )
            
        except Exception as e:
            logger.error(f"回退提取失败: {e}")
            return ExtractedContent(
                url=url,
                extraction_time=extraction_time,
                success=False,
                error=str(e)
            )
    
    def _extract_links(self, html: str, base_url: str) -> List[ExtractedLink]:
        """
        提取页面中的链接
        
        Args:
            html: HTML内容
            base_url: 基础URL
            
        Returns:
            链接列表
        """
        links = []
        seen_urls = set()
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            base_domain = urlparse(base_url).netloc
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                
                # 跳过无效链接
                if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue
                
                # 规范化URL
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(base_url, href)
                
                # 去重
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                # 获取链接文本
                link_text = a_tag.get_text(strip=True)
                if not link_text:
                    link_text = a_tag.get('title', '')
                
                # 获取上下文
                parent = a_tag.parent
                context = parent.get_text(strip=True)[:100] if parent else ""
                
                # 判断是否内部链接
                link_domain = urlparse(href).netloc
                is_internal = base_domain in link_domain
                
                links.append(ExtractedLink(
                    url=href,
                    text=link_text[:100],
                    context=context,
                    is_internal=is_internal
                ))
            
            # 限制链接数量
            if len(links) > self.config.max_urls_per_page:
                # 优先保留内部链接
                internal = [l for l in links if l.is_internal]
                external = [l for l in links if not l.is_internal]
                links = internal[:self.config.max_urls_per_page]
                if len(links) < self.config.max_urls_per_page:
                    links.extend(external[:self.config.max_urls_per_page - len(links)])
            
            logger.debug(f"提取到 {len(links)} 个链接 (内部: {sum(1 for l in links if l.is_internal)})")
            
        except Exception as e:
            logger.warning(f"链接提取失败: {e}")
        
        return links
    
    def _extract_emails(self, text: str) -> List[str]:
        """提取邮箱地址"""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = list(set(re.findall(pattern, text)))
        return emails[:20]  # 限制数量
    
    def _extract_phones(self, text: str) -> List[str]:
        """提取电话号码"""
        patterns = [
            r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
            r'\b\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        ]
        phones = []
        for pattern in patterns:
            phones.extend(re.findall(pattern, text))
        return list(set(phones))[:10]
    
    def chunk_content(self, content: ExtractedContent) -> List[str]:
        """
        将内容分块
        
        Args:
            content: 提取的内容
            
        Returns:
            文本块列表
        """
        text = content.text
        if not text:
            return []
        
        chunks = []
        chunk_size = self.config.chunk_size
        overlap = self.config.chunk_overlap
        min_size = self.config.min_chunk_size
        
        # 按段落分割
        paragraphs = text.split('\n\n')
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if len(current_chunk) >= min_size:
                    chunks.append(current_chunk)
                
                # 保留重叠
                if overlap > 0 and current_chunk:
                    overlap_text = current_chunk[-overlap:]
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    current_chunk = para
        
        # 添加最后一块
        if current_chunk and len(current_chunk) >= min_size:
            chunks.append(current_chunk)
        
        logger.debug(f"内容分为 {len(chunks)} 块")
        
        return chunks
    
    def get_summary_text(self, content: ExtractedContent, max_length: int = 500) -> str:
        """
        获取内容摘要
        
        Args:
            content: 提取的内容
            max_length: 最大长度
            
        Returns:
            摘要文本
        """
        text = content.text
        if not text:
            return ""
        
        # 清理文本
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 截断
        if len(text) <= max_length:
            return text
        
        # 在句子边界截断
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        if last_period > max_length // 2:
            return truncated[:last_period + 1]
        
        return truncated + "..."


# ============================================================================
# 工厂函数
# ============================================================================

def create_content_extractor(config: ContentConfig = None) -> ContentExtractor:
    """
    创建内容提取器实例
    
    Args:
        config: 内容配置
        
    Returns:
        ContentExtractor实例
    """
    if config is None:
        config = ContentConfig()
    return ContentExtractor(config)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("内容提取器模块测试")
    print("=" * 60)
    
    # 创建提取器
    config = ContentConfig()
    extractor = create_content_extractor(config)
    
    # 测试HTML
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stanford University - Test Page</title>
        <meta name="description" content="Welcome to Stanford">
    </head>
    <body>
        <nav>Navigation menu</nav>
        <main>
            <h1>Welcome to Stanford University</h1>
            <p>Stanford University is a private research university in Stanford, California. 
            The university was founded in 1885 by Leland and Jane Stanford.</p>
            <p>For more information, contact us at admission@stanford.edu or call 650-723-2300.</p>
            <a href="/admission">Admission</a>
            <a href="/research">Research</a>
            <a href="https://external.com">External Link</a>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """
    
    # 提取内容
    print("\n--- 内容提取测试 ---")
    content = extractor.extract(test_html, "https://www.stanford.edu")
    
    print(f"标题: {content.title}")
    print(f"文本: {content.text[:200]}...")
    print(f"字数: {content.word_count}")
    print(f"链接数: {len(content.links)}")
    print(f"邮箱: {content.emails}")
    print(f"电话: {content.phones}")
    print(f"提取耗时: {content.extraction_time:.3f}秒")
    
    # 链接详情
    print("\n--- 链接列表 ---")
    for link in content.links:
        print(f"  - {link.text}: {link.url} (内部: {link.is_internal})")
    
    # 分块测试
    print("\n--- 内容分块测试 ---")
    chunks = extractor.chunk_content(content)
    print(f"分块数量: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"  块{i+1}: {len(chunk)}字符")
    
    # 摘要测试
    print("\n--- 摘要测试 ---")
    summary = extractor.get_summary_text(content, max_length=100)
    print(f"摘要: {summary}")
    
    print("\n" + "=" * 60)
    print("测试完成!")