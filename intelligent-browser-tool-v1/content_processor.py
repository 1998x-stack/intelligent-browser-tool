"""
内容处理器 - 基于Trafilatura的智能内容提取

设计理念:
- 使用Trafilatura提取高质量文本
- 智能分块处理长文本
- 提取元数据和链接
- 统一的数据结构
"""

from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
import hashlib
import json

import trafilatura
from trafilatura.settings import use_config
from loguru import logger
from lxml.etree import _Element

from config import Config


class ContentProcessor:
    """
    内容处理器 - 负责从HTML中提取结构化内容
    
    使用Trafilatura进行智能文本提取,包括:
    - 主要文本内容
    - 元数据(标题、作者、日期等)
    - 链接提取和过滤
    - 文本分块
    """
    
    def __init__(self, config: Config):
        """
        初始化内容处理器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self._init_trafilatura_config()
        
        logger.info("内容处理器初始化完成")
    
    def _init_trafilatura_config(self):
        """配置Trafilatura参数"""
        # 创建自定义配置
        newconfig = use_config()
        
        # 设置提取选项
        newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
        newconfig.set("DEFAULT", "MIN_EXTRACTED_SIZE", str(self.config.min_text_length))
        newconfig.set("DEFAULT", "MIN_OUTPUT_SIZE", str(self.config.min_text_length))
        
        self.trafilatura_config = newconfig
    
    def _make_json_serializable(self, obj: Any) -> Any:
        """
        递归清理数据，确保可以JSON序列化
        
        Args:
            obj: 任意对象
            
        Returns:
            可JSON序列化的对象
        """
        # 处理 lxml._Element 对象
        if isinstance(obj, _Element):
            from lxml import etree
            return etree.tostring(obj, encoding='unicode', method='text')
        
        # 处理字典
        elif isinstance(obj, dict):
            return {key: self._make_json_serializable(value) for key, value in obj.items()}
        
        # 处理列表
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        
        # 处理其他不可序列化的对象
        elif hasattr(obj, '__dict__'):
            return str(obj)
        
        # 基本类型直接返回
        else:
            return obj
    
    def extract_content(
        self, 
        html_content: str, 
        url: Optional[str] = None
    ) -> Optional[Dict]:
        """
        从HTML中提取内容
        
        Args:
            html_content: HTML内容
            url: 页面URL(可选,用于链接解析)
            
        Returns:
            提取的内容字典,包含:
            - title: 标题
            - text: 主要文本
            - author: 作者
            - date: 日期
            - links: 链接列表
            - metadata: 其他元数据
        """
        if not html_content:
            logger.warning("HTML内容为空")
            return None
        
        try:
            # ========== 使用Trafilatura提取内容 ==========
            # 使用 extract() 并指定 JSON 格式，避免 lxml 对象序列化问题
            import json
            
            extracted_json = trafilatura.extract(
                html_content,
                output_format='json',  # 直接输出 JSON 格式
                include_comments=self.config.extract_comments,
                include_tables=True,
                include_images=self.config.include_images,
                include_links=self.config.include_links,
                url=url,
                config=self.trafilatura_config,
                with_metadata=True
            )
            
            if not extracted_json:
                logger.warning(f"Trafilatura提取失败: {url}")
                return None
            
            # ========== 处理提取结果 ==========
            # 解析 JSON 字符串为字典
            result = json.loads(extracted_json)
            
            # 确保有 text 字段
            if 'text' not in result or not result['text']:
                logger.warning(f"未提取到文本内容: {url}")
                return None
            
            # ========== 提取链接 ==========
            if self.config.include_links:
                links = self._extract_links(html_content, url)
                result['links'] = links
            
            # ========== 文本分块 ==========
            if 'text' in result and len(result['text']) > self.config.max_text_length:
                result['chunks'] = self._chunk_text(
                    result['text'], 
                    chunk_size=self.config.max_text_length
                )
                result['text_truncated'] = True
            else:
                result['text_truncated'] = False
            
            # ========== 添加统计信息 ==========
            result['stats'] = {
                'text_length': len(result.get('text', '')),
                'num_links': len(result.get('links', [])),
                'num_chunks': len(result.get('chunks', [])),
                'content_hash': self._hash_content(result.get('text', ''))
            }
            
            logger.success(
                f"内容提取成功 - 文本长度: {result['stats']['text_length']}, "
                f"链接数: {result['stats']['num_links']}"
            )
            
            # ========== 最终清理：确保所有数据都可JSON序列化 ==========
            result = self._make_json_serializable(result)
            
            return result
            
        except Exception as e:
            logger.error(f"内容提取时发生错误: {e}", exc_info=True)
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def _extract_links(self, html_content: str, base_url: Optional[str]) -> List[Dict]:
        """
        从HTML中提取所有链接
        
        Args:
            html_content: HTML内容
            base_url: 基础URL(用于相对链接解析)
            
        Returns:
            链接列表,每个链接包含 url 和 text
        """
        links = []
        
        try:
            from lxml import html as lxml_html
            
            # 解析HTML
            tree = lxml_html.fromstring(html_content)
            
            # 提取所有<a>标签
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
                
                # 过滤无效链接
                if self._is_valid_link(full_url):
                    links.append({
                        'url': full_url,
                        'text': text,
                        'type': self._classify_link(full_url)
                    })
            
            # 去重
            unique_links = []
            seen_urls = set()
            for link in links:
                if link['url'] not in seen_urls:
                    unique_links.append(link)
                    seen_urls.add(link['url'])
            
            logger.debug(f"提取了 {len(unique_links)} 个唯一链接")
            return unique_links
            
        except Exception as e:
            logger.warning(f"链接提取失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
    
    def _is_valid_link(self, url: str) -> bool:
        """
        检查链接是否有效
        
        Args:
            url: 链接URL
            
        Returns:
            是否有效
        """
        try:
            parsed = urlparse(url)
            
            # 必须有scheme和netloc
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 只保留http/https
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # 排除特定模式
            if any(pattern in url.lower() for pattern in self.config.exclude_patterns):
                return False
            
            return True
            
        except:
            return False
    
    def _classify_link(self, url: str) -> str:
        """
        简单的链接分类
        
        Args:
            url: 链接URL
            
        Returns:
            链接类型
        """
        url_lower = url.lower()
        
        if any(x in url_lower for x in ['/research', '/publication', '/paper']):
            return 'research'
        elif any(x in url_lower for x in ['/faculty', '/people', '/staff']):
            return 'people'
        elif any(x in url_lower for x in ['/program', '/course', '/academic']):
            return 'academic'
        elif any(x in url_lower for x in ['/news', '/blog', '/article']):
            return 'news'
        elif any(x in url_lower for x in ['/event', '/conference']):
            return 'event'
        else:
            return 'general'
    
    def _chunk_text(self, text: str, chunk_size: int = 5000, overlap: int = 200) -> List[Dict]:
        """
        将长文本分块
        
        Args:
            text: 原始文本
            chunk_size: 块大小
            overlap: 重叠大小
            
        Returns:
            文本块列表
        """
        chunks = []
        start = 0
        text_length = len(text)
        chunk_id = 0
        
        while start < text_length:
            end = start + chunk_size
            
            # 如果不是最后一块,尝试在句号处分割
            if end < text_length:
                # 向后查找句号
                for i in range(end, max(start + chunk_size - 200, start), -1):
                    if text[i] in '.!?。!?':
                        end = i + 1
                        break
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                chunks.append({
                    'id': chunk_id,
                    'text': chunk_text,
                    'start': start,
                    'end': end,
                    'length': len(chunk_text)
                })
                chunk_id += 1
            
            # 移动到下一块(考虑重叠)
            start = end - overlap if end < text_length else end
        
        logger.debug(f"文本分为 {len(chunks)} 块")
        return chunks
    
    def _hash_content(self, text: str) -> str:
        """
        生成内容哈希值(用于去重)
        
        Args:
            text: 文本内容
            
        Returns:
            SHA256哈希值
        """
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    
    def extract_metadata_only(self, html_content: str) -> Optional[Dict]:
        """
        仅提取元数据(不提取全文)
        
        Args:
            html_content: HTML内容
            
        Returns:
            元数据字典
        """
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
                    'tags': metadata.tags,
                    'license': metadata.license
                }
            return None
        except Exception as e:
            logger.warning(f"元数据提取失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None