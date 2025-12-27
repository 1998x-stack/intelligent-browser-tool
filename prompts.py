"""
Prompt模板系统 - 为小模型(0.5b/3b)设计的简洁直接提示词

设计理念:
- 简洁直接：小模型需要清晰明确的指令
- 结构化输出：要求JSON格式便于解析
- 低温度：保证输出稳定性
- 上下文感知：支持用户意图作为前缀

参考: Qwen2.5最佳实践
"""

from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class PromptTemplate:
    """Prompt模板"""
    system: str
    user_template: str
    output_format: str


# ============ 用户意图Prompt前缀 ============

def build_intent_prefix(user_intent: str) -> str:
    """
    构建用户意图前缀
    
    这个前缀会添加到所有Prompt的system消息中，
    让模型理解用户的核心目标
    
    Args:
        user_intent: 用户意图描述
        
    Returns:
        格式化的意图前缀
    """
    if not user_intent:
        return ""
    
    return f"""[用户意图]
{user_intent}

所有分析和提取都应围绕这个意图进行。优先关注与意图相关的内容。

"""


# ============ 0.5b模型 - 页面分类Prompt ============

PAGE_CLASSIFICATION_PROMPT = PromptTemplate(
    system="""你是网页分类助手。根据标题和预览文本，判断页面类型。

分类规则:
- admission: 招生、申请、入学相关
- academic: 学术项目、课程、专业
- research: 研究、论文、实验室
- faculty: 教师、人员、团队
- international: 国际学生、全球项目
- financial: 学费、奖学金、资助
- news: 新闻、公告、博客
- about: 关于、历史、介绍
- navigation: 导航、索引、目录
- other: 其他类型

只输出JSON，不要解释。""",

    user_template="""标题: {title}
预览: {preview}

判断页面类型。""",

    output_format="""{
  "category": "分类名",
  "confidence": 0.85,
  "should_extract": true,
  "reason": "简短理由"
}"""
)


# ============ 0.5b模型 - 链接优先级Prompt ============

LINK_PRIORITY_PROMPT = PromptTemplate(
    system="""你是URL分析助手。根据用户意图，判断链接是否值得访问。

评分规则:
- 3分: 高度相关，必须访问
- 2分: 可能相关，建议访问  
- 1分: 略有关联
- 0分: 无关或应跳过

只输出JSON，不要解释。""",

    user_template="""意图: {intent}

评估这些链接:
{links}

返回每个链接的评分。""",

    output_format="""{
  "scores": [
    {"url": "链接1", "score": 3, "reason": "原因"},
    {"url": "链接2", "score": 1, "reason": "原因"}
  ]
}"""
)


# ============ 0.5b模型 - 快速判断Prompt ============

QUICK_RELEVANCE_PROMPT = PromptTemplate(
    system="""判断文本是否与意图相关。只回答yes或no。""",
    
    user_template="""意图: {intent}
文本: {text}

相关吗?""",
    
    output_format="""yes 或 no"""
)


# ============ 3b/4b模型 - 内容分析Prompt ============

CONTENT_ANALYSIS_PROMPT = PromptTemplate(
    system="""你是内容分析助手。从网页内容中提取结构化信息。

提取规则:
1. summary: 2-3句话概括核心内容
2. key_points: 3-5个关键要点
3. entities: 重要实体(人名、机构、项目等)
4. facts: 具体事实(数字、日期、要求等)
5. keywords: 5-10个关键词

关注与用户意图相关的信息。只输出JSON。""",

    user_template="""页面标题: {title}
页面URL: {url}

内容:
{content}

提取结构化信息。""",

    output_format="""{
  "summary": "内容概要",
  "key_points": ["要点1", "要点2", "要点3"],
  "entities": {
    "organizations": ["机构名"],
    "programs": ["项目名"],
    "people": ["人名"],
    "locations": ["地点"]
  },
  "facts": [
    {"type": "deadline", "value": "日期", "context": "上下文"},
    {"type": "requirement", "value": "要求内容", "context": "上下文"}
  ],
  "keywords": ["关键词1", "关键词2"],
  "relevance_score": 0.85
}"""
)


# ============ 3b/4b模型 - URL推荐Prompt ============

URL_RECOMMENDATION_PROMPT = PromptTemplate(
    system="""你是URL推荐助手。根据当前页面和用户意图，推荐下一步要访问的链接。

选择规则:
1. 优先选择与用户意图高度相关的链接
2. 避免重复类型的页面
3. 深度信息页面优于概览页面
4. 最多推荐5个链接

只输出JSON。""",

    user_template="""当前页面: {current_url}
页面摘要: {summary}

可用链接:
{links}

推荐下一步访问的链接。""",

    output_format="""{
  "recommended": [
    {
      "url": "链接URL",
      "priority": 1,
      "reason": "推荐理由"
    }
  ],
  "skip_reasons": {
    "跳过的URL": "跳过理由"
  }
}"""
)


# ============ 3b/4b模型 - 信息整合Prompt ============

INFO_SYNTHESIS_PROMPT = PromptTemplate(
    system="""你是信息整合助手。将多个页面的信息整合成完整报告。

整合规则:
1. 去除重复信息
2. 按主题分类组织
3. 标注信息来源
4. 突出关键发现

只输出JSON。""",

    user_template="""用户意图: {intent}

收集到的信息:
{collected_info}

整合成结构化报告。""",

    output_format="""{
  "topic_summary": "主题概述",
  "sections": [
    {
      "title": "章节标题",
      "content": "章节内容",
      "sources": ["来源URL"]
    }
  ],
  "key_findings": ["关键发现1", "关键发现2"],
  "action_items": ["建议行动1"],
  "data_quality": {
    "completeness": 0.8,
    "reliability": 0.9,
    "gaps": ["信息缺口"]
  }
}"""
)


# ============ 3b/4b模型 - 文件命名Prompt ============

FILE_NAMING_PROMPT = PromptTemplate(
    system="""为网页内容生成简短的文件名。

规则:
1. 使用英文或拼音
2. 下划线分隔
3. 最多30字符
4. 反映页面核心内容

只输出文件名，不要扩展名。""",

    user_template="""标题: {title}
类型: {category}
关键词: {keywords}

生成文件名。""",

    output_format="""stanford_admission_2024"""
)


# ============ Prompt构建器 ============

class PromptBuilder:
    """
    Prompt构建器 - 组合意图和模板
    """
    
    def __init__(self, user_intent: str = ""):
        """
        初始化Prompt构建器
        
        Args:
            user_intent: 用户意图
        """
        self.intent_prefix = build_intent_prefix(user_intent)
        self.user_intent = user_intent
    
    def build_classification_prompt(
        self, 
        title: str, 
        preview: str
    ) -> Dict[str, str]:
        """构建页面分类Prompt"""
        template = PAGE_CLASSIFICATION_PROMPT
        
        return {
            'system': self.intent_prefix + template.system,
            'user': template.user_template.format(
                title=title[:200],
                preview=preview[:500]
            )
        }
    
    def build_link_priority_prompt(
        self, 
        links: List[Dict]
    ) -> Dict[str, str]:
        """构建链接优先级Prompt"""
        template = LINK_PRIORITY_PROMPT
        
        # 格式化链接列表
        links_text = "\n".join([
            f"- {l['url']}: {l.get('text', '')[:50]}"
            for l in links[:20]  # 限制数量
        ])
        
        return {
            'system': self.intent_prefix + template.system,
            'user': template.user_template.format(
                intent=self.user_intent,
                links=links_text
            )
        }
    
    def build_content_analysis_prompt(
        self, 
        title: str, 
        url: str, 
        content: str
    ) -> Dict[str, str]:
        """构建内容分析Prompt"""
        template = CONTENT_ANALYSIS_PROMPT
        
        # 限制内容长度
        content = content[:5000] if len(content) > 5000 else content
        
        return {
            'system': self.intent_prefix + template.system,
            'user': template.user_template.format(
                title=title,
                url=url,
                content=content
            )
        }
    
    def build_url_recommendation_prompt(
        self, 
        current_url: str, 
        summary: str, 
        links: List[Dict]
    ) -> Dict[str, str]:
        """构建URL推荐Prompt"""
        template = URL_RECOMMENDATION_PROMPT
        
        # 格式化链接
        links_text = "\n".join([
            f"- [{l.get('type', 'general')}] {l['url']}: {l.get('text', '')[:50]}"
            for l in links[:30]
        ])
        
        return {
            'system': self.intent_prefix + template.system,
            'user': template.user_template.format(
                current_url=current_url,
                summary=summary[:300],
                links=links_text
            )
        }
    
    def build_synthesis_prompt(
        self, 
        collected_info: List[Dict]
    ) -> Dict[str, str]:
        """构建信息整合Prompt"""
        template = INFO_SYNTHESIS_PROMPT
        
        # 格式化收集的信息
        info_text = "\n\n".join([
            f"[{info.get('url', 'unknown')}]\n{info.get('summary', '')}"
            for info in collected_info[:10]
        ])
        
        return {
            'system': template.system,
            'user': template.user_template.format(
                intent=self.user_intent,
                collected_info=info_text
            )
        }
    
    def build_file_naming_prompt(
        self, 
        title: str, 
        category: str, 
        keywords: List[str]
    ) -> Dict[str, str]:
        """构建文件命名Prompt"""
        template = FILE_NAMING_PROMPT
        
        return {
            'system': template.system,
            'user': template.user_template.format(
                title=title,
                category=category,
                keywords=', '.join(keywords[:5])
            )
        }
    
    def build_quick_relevance_prompt(
        self, 
        text: str
    ) -> Dict[str, str]:
        """构建快速相关性判断Prompt"""
        template = QUICK_RELEVANCE_PROMPT
        
        return {
            'system': template.system,
            'user': template.user_template.format(
                intent=self.user_intent,
                text=text[:500]
            )
        }


def load_intent_from_file(filepath: str) -> str:
    """
    从文件加载用户意图
    
    Args:
        filepath: prompt.txt文件路径
        
    Returns:
        用户意图文本
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        return content
    except Exception as e:
        return ""


if __name__ == "__main__":
    # 测试Prompt构建
    intent = "了解斯坦福大学针对国际学生的招生政策、申请要求和奖学金信息"
    builder = PromptBuilder(intent)
    
    # 测试分类Prompt
    prompt = builder.build_classification_prompt(
        title="Stanford Admissions - International Students",
        preview="Learn about applying to Stanford as an international student..."
    )
    print("=== 分类Prompt ===")
    print(f"System: {prompt['system'][:200]}...")
    print(f"User: {prompt['user']}")
    
    # 测试内容分析Prompt
    prompt = builder.build_content_analysis_prompt(
        title="Admission Requirements",
        url="https://admission.stanford.edu/",
        content="Stanford welcomes applications from students around the world..."
    )
    print("\n=== 内容分析Prompt ===")
    print(f"System: {prompt['system'][:200]}...")