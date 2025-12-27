"""
意图分析器模块 - 使用LLM将用户意图转化为AI prompt背景

设计理念 (CleanRL哲学):
- 单文件自包含: 意图分析逻辑集中管理
- 透明的处理流程: Prompt模板清晰可见
- 最小化抽象: 直接的LLM调用
- 便于调试: 详细的分析日志

功能:
- 将用户意图转化为结构化的prompt组件
- 生成意图类别和关键词
- 支持多种意图类型
"""

import re
import json
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

from loguru import logger

from config import IntentCategory, get_err_message
from llm_client import LLMClient, LLMResponse
from utils import extract_json_from_text


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class IntentComponents:
    """意图组件 - LLM生成的prompt背景"""
    category: str                           # 意图类别
    keywords: List[str]                     # 关键词列表
    search_focus: str                       # 搜索重点
    content_type: str                       # 期望内容类型
    priority_signals: List[str]             # 优先级信号
    exclude_patterns: List[str]             # 排除模式
    prompt_background: str                  # 完整的prompt背景
    raw_response: str = ""                  # 原始LLM响应
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'category': self.category,
            'keywords': self.keywords,
            'search_focus': self.search_focus,
            'content_type': self.content_type,
            'priority_signals': self.priority_signals,
            'exclude_patterns': self.exclude_patterns,
            'prompt_background': self.prompt_background
        }


@dataclass
class MatchedIntent:
    """匹配的意图 - 快速模型输出"""
    intent: str                     # 识别的意图
    confidence: float               # 置信度 (0-1)
    matched_keywords: List[str]     # 匹配的关键词
    raw_response: str = ""          # 原始响应


# ============================================================================
# Prompt模板
# ============================================================================

INTENT_TO_COMPONENTS_PROMPT = """你是一个意图分析专家。根据用户的意图，生成用于网页内容分析的prompt组件。

用户意图: {intent}
目标网站: {url}

请分析意图并生成以下JSON格式的组件:

```json
{{
    "category": "意图类别，从以下选择: content/data/email/policy/contact/admission/research/news/event/general",
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "search_focus": "搜索的主要焦点描述",
    "content_type": "期望的内容类型: 文章/数据/联系方式/政策文档/新闻/活动",
    "priority_signals": ["URL或内容中的优先级信号词"],
    "exclude_patterns": ["应该排除的URL或内容模式"],
    "prompt_background": "为内容分析生成的详细prompt背景，描述我们在寻找什么类型的信息"
}}
```

要求:
1. category必须从给定选项中选择
2. keywords应该是3-5个最相关的关键词
3. prompt_background应该详细描述信息需求
4. 使用中文回复

只输出JSON，不要其他内容。"""


QUICK_INTENT_MATCH_PROMPT = """分析以下网页内容是否匹配目标意图。

目标意图: {intent}
意图类别: {category}
关键词: {keywords}

网页标题: {title}
网页摘要: {summary}

判断此页面是否与目标意图相关，输出JSON:

```json
{{
    "intent": "识别到的具体意图",
    "confidence": 0.8,
    "matched_keywords": ["匹配到的关键词"]
}}
```

置信度0-1之间，>0.7表示高度相关。只输出JSON。"""


# ============================================================================
# 意图分析器类
# ============================================================================

class IntentAnalyzer:
    """
    意图分析器 - 使用LLM分析和转换用户意图
    
    使用方式:
        analyzer = IntentAnalyzer(llm_client)
        components = analyzer.analyze_intent("招生信息", "https://stanford.edu")
        print(components.prompt_background)
    """
    
    def __init__(self, llm_client: LLMClient):
        """
        初始化意图分析器
        
        Args:
            llm_client: LLM客户端实例
        """
        self.llm_client = llm_client
        
        # 意图类别映射 (用于快速分类)
        self.category_keywords = {
            IntentCategory.ADMISSION: ['招生', '申请', '录取', 'admission', 'apply', 'enrollment'],
            IntentCategory.RESEARCH: ['研究', '科研', '论文', 'research', 'paper', 'lab'],
            IntentCategory.CONTACT: ['联系', '电话', '邮箱', 'contact', 'email', 'phone'],
            IntentCategory.EMAIL: ['邮件', '邮箱', 'email', 'mail'],
            IntentCategory.POLICY: ['政策', '规定', '要求', 'policy', 'requirement', 'rule'],
            IntentCategory.NEWS: ['新闻', '动态', '最新', 'news', 'update', 'announcement'],
            IntentCategory.EVENT: ['活动', '讲座', '会议', 'event', 'seminar', 'conference'],
            IntentCategory.DATA: ['数据', '统计', '排名', 'data', 'statistics', 'ranking'],
            IntentCategory.CONTENT: ['内容', '文章', '介绍', 'content', 'article', 'about'],
        }
        
        logger.info("意图分析器初始化完成")
    
    def analyze_intent(self, intent: str, url: str) -> IntentComponents:
        """
        分析用户意图，生成prompt组件
        
        使用 qwen3:1.7b 模型进行深度分析
        
        Args:
            intent: 用户意图描述
            url: 目标网站URL
            
        Returns:
            IntentComponents对象
        """
        logger.info(f"分析意图: {intent} | URL: {url}")
        
        # 构建prompt
        prompt = INTENT_TO_COMPONENTS_PROMPT.format(
            intent=intent,
            url=url
        )
        
        # 调用LLM (使用1.7b模型)
        response = self.llm_client.intent_generate(prompt)
        
        if not response.success:
            logger.warning(f"LLM意图分析失败: {response.error}")
            # 返回基于规则的默认组件
            return self._create_default_components(intent, url)
        
        # 解析响应
        try:
            result = extract_json_from_text(response.content)
            
            if not result:
                logger.warning("无法解析LLM响应为JSON，使用默认值")
                return self._create_default_components(intent, url)
            
            components = IntentComponents(
                category=result.get('category', IntentCategory.GENERAL),
                keywords=result.get('keywords', [intent]),
                search_focus=result.get('search_focus', intent),
                content_type=result.get('content_type', '通用'),
                priority_signals=result.get('priority_signals', []),
                exclude_patterns=result.get('exclude_patterns', []),
                prompt_background=result.get('prompt_background', f'寻找关于{intent}的信息'),
                raw_response=response.content
            )
            
            # 验证类别
            if components.category not in IntentCategory.all_categories():
                components.category = self._guess_category(intent)
            
            logger.success(f"意图分析完成 | 类别: {components.category} | 关键词: {components.keywords}")
            
            return components
            
        except Exception as e:
            logger.error(f"解析意图组件失败: {e}")
            return self._create_default_components(intent, url)
    
    def quick_match_intent(
        self,
        title: str,
        summary: str,
        intent_components: IntentComponents
    ) -> MatchedIntent:
        """
        快速匹配意图 - 判断页面是否与意图相关
        
        使用 qwen3:0.6b 快速模型
        
        Args:
            title: 页面标题
            summary: 页面摘要
            intent_components: 意图组件
            
        Returns:
            MatchedIntent对象
        """
        # 构建prompt
        prompt = QUICK_INTENT_MATCH_PROMPT.format(
            intent=intent_components.search_focus,
            category=intent_components.category,
            keywords=', '.join(intent_components.keywords),
            title=title[:100],
            summary=summary[:300]
        )
        
        # 调用快速模型
        response = self.llm_client.fast_generate(prompt)
        
        if not response.success:
            # 回退到关键词匹配
            return self._keyword_match(title, summary, intent_components)
        
        try:
            result = extract_json_from_text(response.content)
            
            if not result:
                return self._keyword_match(title, summary, intent_components)
            
            return MatchedIntent(
                intent=result.get('intent', ''),
                confidence=float(result.get('confidence', 0.5)),
                matched_keywords=result.get('matched_keywords', []),
                raw_response=response.content
            )
            
        except Exception as e:
            logger.debug(f"解析匹配结果失败: {e}")
            return self._keyword_match(title, summary, intent_components)
    
    def _guess_category(self, intent: str) -> str:
        """
        基于关键词猜测意图类别
        
        Args:
            intent: 意图描述
            
        Returns:
            类别字符串
        """
        intent_lower = intent.lower()
        
        max_matches = 0
        best_category = IntentCategory.GENERAL
        
        for category, keywords in self.category_keywords.items():
            matches = sum(1 for kw in keywords if kw in intent_lower)
            if matches > max_matches:
                max_matches = matches
                best_category = category
        
        return best_category
    
    def _create_default_components(self, intent: str, url: str) -> IntentComponents:
        """
        创建默认的意图组件
        
        Args:
            intent: 意图描述
            url: URL
            
        Returns:
            IntentComponents对象
        """
        category = self._guess_category(intent)
        
        # 提取关键词 (简单分词)
        keywords = [w for w in re.split(r'\s+|,|，', intent) if len(w) > 1]
        if not keywords:
            keywords = [intent]
        
        return IntentComponents(
            category=category,
            keywords=keywords[:5],
            search_focus=intent,
            content_type='通用内容',
            priority_signals=keywords[:3],
            exclude_patterns=[],
            prompt_background=f"我们正在寻找关于'{intent}'的信息。请关注与此主题相关的所有内容。"
        )
    
    def _keyword_match(
        self,
        title: str,
        summary: str,
        intent_components: IntentComponents
    ) -> MatchedIntent:
        """
        关键词匹配 (回退方法)
        
        Args:
            title: 页面标题
            summary: 页面摘要
            intent_components: 意图组件
            
        Returns:
            MatchedIntent对象
        """
        text = (title + ' ' + summary).lower()
        matched = []
        
        for keyword in intent_components.keywords:
            if keyword.lower() in text:
                matched.append(keyword)
        
        # 计算置信度
        if not intent_components.keywords:
            confidence = 0.5
        else:
            confidence = len(matched) / len(intent_components.keywords)
        
        return MatchedIntent(
            intent=intent_components.search_focus,
            confidence=confidence,
            matched_keywords=matched
        )
    
    def generate_analysis_prompt(
        self,
        content: str,
        intent_components: IntentComponents
    ) -> str:
        """
        生成内容分析prompt
        
        Args:
            content: 网页内容
            intent_components: 意图组件
            
        Returns:
            完整的分析prompt
        """
        prompt = f"""你是一个专业的网页内容分析专家。

背景: {intent_components.prompt_background}

意图类别: {intent_components.category}
关键词: {', '.join(intent_components.keywords)}
内容类型: {intent_components.content_type}

请分析以下网页内容，提取与上述意图相关的核心信息:

---
{content[:3000]}
---

请输出JSON格式的分析结果:

```json
{{
    "relevance_score": 0.8,
    "key_findings": ["关键发现1", "关键发现2"],
    "extracted_data": {{
        "标题": "...",
        "主要内容": "...",
        "联系信息": "...",
        "日期": "..."
    }},
    "related_urls": [
        {{"url": "...", "priority": 1, "reason": "..."}}
    ],
    "summary": "简要总结"
}}
```

只输出JSON，不要其他内容。"""
        
        return prompt


# ============================================================================
# 工厂函数
# ============================================================================

def create_intent_analyzer(llm_client: LLMClient) -> IntentAnalyzer:
    """
    创建意图分析器实例
    
    Args:
        llm_client: LLM客户端
        
    Returns:
        IntentAnalyzer实例
    """
    return IntentAnalyzer(llm_client)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    from config import LLMConfig
    from llm_client import create_llm_client
    
    print("=" * 60)
    print("意图分析器模块测试")
    print("=" * 60)
    
    # 创建LLM客户端
    llm_config = LLMConfig()
    llm_client = create_llm_client(llm_config)
    
    # 检查连接
    if not llm_client.check_connection():
        print("无法连接Ollama服务")
        exit(1)
    
    # 创建分析器
    analyzer = create_intent_analyzer(llm_client)
    
    # 测试意图分析
    print("\n--- 意图分析测试 ---")
    test_intent = "招生信息"
    test_url = "https://www.stanford.edu"
    
    components = analyzer.analyze_intent(test_intent, test_url)
    
    print(f"类别: {components.category}")
    print(f"关键词: {components.keywords}")
    print(f"搜索焦点: {components.search_focus}")
    print(f"内容类型: {components.content_type}")
    print(f"优先级信号: {components.priority_signals}")
    print(f"排除模式: {components.exclude_patterns}")
    print(f"Prompt背景: {components.prompt_background}")
    
    # 测试快速匹配
    print("\n--- 快速匹配测试 ---")
    test_title = "Stanford Admission Requirements 2024"
    test_summary = "Learn about undergraduate admission requirements, deadlines, and how to apply to Stanford University."
    
    match_result = analyzer.quick_match_intent(test_title, test_summary, components)
    
    print(f"识别意图: {match_result.intent}")
    print(f"置信度: {match_result.confidence}")
    print(f"匹配关键词: {match_result.matched_keywords}")
    
    # 测试分析prompt生成
    print("\n--- 分析Prompt生成测试 ---")
    analysis_prompt = analyzer.generate_analysis_prompt(
        "Stanford undergraduate admission process...",
        components
    )
    print(f"Prompt长度: {len(analysis_prompt)} 字符")
    print(f"Prompt预览:\n{analysis_prompt[:500]}...")
    
    print("\n" + "=" * 60)
    print("测试完成!")
