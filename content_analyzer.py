"""
内容分析器模块 - 使用LLM分析网页内容

设计理念 (CleanRL哲学):
- 单文件自包含: 内容分析逻辑完整独立
- 透明的处理流程: 分析步骤清晰可见
- 最小化抽象: 直接的LLM调用
- 便于调试: 详细的分析日志

功能:
- 提取核心内容数据
- 识别相关URL并排序优先级
- 生成结构化分析结果
"""

import re
import json
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin

from loguru import logger

from config import URLPriority, get_err_message
from llm_client import LLMClient, LLMResponse
from intent_analyzer import IntentComponents
from content_extractor import ExtractedContent, ExtractedLink
from utils import extract_json_from_text, truncate_text


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class PrioritizedURL:
    """带优先级的URL"""
    url: str                        # URL地址
    priority: int                   # 优先级 (1=高, 2=中, 3=低)
    reason: str                     # 优先级原因
    link_text: str = ""             # 链接文本
    
    def __lt__(self, other):
        """比较方法，用于排序"""
        return self.priority < other.priority


@dataclass
class AnalysisResult:
    """内容分析结果"""
    url: str                                    # 分析的URL
    relevance_score: float                      # 相关度分数 (0-1)
    key_findings: List[str]                     # 关键发现
    extracted_data: Dict[str, Any]              # 提取的数据
    summary: str                                # 内容摘要
    prioritized_urls: List[PrioritizedURL]     # 优先级排序的URL
    
    # 元数据
    analysis_time: float = 0.0                  # 分析耗时
    model_used: str = ""                        # 使用的模型
    raw_response: str = ""                      # 原始LLM响应
    
    success: bool = True
    error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'url': self.url,
            'relevance_score': self.relevance_score,
            'key_findings': self.key_findings,
            'extracted_data': self.extracted_data,
            'summary': self.summary,
            'prioritized_urls': [
                {'url': u.url, 'priority': u.priority, 'reason': u.reason}
                for u in self.prioritized_urls
            ],
            'analysis_time': self.analysis_time,
            'model_used': self.model_used
        }


# ============================================================================
# Prompt模板
# ============================================================================

CONTENT_ANALYSIS_PROMPT = """你是一个专业的网页内容分析专家。

## 分析背景
{prompt_background}

## 意图信息
- 类别: {category}
- 关键词: {keywords}
- 搜索重点: {search_focus}

## 待分析内容

**页面标题**: {title}
**页面URL**: {url}

**主要内容**:
{content}

## 页面链接
{links}

## 任务

请分析以上内容，完成以下任务:

1. 评估此页面与目标意图的相关程度 (0-1分)
2. 提取与意图相关的关键信息
3. 从链接中选出值得继续访问的URL，并按1-3优先级排序
   - 优先级1: 高度相关，必须访问
   - 优先级2: 中度相关，建议访问
   - 优先级3: 可能相关，可选访问

## 输出格式

请输出JSON格式:

```json
{{
    "relevance_score": 0.8,
    "key_findings": [
        "发现1: ...",
        "发现2: ..."
    ],
    "extracted_data": {{
        "title": "页面标题",
        "main_content": "核心内容摘要",
        "contact_info": "联系信息(如有)",
        "dates": "相关日期(如有)",
        "data_points": ["数据点1", "数据点2"]
    }},
    "prioritized_urls": [
        {{"url": "完整URL", "priority": 1, "reason": "选择原因"}},
        {{"url": "完整URL", "priority": 2, "reason": "选择原因"}}
    ],
    "summary": "50-100字的内容摘要"
}}
```

注意:
1. 只输出JSON，不要其他内容
2. URL必须是完整的绝对路径
3. 最多选择10个优先URL
4. 摘要使用中文"""


QUICK_RELEVANCE_PROMPT = """/no_think
判断页面相关性。

意图: {intent}
关键词: {keywords}

标题: {title}
摘要: {summary}

输出JSON: {{"score": 0.8, "keywords_found": ["词1"]}}
只输出JSON。"""


# ============================================================================
# 内容分析器类
# ============================================================================

class ContentAnalyzer:
    """
    内容分析器 - 使用LLM分析网页内容
    
    使用方式:
        analyzer = ContentAnalyzer(llm_client)
        result = analyzer.analyze(content, intent_components)
        print(result.summary)
    """
    
    def __init__(self, llm_client: LLMClient):
        """
        初始化内容分析器
        
        Args:
            llm_client: LLM客户端实例
        """
        self.llm_client = llm_client
        logger.info("内容分析器初始化完成")
    
    def analyze(
        self,
        content: ExtractedContent,
        intent_components: IntentComponents,
        base_url: str = None
    ) -> AnalysisResult:
        """
        分析网页内容
        
        使用 qwen3:1.7b 模型进行深度分析
        
        Args:
            content: 提取的网页内容
            intent_components: 意图组件
            base_url: 基础URL (用于链接解析)
            
        Returns:
            AnalysisResult对象
        """
        import time
        start_time = time.time()
        
        url = content.url
        base_url = base_url or url
        
        logger.info(f"分析内容: {url}")
        
        # 准备链接信息
        links_text = self._format_links(content.links, base_url)
        
        # 构建prompt
        prompt = CONTENT_ANALYSIS_PROMPT.format(
            prompt_background=intent_components.prompt_background,
            category=intent_components.category,
            keywords=', '.join(intent_components.keywords),
            search_focus=intent_components.search_focus,
            title=content.title or "无标题",
            url=url,
            content=truncate_text(content.text, 2500),
            links=links_text
        )
        
        # 调用LLM
        response = self.llm_client.analysis_generate(prompt)
        
        analysis_time = time.time() - start_time
        
        if not response.success:
            logger.warning(f"LLM分析失败: {response.error}")
            return self._create_fallback_result(content, intent_components, analysis_time)
        
        # 解析响应
        try:
            result = extract_json_from_text(response.content)
            
            if not result:
                logger.warning("无法解析LLM响应")
                return self._create_fallback_result(content, intent_components, analysis_time)
            
            # 解析URL
            prioritized_urls = self._parse_prioritized_urls(
                result.get('prioritized_urls', []),
                base_url
            )
            
            analysis_result = AnalysisResult(
                url=url,
                relevance_score=float(result.get('relevance_score', 0.5)),
                key_findings=result.get('key_findings', []),
                extracted_data=result.get('extracted_data', {}),
                summary=result.get('summary', ''),
                prioritized_urls=prioritized_urls,
                analysis_time=analysis_time,
                model_used=self.llm_client.config.analysis_model,
                raw_response=response.content,
                success=True
            )
            
            logger.success(
                f"分析完成: {url} | "
                f"相关度: {analysis_result.relevance_score:.2f} | "
                f"发现: {len(analysis_result.key_findings)} | "
                f"推荐URL: {len(prioritized_urls)} | "
                f"耗时: {analysis_time:.2f}s"
            )
            
            return analysis_result
            
        except Exception as e:
            error_msg = get_err_message()
            logger.error(f"解析分析结果失败: {e}")
            logger.debug(error_msg)
            return self._create_fallback_result(content, intent_components, analysis_time)
    
    def quick_relevance_check(
        self,
        title: str,
        summary: str,
        intent_components: IntentComponents
    ) -> Tuple[float, List[str]]:
        """
        快速相关性检查
        
        使用 qwen3:0.6b 快速模型
        
        Args:
            title: 页面标题
            summary: 页面摘要
            intent_components: 意图组件
            
        Returns:
            (相关度分数, 匹配关键词列表)
        """
        prompt = QUICK_RELEVANCE_PROMPT.format(
            intent=intent_components.search_focus,
            keywords=', '.join(intent_components.keywords),
            title=title[:100],
            summary=summary[:200]
        )
        
        response = self.llm_client.fast_generate(prompt)
        
        if not response.success:
            return self._keyword_relevance_check(title, summary, intent_components)
        
        try:
            result = extract_json_from_text(response.content)
            if result:
                return (
                    float(result.get('score', 0.5)),
                    result.get('keywords_found', [])
                )
        except Exception:
            pass
        
        return self._keyword_relevance_check(title, summary, intent_components)
    
    def _format_links(self, links: List[ExtractedLink], base_url: str) -> str:
        """格式化链接列表"""
        if not links:
            return "无链接"
        
        formatted = []
        for i, link in enumerate(links[:20], 1):
            url = link.url
            if not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            
            text = link.text[:50] if link.text else "无文本"
            internal = "内部" if link.is_internal else "外部"
            formatted.append(f"{i}. [{text}]({url}) - {internal}")
        
        return '\n'.join(formatted)
    
    def _parse_prioritized_urls(
        self,
        urls_data: List[Dict],
        base_url: str
    ) -> List[PrioritizedURL]:
        """解析优先级URL"""
        prioritized = []
        seen = set()
        
        for item in urls_data:
            if not isinstance(item, dict):
                continue
            
            url = item.get('url', '')
            if not url:
                continue
            
            # 规范化URL
            if not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            
            # 去重
            if url in seen:
                continue
            seen.add(url)
            
            priority = item.get('priority', 3)
            if isinstance(priority, str):
                priority = int(priority) if priority.isdigit() else 3
            priority = max(1, min(3, priority))  # 确保在1-3范围
            
            prioritized.append(PrioritizedURL(
                url=url,
                priority=priority,
                reason=item.get('reason', ''),
                link_text=item.get('text', '')
            ))
        
        # 按优先级排序
        prioritized.sort()
        
        return prioritized[:10]
    
    def _create_fallback_result(
        self,
        content: ExtractedContent,
        intent_components: IntentComponents,
        analysis_time: float
    ) -> AnalysisResult:
        """创建回退分析结果"""
        # 基于关键词计算相关度
        score, keywords = self._keyword_relevance_check(
            content.title,
            content.text[:500],
            intent_components
        )
        
        # 基于关键词选择URL
        prioritized_urls = self._select_urls_by_keywords(
            content.links,
            intent_components.keywords,
            content.url
        )
        
        return AnalysisResult(
            url=content.url,
            relevance_score=score,
            key_findings=[f"基于关键词匹配: {', '.join(keywords)}"] if keywords else [],
            extracted_data={
                'title': content.title,
                'main_content': content.text[:500]
            },
            summary=truncate_text(content.text, 200),
            prioritized_urls=prioritized_urls,
            analysis_time=analysis_time,
            model_used="fallback",
            success=True
        )
    
    def _keyword_relevance_check(
        self,
        title: str,
        text: str,
        intent_components: IntentComponents
    ) -> Tuple[float, List[str]]:
        """关键词相关性检查"""
        combined = (title + ' ' + text).lower()
        matched = []
        
        for keyword in intent_components.keywords:
            if keyword.lower() in combined:
                matched.append(keyword)
        
        if not intent_components.keywords:
            score = 0.5
        else:
            score = len(matched) / len(intent_components.keywords)
        
        return (score, matched)
    
    def _select_urls_by_keywords(
        self,
        links: List[ExtractedLink],
        keywords: List[str],
        base_url: str
    ) -> List[PrioritizedURL]:
        """基于关键词选择URL"""
        scored_links = []
        
        for link in links:
            if not link.is_internal:
                continue
            
            # 计算链接分数
            link_text = (link.text + ' ' + link.url).lower()
            matches = sum(1 for kw in keywords if kw.lower() in link_text)
            
            if matches > 0:
                priority = 1 if matches >= 2 else (2 if matches == 1 else 3)
                url = link.url
                if not url.startswith(('http://', 'https://')):
                    url = urljoin(base_url, url)
                
                scored_links.append(PrioritizedURL(
                    url=url,
                    priority=priority,
                    reason=f"匹配{matches}个关键词",
                    link_text=link.text
                ))
        
        # 排序并限制数量
        scored_links.sort()
        return scored_links[:10]


# ============================================================================
# 工厂函数
# ============================================================================

def create_content_analyzer(llm_client: LLMClient) -> ContentAnalyzer:
    """
    创建内容分析器实例
    
    Args:
        llm_client: LLM客户端
        
    Returns:
        ContentAnalyzer实例
    """
    return ContentAnalyzer(llm_client)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    from config import LLMConfig, ContentConfig
    from llm_client import create_llm_client
    from content_extractor import ExtractedContent, ExtractedLink
    from intent_analyzer import IntentComponents
    
    print("=" * 60)
    print("内容分析器模块测试")
    print("=" * 60)
    
    # 创建LLM客户端
    llm_config = LLMConfig()
    llm_client = create_llm_client(llm_config)
    
    if not llm_client.check_connection():
        print("无法连接Ollama服务")
        exit(1)
    
    # 创建分析器
    analyzer = create_content_analyzer(llm_client)
    
    # 创建测试数据
    test_content = ExtractedContent(
        url="https://www.stanford.edu/admission",
        title="Stanford Admission - Undergraduate",
        text="""
        Stanford University welcomes applications from students around the world.
        Our admission process is highly selective, considering academic achievement,
        extracurricular activities, and personal qualities.
        
        Key dates for 2024:
        - Application deadline: January 2, 2024
        - Financial aid deadline: February 15, 2024
        - Decision notification: April 1, 2024
        
        For more information, contact the admission office at admission@stanford.edu
        or call (650) 723-2091.
        """,
        links=[
            ExtractedLink(url="/admission/apply", text="Apply Now", is_internal=True),
            ExtractedLink(url="/admission/requirements", text="Requirements", is_internal=True),
            ExtractedLink(url="/financial-aid", text="Financial Aid", is_internal=True),
            ExtractedLink(url="https://external.com", text="External", is_internal=False),
        ],
        emails=["admission@stanford.edu"],
        word_count=80
    )
    
    test_intent = IntentComponents(
        category="admission",
        keywords=["招生", "申请", "录取", "admission", "apply"],
        search_focus="斯坦福大学本科招生信息",
        content_type="招生政策",
        priority_signals=["admission", "apply", "deadline"],
        exclude_patterns=[],
        prompt_background="我们正在收集斯坦福大学的本科招生信息，包括申请要求、截止日期、录取标准等。"
    )
    
    # 测试内容分析
    print("\n--- 内容分析测试 ---")
    result = analyzer.analyze(test_content, test_intent)
    
    print(f"URL: {result.url}")
    print(f"相关度: {result.relevance_score}")
    print(f"关键发现: {result.key_findings}")
    print(f"摘要: {result.summary}")
    print(f"分析耗时: {result.analysis_time:.2f}s")
    
    print("\n推荐URL:")
    for url in result.prioritized_urls:
        print(f"  优先级{url.priority}: {url.url}")
        print(f"    原因: {url.reason}")
    
    # 测试快速相关性检查
    print("\n--- 快速相关性检查测试 ---")
    score, keywords = analyzer.quick_relevance_check(
        test_content.title,
        test_content.text[:200],
        test_intent
    )
    print(f"相关度分数: {score}")
    print(f"匹配关键词: {keywords}")
    
    print("\n" + "=" * 60)
    print("测试完成!")