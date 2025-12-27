"""
内容处理器 - 基于Trafilatura的智能内容提取

设计理念:
- 使用Trafilatura提取高质量文本
- 智能分块处理长文本
- 提取元数据和链接
- 统一的数据结构

参考: Trafilatura最佳实践
"""

from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse
import hashlib
import json
import re

import trafilatura
from trafilatura.settings import use_config
from loguru import logger
from lxml import html as lxml_html
from lxml.etree import _Element

from config import Config, TrafilaturaConfig


class ContentProcessor:
    """
    内容处理器 - 负责从HTML中提取结构化内容
    
    功能:
    - 主要文本内容提取
    - 元数据提取（标题、作者、日期等）
    - 链接提取和分类
    - 文本分块（用于长文本）
    
    使用示例:
        processor = ContentProcessor(config)
        content = processor.extract_content(html, url)
    """
    
    def __init__(self, config: Config):
        """
        初始化内容处理器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.traf_config = config.trafilatura
        self._init_trafilatura_config()
        
        logger.info("内容处理器初始化完成")
    
    def _init_trafilatura_config(self):
        """配置Trafilatura参数"""
        newconfig = use_config()
        newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
        newconfig.set("DEFAULT", "MIN_EXTRACTED_SIZE", 
                     str(self.traf_config.min_text_length))
        newconfig.set("DEFAULT", "MIN_OUTPUT_SIZE", 
                     str(self.traf_config.min_text_length))
        self.trafilatura_config = newconfig
    
    def extract_content(
        self, 
        html_content: str, 
        url: Optional[str] = None
    ) -> Optional[Dict]:
        """
        从HTML中提取内容
        
        Args:
            html_content: HTML内容
            url: 页面URL（用于链接解析）
            
        Returns:
            提取的内容字典
        """
        if not html_content:
            logger.warning("HTML内容为空")
            return None
        
        try:
            # ========== 使用Trafilatura提取内容 ==========
            extracted_json = trafilatura.extract(
                html_content,
                output_format='json',
                include_comments=self.traf_config.extract_comments,
                include_tables=self.traf_config.include_tables,
                include_images=self.traf_config.include_images,
                include_links=self.traf_config.include_links,
                url=url,
                config=self.trafilatura_config,
                with_metadata=True,
                favor_recall=self.traf_config.favor_recall,
                favor_precision=self.traf_config.favor_precision
            )
            
            if not extracted_json:
                logger.warning(f"Trafilatura提取失败: {url}")
                # 尝试使用baseline方法
                return self._fallback_extraction(html_content, url)
            
            # ========== 解析结果 ==========
            result = json.loads(extracted_json)
            
            if 'text' not in result or not result['text']:
                logger.warning(f"未提取到文本内容: {url}")
                return self._fallback_extraction(html_content, url)
            
            # ========== 提取链接 ==========
            links = self._extract_links(html_content, url)
            result['links'] = links
            
            # ========== 文本分块 ==========
            text = result.get('text', '')
            if len(text) > self.traf_config.max_text_length:
                result['chunks'] = self._chunk_text(text)
                result['text_truncated'] = True
            else:
                result['chunks'] = []
                result['text_truncated'] = False
            
            # ========== 生成摘要 ==========
            result['text_preview'] = self._generate_preview(text)
            
            # ========== 添加统计信息 ==========
            result['stats'] = {
                'text_length': len(text),
                'word_count': len(text.split()),
                'num_links': len(links),
                'num_chunks': len(result.get('chunks', [])),
                'content_hash': self._hash_content(text),
                'internal_links': len([l for l in links if l.get('is_internal')]),
                'external_links': len([l for l in links if not l.get('is_internal')])
            }
            
            # ========== 清理数据 ==========
            result = self._make_json_serializable(result)
            
            logger.success(
                f"内容提取成功 - 文本: {result['stats']['text_length']} chars, "
                f"链接: {result['stats']['num_links']}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"内容提取时发生错误: {e}")
            return self._fallback_extraction(html_content, url)
    
    def _fallback_extraction(
        self, 
        html_content: str, 
        url: Optional[str]
    ) -> Optional[Dict]:
        """
        备用提取方法 - 使用baseline
        """
        try:
            from trafilatura import baseline
            postbody, text, len_text = baseline(html_content)
            
            if not text or len_text < self.traf_config.min_text_length:
                return None
            
            return {
                'text': text,
                'text_preview': self._generate_preview(text),
                'title': self._extract_title(html_content),
                'source': url,
                'links': self._extract_links(html_content, url),
                'stats': {
                    'text_length': len_text,
                    'extraction_method': 'baseline'
                }
            }
        except Exception as e:
            logger.warning(f"备用提取也失败: {e}")
            return None
    
    def _extract_title(self, html_content: str) -> str:
        """从HTML中提取标题"""
        try:
            tree = lxml_html.fromstring(html_content)
            
            # 尝试多种方式
            for xpath in ['//title/text()', '//h1/text()', '//meta[@property="og:title"]/@content']:
                elements = tree.xpath(xpath)
                if elements:
                    return str(elements[0]).strip()
            
            return ""
        except:
            return ""
    
    def _extract_links(
        self, 
        html_content: str, 
        base_url: Optional[str]
    ) -> List[Dict]:
        """
        从HTML中提取所有链接
        
        Args:
            html_content: HTML内容
            base_url: 基础URL
            
        Returns:
            链接列表
        """
        links = []
        
        try:
            tree = lxml_html.fromstring(html_content)
            base_domain = urlparse(base_url).netloc if base_url else ""
            
            for element in tree.xpath('//a[@href]'):
                href = element.get('href')
                text = element.text_content().strip()
                
                if not href:
                    continue
                
                # 解析相对URL
                if base_url:
                    full_url = urljoin(base_url, href)
                else:
                    full_url = href
                
                # 验证和分类链接
                if self._is_valid_link(full_url):
                    link_domain = urlparse(full_url).netloc
                    is_internal = base_domain and (
                        link_domain == base_domain or
                        link_domain.endswith('.' + base_domain) or
                        base_domain.endswith('.' + link_domain)
                    )
                    
                    links.append({
                        'url': full_url,
                        'text': text[:200] if text else "",
                        'type': self._classify_link(full_url),
                        'is_internal': is_internal,
                        'priority': self._get_link_priority(full_url, text)
                    })
            
            # 去重并按优先级排序
            unique_links = self._deduplicate_links(links)
            unique_links.sort(key=lambda x: x['priority'], reverse=True)
            
            return unique_links
            
        except Exception as e:
            logger.warning(f"链接提取失败: {e}")
            return []
    
    def _is_valid_link(self, url: str) -> bool:
        """检查链接是否有效"""
        try:
            parsed = urlparse(url)
            
            if not parsed.scheme or not parsed.netloc:
                return False
            
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # 检查排除模式
            url_lower = url.lower()
            for pattern in self.config.crawl.exclude_patterns:
                if pattern in url_lower:
                    return False
            
            return True
            
        except:
            return False
    
    def _classify_link(self, url: str) -> str:
        """链接分类"""
        url_lower = url.lower()
        
        patterns = {
            'admission': ['/admission', '/apply', '/application', '/enroll'],
            'academic': ['/program', '/course', '/academic', '/degree', '/major'],
            'research': ['/research', '/publication', '/paper', '/lab'],
            'faculty': ['/faculty', '/people', '/staff', '/professor'],
            'international': ['/international', '/global', '/abroad'],
            'financial': ['/financial', '/tuition', '/scholarship', '/aid'],
            'news': ['/news', '/blog', '/article', '/press'],
            'event': ['/event', '/conference', '/seminar'],
            'about': ['/about', '/history', '/mission']
        }
        
        for category, keywords in patterns.items():
            if any(kw in url_lower for kw in keywords):
                return category
        
        return 'general'
    
    def _get_link_priority(self, url: str, text: str) -> int:
        """
        计算链接优先级
        
        高优先级: 符合priority_patterns的链接
        中优先级: 有意义文本的链接
        低优先级: 其他链接
        """
        priority = 0
        url_lower = url.lower()
        
        # 检查优先模式
        for pattern in self.config.crawl.priority_patterns:
            if pattern in url_lower:
                priority += 10
                break
        
        # 有意义的链接文本
        if text and len(text) > 10:
            priority += 3
        
        # 包含关键词
        keywords = ['admission', 'apply', 'international', 'program', 'graduate']
        text_lower = (text or '').lower()
        for kw in keywords:
            if kw in url_lower or kw in text_lower:
                priority += 2
        
        return priority
    
    def _deduplicate_links(self, links: List[Dict]) -> List[Dict]:
        """链接去重"""
        seen = set()
        unique = []
        
        for link in links:
            # 规范化URL用于去重
            url = link['url'].rstrip('/').split('?')[0].split('#')[0]
            
            if url not in seen:
                seen.add(url)
                unique.append(link)
        
        return unique
    
    def _chunk_text(
        self, 
        text: str, 
        chunk_size: int = None,
        overlap: int = 200
    ) -> List[Dict]:
        """
        将长文本分块
        
        Args:
            text: 原始文本
            chunk_size: 块大小
            overlap: 重叠大小
            
        Returns:
            文本块列表
        """
        if chunk_size is None:
            chunk_size = self.traf_config.max_text_length
        
        chunks = []
        start = 0
        text_length = len(text)
        chunk_id = 0
        
        # 句子分割正则
        sentence_end = re.compile(r'[.!?。！？]\s+')
        
        while start < text_length:
            end = min(start + chunk_size, text_length)
            
            # 尝试在句子边界分割
            if end < text_length:
                # 向后查找句子结尾
                search_text = text[end-200:end]
                matches = list(sentence_end.finditer(search_text))
                if matches:
                    # 使用最后一个匹配
                    last_match = matches[-1]
                    end = end - 200 + last_match.end()
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                chunks.append({
                    'id': chunk_id,
                    'text': chunk_text,
                    'start': start,
                    'end': end,
                    'length': len(chunk_text),
                    'preview': chunk_text[:100] + '...' if len(chunk_text) > 100 else chunk_text
                })
                chunk_id += 1
            
            # 移动到下一块（考虑重叠）
            start = end - overlap if end < text_length else end
        
        logger.debug(f"文本分为 {len(chunks)} 块")
        return chunks
    
    def _generate_preview(self, text: str, max_length: int = 500) -> str:
        """生成文本预览"""
        if not text:
            return ""
        
        # 清理文本
        text = re.sub(r'\s+', ' ', text).strip()
        
        if len(text) <= max_length:
            return text
        
        # 尝试在句子边界截断
        preview = text[:max_length]
        last_period = preview.rfind('.')
        
        if last_period > max_length * 0.6:
            preview = preview[:last_period + 1]
        else:
            preview = preview.rsplit(' ', 1)[0] + '...'
        
        return preview
    
    def _hash_content(self, text: str) -> str:
        """生成内容哈希值"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    
    def _make_json_serializable(self, obj: Any) -> Any:
        """确保对象可JSON序列化"""
        if isinstance(obj, _Element):
            from lxml import etree
            return etree.tostring(obj, encoding='unicode', method='text')
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return str(obj)
        else:
            return obj
    
    def extract_metadata_only(self, html_content: str) -> Optional[Dict]:
        """仅提取元数据"""
        try:
            metadata = trafilatura.extract_metadata(html_content)
            if metadata:
                return {
                    'title': metadata.title,
                    'author': metadata.author,
                    'url': metadata.url,
                    'hostname': metadata.hostname,
                    'description': metadata.description,
                    'sitename': metadata.sitename,
                    'date': metadata.date,
                    'categories': metadata.categories,
                    'tags': metadata.tags
                }
            return None
        except Exception as e:
            logger.warning(f"元数据提取失败: {e}")
            return None
    
    def clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""
        
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊字符
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        return text.strip()


if __name__ == "__main__":
    # 测试内容处理器
    from config import get_fast_config
    
    config = get_fast_config()
    processor = ContentProcessor(config)
    
    # 测试HTML
    test_html = """
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Welcome to Stanford</h1>
        <p>Stanford University is a private research university.</p>
        <a href="/admissions">Admissions</a>
        <a href="/research">Research</a>
    </body>
    </html>
    """
    
    result = processor.extract_content(test_html, "https://www.stanford.edu/")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False)[:500])