"""
报告生成器 - 生成多层次的Markdown报告

设计理念:
- 分层报告: 总览 -> 分类 -> 详细
- Markdown格式: 便于阅读和转换
- 模板驱动: 灵活的报告格式
- 自动整理: 按类别组织内容

输出结构:
04_reports/
├── summary.md           # 总览报告
├── categories.md        # 分类索引
├── admission/           # 招生相关
│   ├── overview.md
│   └── details/
├── academic/            # 学术相关
├── research/            # 研究相关
└── ...
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import json

from loguru import logger

from config import Config
from data_manager import DataManager


class ReportGenerator:
    """
    报告生成器 - 生成全方位的Markdown报告
    
    功能:
    1. 总览报告 - 任务概况和关键发现
    2. 分类报告 - 按内容类型组织
    3. 详细报告 - 单页面详细分析
    4. 索引报告 - 便于导航的目录
    
    使用示例:
        generator = ReportGenerator(config, data_manager)
        generator.generate_all_reports()
    """
    
    def __init__(self, config: Config, data_manager: DataManager):
        """
        初始化报告生成器
        
        Args:
            config: 配置对象
            data_manager: 数据管理器
        """
        self.config = config
        self.data_manager = data_manager
        self.reports_dir = Path(config.storage.base_dir) / config.storage.reports_dir
        
        logger.info("报告生成器初始化完成")
    
    def generate_all_reports(self) -> Dict[str, str]:
        """
        生成所有报告
        
        Returns:
            生成的报告路径字典
        """
        reports = {}
        
        # 1. 生成总览报告
        summary_path = self.generate_summary_report()
        reports['summary'] = summary_path
        
        # 2. 生成分类索引
        categories_path = self.generate_categories_index()
        reports['categories'] = categories_path
        
        # 3. 生成各分类报告
        stats = self.data_manager.get_stats()
        for category in stats.get('by_category', {}).keys():
            cat_path = self.generate_category_report(category)
            reports[f'category_{category}'] = cat_path
        
        # 4. 生成数据导出
        data_path = self.generate_data_export()
        reports['data'] = data_path
        
        logger.success(f"生成了 {len(reports)} 个报告")
        return reports
    
    def generate_summary_report(self) -> str:
        """
        生成总览报告
        
        包含:
        - 任务信息
        - 爬取统计
        - 关键发现
        - 建议行动
        """
        stats = self.data_manager.get_stats()
        all_analyzed = self.data_manager.get_all_analyzed()
        
        # 收集关键发现
        key_findings = self._collect_key_findings(all_analyzed)
        
        # 构建报告内容
        content = f"""# 📊 网页分析报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 📋 任务概况

| 项目 | 内容 |
|------|------|
| **任务名称** | {self.config.task_name} |
| **起始URL** | {self.config.start_url} |
| **用户意图** | {self.config.user_intent} |

## 📈 爬取统计

| 指标 | 数量 |
|------|------|
| 原始页面 | {stats['total_raw']} |
| 已提取 | {stats['total_extracted']} |
| 已分析 | {stats['total_analyzed']} |

### 按类别分布

"""
        
        # 类别分布
        for cat, count in stats.get('by_category', {}).items():
            content += f"- **{cat}**: {count} 页\n"
        
        # 关键发现
        content += f"""
## 🔍 关键发现

"""
        for i, finding in enumerate(key_findings[:10], 1):
            content += f"{i}. {finding}\n"
        
        # 高相关页面
        content += """
## ⭐ 高相关页面

以下页面与您的意图最为相关:

"""
        # 按相关性排序
        relevant_pages = sorted(
            all_analyzed, 
            key=lambda x: x.get('relevance_score', 0), 
            reverse=True
        )[:10]
        
        for page in relevant_pages:
            score = page.get('relevance_score', 0)
            title = page.get('title', 'Untitled')[:50]
            url = page.get('url', '')
            summary = page.get('summary', '')[:100]
            
            content += f"""### [{title}]({url})
- 相关性评分: {score:.2f}
- 摘要: {summary}...

"""
        
        # 建议行动
        content += """
## 💡 建议行动

根据分析结果，建议您:

1. 查看高相关性页面获取详细信息
2. 关注 admission 和 international 类别的页面
3. 留意具体的申请截止日期和要求

---

*报告由 Intelligent Browser Tool 自动生成*
"""
        
        # 保存报告
        filepath = self.data_manager.save_report(
            name='summary',
            content=content,
            format='md'
        )
        
        return filepath
    
    def generate_categories_index(self) -> str:
        """生成分类索引"""
        stats = self.data_manager.get_stats()
        
        content = f"""# 📁 分类索引

> 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 目录

"""
        
        for category, count in stats.get('by_category', {}).items():
            content += f"- [{category}](./{category}/overview.md) ({count} 页)\n"
        
        content += """
## 分类说明

| 分类 | 描述 |
|------|------|
| admission | 招生、申请相关 |
| academic | 学术项目、课程 |
| research | 研究、实验室 |
| faculty | 教师、团队 |
| international | 国际学生项目 |
| financial | 学费、奖学金 |
| news | 新闻、公告 |
| about | 学校介绍 |
| general | 其他内容 |

---

返回 [总览报告](./summary.md)
"""
        
        filepath = self.data_manager.save_report(
            name='categories',
            content=content,
            format='md'
        )
        
        return filepath
    
    def generate_category_report(self, category: str) -> str:
        """
        生成分类报告
        
        Args:
            category: 分类名称
            
        Returns:
            报告路径
        """
        pages = self.data_manager.get_by_category(category)
        
        if not pages:
            return ""
        
        content = f"""# 📂 {category.upper()} 分类报告

> 共 {len(pages)} 个页面

## 页面列表

"""
        
        for page in pages:
            title = page.get('title', 'Untitled')
            url = page.get('url', '')
            summary = page.get('summary', 'No summary available')
            # 确保summary是字符串
            if not isinstance(summary, str):
                summary = str(summary) if summary else 'No summary available'
            
            content += f"""### [{title}]({url})

{summary[:200]}{"..." if len(summary) > 200 else ""}

**关键点:**
"""
            key_points = page.get('key_points', [])
            if isinstance(key_points, list):
                for point in key_points[:5]:
                    if isinstance(point, str):
                        content += f"- {point}\n"
                    elif isinstance(point, dict):
                        content += f"- {point.get('text', str(point))}\n"
                    else:
                        content += f"- {str(point)}\n"
            
            content += "\n---\n\n"
        
        # 保存到分类目录
        filepath = self.data_manager.save_report(
            name='overview',
            content=content,
            category=category,
            format='md'
        )
        
        # 同时生成各页面的详细报告
        for page in pages:
            self._generate_page_detail(page, category)
        
        return filepath
    
    def _generate_page_detail(self, page: Dict, category: str):
        """生成单页面详细报告"""
        filename = page.get('_meta', {}).get('filename', 'unknown')
        
        content = f"""# {page.get('title', 'Untitled')}

> URL: {page.get('url', '')}  
> 分析时间: {page.get('_meta', {}).get('analyzed_at', '')}

## 摘要

{page.get('summary', 'No summary available')}

## 关键点

"""
        
        key_points = page.get('key_points', [])
        if isinstance(key_points, list):
            for point in key_points:
                if isinstance(point, str):
                    content += f"- {point}\n"
                elif isinstance(point, dict):
                    content += f"- {point.get('text', str(point))}\n"
        
        content += """
## 实体信息

"""
        
        entities = page.get('entities', {})
        # 处理entities可能是字典或列表的情况
        if isinstance(entities, dict):
            for entity_type, values in entities.items():
                if values:
                    content += f"### {entity_type}\n"
                    if isinstance(values, list):
                        for val in values:
                            if isinstance(val, str):
                                content += f"- {val}\n"
                            elif isinstance(val, dict):
                                content += f"- {val.get('name', str(val))}\n"
                    elif isinstance(values, str):
                        content += f"- {values}\n"
                    content += "\n"
        elif isinstance(entities, list):
            # entities是列表的情况
            for entity in entities:
                if isinstance(entity, str):
                    content += f"- {entity}\n"
                elif isinstance(entity, dict):
                    entity_type = entity.get('type', 'entity')
                    entity_value = entity.get('value', entity.get('name', str(entity)))
                    content += f"- **{entity_type}**: {entity_value}\n"
        
        content += """
## 关键事实

"""
        
        facts = page.get('facts', [])
        if isinstance(facts, list):
            for fact in facts:
                if isinstance(fact, dict):
                    content += f"- **{fact.get('type', 'info')}**: {fact.get('value', '')}\n"
                elif isinstance(fact, str):
                    content += f"- {fact}\n"
        
        content += """
## 关键词

"""
        keywords = page.get('keywords', [])
        if isinstance(keywords, list):
            keyword_strs = [kw if isinstance(kw, str) else str(kw) for kw in keywords]
            content += ", ".join(keyword_strs)
        elif isinstance(keywords, str):
            content += keywords
        
        content += f"""

---

返回 [分类概览](./overview.md) | [总览报告](../summary.md)
"""
        
        # 保存到分类目录下的details子目录
        details_dir = self.reports_dir / category / 'details'
        details_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = details_dir / f"{filename}.md"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def generate_data_export(self) -> str:
        """生成数据导出"""
        summary = self.data_manager.export_summary()
        
        filepath = self.reports_dir / 'data_export.json'
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    def _collect_key_findings(self, all_analyzed: List[Dict]) -> List[str]:
        """收集关键发现"""
        findings = []
        
        # 收集高频关键词
        keyword_counts = {}
        for page in all_analyzed:
            keywords = page.get('keywords', [])
            if isinstance(keywords, list):
                for kw in keywords:
                    if isinstance(kw, str):
                        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        
        top_keywords = sorted(
            keyword_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        if top_keywords:
            findings.append(
                f"最常见的主题包括: {', '.join([kw for kw, _ in top_keywords])}"
            )
        
        # 收集重要事实
        for page in all_analyzed:
            facts = page.get('facts', [])
            if isinstance(facts, list):
                for fact in facts:
                    # 处理fact可能是字符串或字典的情况
                    if isinstance(fact, dict):
                        fact_type = fact.get('type', '')
                        if fact_type in ['deadline', 'requirement', 'date']:
                            findings.append(
                                f"{fact_type}: {fact.get('value', '')} "
                                f"(来源: {page.get('title', 'Unknown')[:30]})"
                            )
                    elif isinstance(fact, str) and fact.strip():
                        # 如果fact是字符串，直接添加
                        findings.append(
                            f"事实: {fact[:80]} "
                            f"(来源: {page.get('title', 'Unknown')[:30]})"
                        )
        
        # 收集高相关页面摘要
        for page in all_analyzed:
            relevance = page.get('relevance_score', 0)
            # 确保relevance是数字
            if isinstance(relevance, (int, float)) and relevance > 0.7:
                summary = page.get('summary', '')
                if summary and isinstance(summary, str):
                    findings.append(summary[:100] + "...")
        
        return findings[:15]
    
    def generate_intent_report(
        self, 
        synthesized_info: Dict
    ) -> str:
        """
        生成针对用户意图的专题报告
        
        Args:
            synthesized_info: AI整合的信息
            
        Returns:
            报告路径
        """
        # 确保synthesized_info是字典
        if not isinstance(synthesized_info, dict):
            synthesized_info = {}
        
        topic_summary = synthesized_info.get('topic_summary', '暂无概述')
        if not isinstance(topic_summary, str):
            topic_summary = str(topic_summary) if topic_summary else '暂无概述'
        
        content = f"""# 🎯 意图分析报告

> 用户意图: {self.config.user_intent}  
> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 概述

{topic_summary}

## 详细内容

"""
        
        sections = synthesized_info.get('sections', [])
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict):
                    title = section.get('title', 'Section')
                    section_content = section.get('content', '')
                    sources = section.get('sources', [])
                    
                    # 确保content是字符串
                    if not isinstance(section_content, str):
                        section_content = str(section_content) if section_content else ''
                    
                    # 确保sources是列表
                    if isinstance(sources, list):
                        sources_str = ', '.join(str(s) for s in sources)
                    elif isinstance(sources, str):
                        sources_str = sources
                    else:
                        sources_str = str(sources) if sources else ''
                    
                    content += f"""### {title}

{section_content}

*来源: {sources_str}*

"""
                elif isinstance(section, str):
                    content += f"{section}\n\n"
        
        content += """## 关键发现

"""
        
        key_findings = synthesized_info.get('key_findings', [])
        if isinstance(key_findings, list):
            for finding in key_findings:
                if isinstance(finding, str):
                    content += f"- {finding}\n"
                elif isinstance(finding, dict):
                    content += f"- {finding.get('text', str(finding))}\n"
                else:
                    content += f"- {str(finding)}\n"
        elif isinstance(key_findings, str):
            content += f"- {key_findings}\n"
        
        content += """
## 建议行动

"""
        
        action_items = synthesized_info.get('action_items', [])
        if isinstance(action_items, list):
            for action in action_items:
                if isinstance(action, str):
                    content += f"- {action}\n"
                elif isinstance(action, dict):
                    content += f"- {action.get('text', str(action))}\n"
                else:
                    content += f"- {str(action)}\n"
        elif isinstance(action_items, str):
            content += f"- {action_items}\n"
        
        # 数据质量评估
        quality = synthesized_info.get('data_quality', {})
        if not isinstance(quality, dict):
            quality = {}
        
        completeness = quality.get('completeness', 0)
        reliability = quality.get('reliability', 0)
        
        # 确保是数字
        try:
            completeness = float(completeness) if completeness else 0
            reliability = float(reliability) if reliability else 0
        except (TypeError, ValueError):
            completeness = 0
            reliability = 0
        
        content += f"""
## 数据质量评估

| 指标 | 评分 |
|------|------|
| 完整性 | {completeness:.0%} |
| 可靠性 | {reliability:.0%} |

### 信息缺口

"""
        
        gaps = quality.get('gaps', [])
        if isinstance(gaps, list):
            for gap in gaps:
                if isinstance(gap, str):
                    content += f"- {gap}\n"
                else:
                    content += f"- {str(gap)}\n"
        elif isinstance(gaps, str):
            content += f"- {gaps}\n"
        
        content += """
---

*本报告由 AI 自动生成，请结合实际情况使用*
"""
        
        filepath = self.data_manager.save_report(
            name='intent_analysis',
            content=content,
            format='md'
        )
        
        return filepath

        for gap in quality.get('gaps', []):
            content += f"- {gap}\n"
        
        content += """
---

*本报告由 AI 自动生成，请结合实际情况使用*
"""
        
        filepath = self.data_manager.save_report(
            name='intent_analysis',
            content=content,
            format='md'
        )
        
        return filepath


class ReportTemplates:
    """报告模板集合"""
    
    @staticmethod
    def page_card(page: Dict) -> str:
        """页面卡片模板"""
        return f"""<div class="page-card">
<h3><a href="{page.get('url', '')}">{page.get('title', 'Untitled')}</a></h3>
<p>{page.get('summary', '')[:150]}...</p>
<span class="category">{page.get('category', 'general')}</span>
<span class="score">相关性: {page.get('relevance_score', 0):.0%}</span>
</div>
"""
    
    @staticmethod
    def fact_item(fact: Dict) -> str:
        """事实项目模板"""
        return f"- **{fact.get('type', 'info')}**: {fact.get('value', '')} ({fact.get('context', '')})"
    
    @staticmethod
    def stats_table(stats: Dict) -> str:
        """统计表格模板"""
        rows = []
        for key, value in stats.items():
            rows.append(f"| {key} | {value} |")
        return "| 指标 | 数值 |\n|------|------|\n" + "\n".join(rows)


if __name__ == "__main__":
    # 测试报告生成器
    from config import get_fast_config
    import shutil
    
    config = get_fast_config()
    config.storage.base_dir = "./test_report_output"
    config.user_intent = "了解斯坦福大学招生信息"
    
    # 创建测试数据
    manager = DataManager(config)
    
    # 添加测试数据
    manager.save_analyzed(
        url="https://test.com/admission",
        analysis={
            'title': 'Admission Page',
            'category': 'admission',
            'summary': 'This is a test summary about admission.',
            'key_points': ['Point 1', 'Point 2'],
            'keywords': ['admission', 'apply'],
            'relevance_score': 0.9
        }
    )
    
    # 生成报告
    generator = ReportGenerator(config, manager)
    reports = generator.generate_all_reports()
    
    print("生成的报告:")
    for name, path in reports.items():
        print(f"  {name}: {path}")
    
    # 清理
    shutil.rmtree("./test_report_output", ignore_errors=True)