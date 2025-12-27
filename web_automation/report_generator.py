#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成器 - Report Generator

生成爬取结果的Markdown报告,包含统计摘要、页面分析、发现数据等。
Generates comprehensive Markdown reports from crawl results including
statistics, page analysis, and extracted data.

设计原则 (Design Principles):
- CleanRL哲学: 单文件自包含、透明处理流程、最小化抽象、便于调试
- 模板化输出: 使用字符串模板生成结构化报告
- 多语言支持: 中英文双语报告内容

Author: AI Assistant
Date: 2024
"""

import sys
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
from loguru import logger

# ============================================================================
# 错误处理 (Error Handling)
# ============================================================================

def get_err_message() -> str:
    """获取当前异常的详细错误信息"""
    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return "No exception"
    return f"{exc_type.__name__}: {exc_value} (line {exc_tb.tb_lineno})"


# ============================================================================
# 数据结构 (Data Structures)
# ============================================================================

@dataclass
class CrawlSummary:
    """
    爬取摘要统计
    
    Attributes:
        start_time: 爬取开始时间
        end_time: 爬取结束时间
        total_pages: 总页面数
        successful_pages: 成功页面数
        failed_pages: 失败页面数
        total_urls_found: 发现的URL总数
        total_data_extracted: 提取的数据项数
        intent: 用户意图
        start_url: 起始URL
    """
    start_time: datetime
    end_time: Optional[datetime] = None
    total_pages: int = 0
    successful_pages: int = 0
    failed_pages: int = 0
    total_urls_found: int = 0
    total_data_extracted: int = 0
    intent: str = ""
    start_url: str = ""


@dataclass
class PageReport:
    """
    单页面报告
    
    Attributes:
        url: 页面URL
        title: 页面标题
        relevance_score: 相关性分数 (0-1)
        key_findings: 关键发现列表
        extracted_data: 提取的数据
        summary: 内容摘要
        priority_urls: 优先URL列表
        fetch_time: 抓取耗时
        analysis_time: 分析耗时
        success: 是否成功
        error: 错误信息
    """
    url: str
    title: str = ""
    relevance_score: float = 0.0
    key_findings: List[str] = field(default_factory=list)
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    priority_urls: List[Dict] = field(default_factory=list)
    fetch_time: float = 0.0
    analysis_time: float = 0.0
    success: bool = True
    error: Optional[str] = None


# ============================================================================
# 报告模板 (Report Templates)
# ============================================================================

REPORT_HEADER_TEMPLATE = """# 网页爬取分析报告
# Web Crawling Analysis Report

---

## 基本信息 / Basic Information

| 项目 / Item | 值 / Value |
|------------|-----------|
| **起始URL / Start URL** | {start_url} |
| **用户意图 / Intent** | {intent} |
| **开始时间 / Start Time** | {start_time} |
| **结束时间 / End Time** | {end_time} |
| **总耗时 / Duration** | {duration} |

---

## 统计摘要 / Statistics Summary

| 指标 / Metric | 数值 / Value |
|--------------|-------------|
| 总页面数 / Total Pages | {total_pages} |
| 成功页面 / Successful | {successful_pages} |
| 失败页面 / Failed | {failed_pages} |
| 成功率 / Success Rate | {success_rate}% |
| 发现URL数 / URLs Found | {total_urls_found} |
| 提取数据项 / Data Items | {total_data_extracted} |

---

"""

PAGE_REPORT_TEMPLATE = """### 📄 {title}

**URL**: {url}

**相关性分数 / Relevance Score**: {relevance_score:.2f}

{findings_section}

{data_section}

{summary_section}

{urls_section}

**处理时间 / Processing Time**: 抓取 {fetch_time:.2f}s, 分析 {analysis_time:.2f}s

---

"""

ERROR_PAGE_TEMPLATE = """### ❌ 处理失败 / Failed

**URL**: {url}

**错误信息 / Error**: {error}

---

"""

# ============================================================================
# 报告生成器 (Report Generator)
# ============================================================================

class ReportGenerator:
    """
    Markdown报告生成器
    
    Features:
        - 结构化报告: 统计摘要、页面分析、数据提取
        - 多格式输出: Markdown、JSON
        - 中英文双语: 支持中英文标签
    
    Example:
        >>> generator = ReportGenerator()
        >>> generator.set_summary(summary)
        >>> generator.add_page_report(page_report)
        >>> report = generator.generate()
    """
    
    def __init__(self):
        """初始化报告生成器"""
        self.summary: Optional[CrawlSummary] = None
        self.page_reports: List[PageReport] = []
        self.metadata: Dict[str, Any] = {}
        
        logger.info("ReportGenerator initialized")
    
    def set_summary(self, summary: CrawlSummary) -> None:
        """设置爬取摘要"""
        self.summary = summary
        logger.debug(f"Summary set: {summary.total_pages} pages")
    
    def add_page_report(self, report: PageReport) -> None:
        """添加页面报告"""
        self.page_reports.append(report)
        logger.debug(f"Page report added: {report.url}")
    
    def add_metadata(self, key: str, value: Any) -> None:
        """添加元数据"""
        self.metadata[key] = value
    
    # ========================================================================
    # 格式化辅助方法 (Formatting Helpers)
    # ========================================================================
    
    def _format_duration(self, start: datetime, end: Optional[datetime]) -> str:
        """格式化时间间隔"""
        if not end:
            return "进行中 / In Progress"
        
        delta = end - start
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}秒 / {total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}分{seconds}秒 / {minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}小时{minutes}分 / {hours}h {minutes}m"
    
    def _format_findings(self, findings: List[str]) -> str:
        """格式化关键发现"""
        if not findings:
            return ""
        
        lines = ["**关键发现 / Key Findings**:", ""]
        for i, finding in enumerate(findings, 1):
            lines.append(f"{i}. {finding}")
        lines.append("")
        
        return "\n".join(lines)
    
    def _format_extracted_data(self, data: Dict[str, Any]) -> str:
        """格式化提取的数据"""
        if not data:
            return ""
        
        lines = ["**提取数据 / Extracted Data**:", ""]
        
        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"- **{key}**:")
                for item in value[:5]:  # 限制显示数量
                    lines.append(f"  - {item}")
                if len(value) > 5:
                    lines.append(f"  - ... ({len(value) - 5} more)")
            elif isinstance(value, dict):
                lines.append(f"- **{key}**: {json.dumps(value, ensure_ascii=False)[:100]}...")
            else:
                lines.append(f"- **{key}**: {value}")
        
        lines.append("")
        return "\n".join(lines)
    
    def _format_summary(self, summary: str) -> str:
        """格式化内容摘要"""
        if not summary:
            return ""
        
        return f"**摘要 / Summary**:\n\n> {summary}\n"
    
    def _format_priority_urls(self, urls: List[Dict]) -> str:
        """格式化优先URL列表"""
        if not urls:
            return ""
        
        lines = ["**推荐访问 / Recommended URLs**:", ""]
        
        priority_labels = {
            1: "🔴 高 / High",
            2: "🟡 中 / Medium",
            3: "🟢 低 / Low"
        }
        
        for url_info in urls[:10]:  # 限制显示数量
            url = url_info.get('url', '')
            priority = url_info.get('priority', 2)
            reason = url_info.get('reason', '')
            
            priority_label = priority_labels.get(priority, "中 / Medium")
            lines.append(f"- [{priority_label}] {url}")
            if reason:
                lines.append(f"  - 原因: {reason}")
        
        if len(urls) > 10:
            lines.append(f"- ... ({len(urls) - 10} more URLs)")
        
        lines.append("")
        return "\n".join(lines)
    
    # ========================================================================
    # 报告生成 (Report Generation)
    # ========================================================================
    
    def _generate_header(self) -> str:
        """生成报告头部"""
        if not self.summary:
            return "# Web Crawling Report\n\n*No summary available*\n\n"
        
        s = self.summary
        success_rate = (s.successful_pages / s.total_pages * 100) if s.total_pages > 0 else 0
        
        return REPORT_HEADER_TEMPLATE.format(
            start_url=s.start_url,
            intent=s.intent,
            start_time=s.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=s.end_time.strftime("%Y-%m-%d %H:%M:%S") if s.end_time else "N/A",
            duration=self._format_duration(s.start_time, s.end_time),
            total_pages=s.total_pages,
            successful_pages=s.successful_pages,
            failed_pages=s.failed_pages,
            success_rate=f"{success_rate:.1f}",
            total_urls_found=s.total_urls_found,
            total_data_extracted=s.total_data_extracted
        )
    
    def _generate_page_section(self, report: PageReport) -> str:
        """生成单页面报告section"""
        if not report.success:
            return ERROR_PAGE_TEMPLATE.format(
                url=report.url,
                error=report.error or "Unknown error"
            )
        
        return PAGE_REPORT_TEMPLATE.format(
            title=report.title or "Untitled",
            url=report.url,
            relevance_score=report.relevance_score,
            findings_section=self._format_findings(report.key_findings),
            data_section=self._format_extracted_data(report.extracted_data),
            summary_section=self._format_summary(report.summary),
            urls_section=self._format_priority_urls(report.priority_urls),
            fetch_time=report.fetch_time,
            analysis_time=report.analysis_time
        )
    
    def _generate_pages_section(self) -> str:
        """生成所有页面报告"""
        if not self.page_reports:
            return "## 页面分析 / Page Analysis\n\n*No pages analyzed*\n\n"
        
        lines = ["## 页面分析 / Page Analysis", ""]
        
        # 按相关性分数排序
        sorted_reports = sorted(
            self.page_reports,
            key=lambda x: x.relevance_score,
            reverse=True
        )
        
        for report in sorted_reports:
            lines.append(self._generate_page_section(report))
        
        return "\n".join(lines)
    
    def _generate_data_summary(self) -> str:
        """生成数据汇总section"""
        all_data = {}
        all_findings = []
        
        for report in self.page_reports:
            if report.success:
                # 收集所有发现
                all_findings.extend(report.key_findings)
                
                # 合并提取的数据
                for key, value in report.extracted_data.items():
                    if key not in all_data:
                        all_data[key] = []
                    if isinstance(value, list):
                        all_data[key].extend(value)
                    else:
                        all_data[key].append(value)
        
        lines = ["## 数据汇总 / Data Summary", ""]
        
        # 关键发现汇总
        if all_findings:
            lines.append("### 所有关键发现 / All Key Findings")
            lines.append("")
            for i, finding in enumerate(all_findings[:20], 1):
                lines.append(f"{i}. {finding}")
            if len(all_findings) > 20:
                lines.append(f"\n*... and {len(all_findings) - 20} more findings*")
            lines.append("")
        
        # 提取数据汇总
        if all_data:
            lines.append("### 提取数据汇总 / Extracted Data Summary")
            lines.append("")
            for key, values in all_data.items():
                unique_values = list(set(str(v) for v in values if v))[:10]
                lines.append(f"**{key}** ({len(values)} items):")
                for v in unique_values:
                    lines.append(f"  - {v[:100]}{'...' if len(v) > 100 else ''}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        return "\n".join(lines)
    
    def _generate_footer(self) -> str:
        """生成报告底部"""
        lines = [
            "## 报告信息 / Report Information",
            "",
            f"- **生成时间 / Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **报告版本 / Version**: 1.0",
            f"- **生成器 / Generator**: Web Automation Tool",
            ""
        ]
        
        if self.metadata:
            lines.append("### 元数据 / Metadata")
            lines.append("")
            for key, value in self.metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
        
        lines.extend([
            "---",
            "",
            "*此报告由自动化工具生成 / This report was generated automatically*"
        ])
        
        return "\n".join(lines)
    
    def generate(self) -> str:
        """
        生成完整的Markdown报告
        
        Returns:
            Markdown格式的报告字符串
        """
        try:
            sections = [
                self._generate_header(),
                self._generate_pages_section(),
                self._generate_data_summary(),
                self._generate_footer()
            ]
            
            report = "\n".join(sections)
            logger.info(f"Report generated: {len(report)} characters")
            
            return report
            
        except Exception:
            logger.error(f"Report generation failed: {get_err_message()}")
            return f"# Error\n\nFailed to generate report: {get_err_message()}"
    
    def generate_json(self) -> Dict[str, Any]:
        """
        生成JSON格式的报告数据
        
        Returns:
            报告数据字典
        """
        try:
            data = {
                'generated_at': datetime.now().isoformat(),
                'summary': None,
                'pages': [],
                'metadata': self.metadata
            }
            
            if self.summary:
                s = self.summary
                data['summary'] = {
                    'start_url': s.start_url,
                    'intent': s.intent,
                    'start_time': s.start_time.isoformat(),
                    'end_time': s.end_time.isoformat() if s.end_time else None,
                    'total_pages': s.total_pages,
                    'successful_pages': s.successful_pages,
                    'failed_pages': s.failed_pages,
                    'total_urls_found': s.total_urls_found,
                    'total_data_extracted': s.total_data_extracted
                }
            
            for report in self.page_reports:
                data['pages'].append({
                    'url': report.url,
                    'title': report.title,
                    'relevance_score': report.relevance_score,
                    'key_findings': report.key_findings,
                    'extracted_data': report.extracted_data,
                    'summary': report.summary,
                    'priority_urls': report.priority_urls,
                    'fetch_time': report.fetch_time,
                    'analysis_time': report.analysis_time,
                    'success': report.success,
                    'error': report.error
                })
            
            logger.info("JSON report generated")
            return data
            
        except Exception:
            logger.error(f"JSON report generation failed: {get_err_message()}")
            return {'error': get_err_message()}
    
    def save_report(
        self,
        output_dir: str,
        filename: Optional[str] = None,
        formats: List[str] = None
    ) -> Dict[str, str]:
        """
        保存报告到文件
        
        Args:
            output_dir: 输出目录
            filename: 文件名 (不含扩展名)
            formats: 输出格式列表 ['md', 'json']
            
        Returns:
            保存的文件路径字典
        """
        formats = formats or ['md']
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"crawl_report_{timestamp}"
        
        saved_files = {}
        
        try:
            if 'md' in formats:
                md_path = output_path / f"{filename}.md"
                md_content = self.generate()
                md_path.write_text(md_content, encoding='utf-8')
                saved_files['md'] = str(md_path)
                logger.info(f"Markdown report saved: {md_path}")
            
            if 'json' in formats:
                json_path = output_path / f"{filename}.json"
                json_data = self.generate_json()
                json_path.write_text(
                    json.dumps(json_data, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                saved_files['json'] = str(json_path)
                logger.info(f"JSON report saved: {json_path}")
            
            return saved_files
            
        except Exception:
            logger.error(f"Failed to save report: {get_err_message()}")
            return saved_files
    
    def reset(self) -> None:
        """重置报告生成器"""
        self.summary = None
        self.page_reports = []
        self.metadata = {}
        logger.debug("Report generator reset")


# ============================================================================
# 便捷函数 (Convenience Functions)
# ============================================================================

def create_summary_from_results(
    results: List[Dict],
    start_url: str,
    intent: str,
    start_time: datetime,
    end_time: Optional[datetime] = None
) -> CrawlSummary:
    """
    从结果列表创建摘要
    
    Args:
        results: 页面结果列表
        start_url: 起始URL
        intent: 用户意图
        start_time: 开始时间
        end_time: 结束时间
        
    Returns:
        CrawlSummary对象
    """
    successful = sum(1 for r in results if r.get('success', True))
    failed = len(results) - successful
    
    total_urls = sum(len(r.get('priority_urls', [])) for r in results)
    total_data = sum(len(r.get('extracted_data', {})) for r in results)
    
    return CrawlSummary(
        start_time=start_time,
        end_time=end_time or datetime.now(),
        total_pages=len(results),
        successful_pages=successful,
        failed_pages=failed,
        total_urls_found=total_urls,
        total_data_extracted=total_data,
        intent=intent,
        start_url=start_url
    )


def create_page_report_from_result(result: Dict) -> PageReport:
    """
    从结果字典创建页面报告
    
    Args:
        result: 页面结果字典
        
    Returns:
        PageReport对象
    """
    return PageReport(
        url=result.get('url', ''),
        title=result.get('title', ''),
        relevance_score=result.get('relevance_score', 0.0),
        key_findings=result.get('key_findings', []),
        extracted_data=result.get('extracted_data', {}),
        summary=result.get('summary', ''),
        priority_urls=result.get('priority_urls', []),
        fetch_time=result.get('fetch_time', 0.0),
        analysis_time=result.get('analysis_time', 0.0),
        success=result.get('success', True),
        error=result.get('error')
    )


# ============================================================================
# 测试代码 (Test Code)
# ============================================================================

if __name__ == "__main__":
    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"
    )
    
    print("=" * 60)
    print("Report Generator Test")
    print("=" * 60)
    
    # 创建测试数据
    start_time = datetime.now()
    
    # 创建摘要
    summary = CrawlSummary(
        start_time=start_time,
        end_time=datetime.now(),
        total_pages=3,
        successful_pages=2,
        failed_pages=1,
        total_urls_found=15,
        total_data_extracted=8,
        intent="招生信息",
        start_url="https://www.stanford.edu/"
    )
    
    # 创建页面报告
    page1 = PageReport(
        url="https://www.stanford.edu/admission",
        title="Stanford Admission",
        relevance_score=0.95,
        key_findings=[
            "本科申请截止日期为1月2日",
            "需要提交SAT/ACT成绩",
            "录取率约为4%"
        ],
        extracted_data={
            "deadline": "January 2",
            "acceptance_rate": "4%",
            "required_tests": ["SAT", "ACT"]
        },
        summary="斯坦福大学招生页面,包含本科和研究生申请信息。",
        priority_urls=[
            {"url": "https://www.stanford.edu/apply", "priority": 1, "reason": "申请入口"},
            {"url": "https://www.stanford.edu/finaid", "priority": 2, "reason": "经济援助"}
        ],
        fetch_time=2.5,
        analysis_time=3.2,
        success=True
    )
    
    page2 = PageReport(
        url="https://www.stanford.edu/about",
        title="About Stanford",
        relevance_score=0.45,
        key_findings=["学校成立于1885年", "位于加州帕洛阿尔托"],
        extracted_data={"founded": "1885", "location": "Palo Alto, CA"},
        summary="学校简介页面",
        priority_urls=[],
        fetch_time=1.8,
        analysis_time=2.1,
        success=True
    )
    
    page3 = PageReport(
        url="https://www.stanford.edu/broken",
        title="",
        success=False,
        error="Connection timeout"
    )
    
    # 生成报告
    generator = ReportGenerator()
    generator.set_summary(summary)
    generator.add_page_report(page1)
    generator.add_page_report(page2)
    generator.add_page_report(page3)
    generator.add_metadata("crawler_version", "1.0.0")
    generator.add_metadata("user_agent", "WebAutomationBot/1.0")
    
    # 生成Markdown报告
    report = generator.generate()
    print("\n" + "=" * 60)
    print("Generated Markdown Report:")
    print("=" * 60)
    print(report)
    
    # 保存报告
    saved = generator.save_report(
        output_dir="/home/claude/web_automation/test_reports",
        filename="test_report",
        formats=['md', 'json']
    )
    print(f"\nSaved files: {saved}")
    
    print("\n测试完成!")
