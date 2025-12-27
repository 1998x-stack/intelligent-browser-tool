"""
数据管理器 - 分层次的数据存储和管理

设计理念:
- 分层存储: raw -> extracted -> analyzed -> reports
- 统一命名: 使用AI生成的语义化文件名
- 增量保存: 支持断点续爬
- 索引管理: 维护数据索引便于查询

参考: Skills文件格式规范
"""

import json
import hashlib
import shutil
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

from loguru import logger

from config import Config


@dataclass
class PageRecord:
    """页面记录"""
    url: str
    filename: str
    category: str
    title: str
    timestamp: str
    status: str  # raw, extracted, analyzed
    content_hash: str
    metadata: Dict = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class DataManager:
    """
    数据管理器 - 负责爬取数据的存储和组织
    
    目录结构:
    output/
    ├── 01_raw/              # 原始HTML
    │   ├── index.json       # 页面索引
    │   └── *.html           # HTML文件
    ├── 02_extracted/        # 提取的内容
    │   ├── index.json
    │   └── *.json           # 提取的JSON
    ├── 03_analyzed/         # AI分析结果
    │   ├── index.json
    │   └── *.json           # 分析结果
    ├── 04_reports/          # 最终报告
    │   ├── summary.md       # 总览报告
    │   ├── admission/       # 按类别分目录
    │   └── research/
    └── metadata.json        # 任务元数据
    
    使用示例:
        manager = DataManager(config)
        manager.save_raw(url, html, filename)
        manager.save_extracted(url, content)
        manager.save_analyzed(url, analysis)
    """
    
    def __init__(self, config: Config):
        """
        初始化数据管理器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.storage = config.storage
        self.base_dir = Path(config.storage.base_dir)
        
        # 目录路径
        self.raw_dir = self.base_dir / self.storage.raw_dir
        self.extracted_dir = self.base_dir / self.storage.extracted_dir
        self.analyzed_dir = self.base_dir / self.storage.analyzed_dir
        self.reports_dir = self.base_dir / self.storage.reports_dir
        
        # 索引
        self._raw_index: Dict[str, PageRecord] = {}
        self._extracted_index: Dict[str, PageRecord] = {}
        self._analyzed_index: Dict[str, PageRecord] = {}
        
        # 初始化
        self._setup_directories()
        self._load_indexes()
        self._save_metadata()
        
        logger.info(f"数据管理器初始化完成 - 基础目录: {self.base_dir}")
    
    def _setup_directories(self):
        """创建目录结构"""
        for dir_path in [
            self.raw_dir, 
            self.extracted_dir, 
            self.analyzed_dir, 
            self.reports_dir
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _load_indexes(self):
        """加载现有索引"""
        for stage, index in [
            ('raw', self._raw_index),
            ('extracted', self._extracted_index),
            ('analyzed', self._analyzed_index)
        ]:
            index_file = self._get_stage_dir(stage) / 'index.json'
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for url, record in data.items():
                        index[url] = PageRecord(**record)
                    logger.debug(f"加载 {stage} 索引: {len(index)} 条记录")
                except Exception as e:
                    logger.warning(f"加载索引失败 {stage}: {e}")
    
    def _save_index(self, stage: str):
        """保存索引"""
        index = self._get_index(stage)
        index_file = self._get_stage_dir(stage) / 'index.json'
        
        try:
            data = {url: record.to_dict() for url, record in index.items()}
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存索引失败 {stage}: {e}")
    
    def _save_metadata(self):
        """保存任务元数据"""
        metadata = {
            'task_name': self.config.task_name,
            'start_url': self.config.start_url,
            'user_intent': self.config.user_intent,
            'created_at': datetime.now().isoformat(),
            'config': self.config.to_dict()
        }
        
        metadata_file = self.base_dir / 'metadata.json'
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    def _get_stage_dir(self, stage: str) -> Path:
        """获取阶段目录"""
        stage_map = {
            'raw': self.raw_dir,
            'extracted': self.extracted_dir,
            'analyzed': self.analyzed_dir,
            'reports': self.reports_dir
        }
        return stage_map.get(stage, self.base_dir)
    
    def _get_index(self, stage: str) -> Dict[str, PageRecord]:
        """获取索引"""
        index_map = {
            'raw': self._raw_index,
            'extracted': self._extracted_index,
            'analyzed': self._analyzed_index
        }
        return index_map.get(stage, {})
    
    def _generate_filename(
        self, 
        url: str, 
        title: str = "", 
        category: str = "general"
    ) -> str:
        """
        生成文件名
        
        格式: {category}_{hash}_{sanitized_title}
        """
        # URL哈希
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        
        # 清理标题
        if title:
            # 只保留字母数字和下划线
            sanitized = ''.join(
                c if c.isalnum() or c == ' ' else '_' 
                for c in title[:30]
            )
            sanitized = sanitized.replace(' ', '_').lower()
            sanitized = '_'.join(filter(None, sanitized.split('_')))
        else:
            sanitized = "page"
        
        return f"{category}_{url_hash}_{sanitized}"
    
    # ========== 原始HTML存储 ==========
    
    def save_raw(
        self, 
        url: str, 
        html: str, 
        title: str = "",
        category: str = "general",
        filename: str = None
    ) -> str:
        """
        保存原始HTML
        
        Args:
            url: 页面URL
            html: HTML内容
            title: 页面标题
            category: 页面类别
            filename: 自定义文件名
            
        Returns:
            保存的文件路径
        """
        if not filename:
            filename = self._generate_filename(url, title, category)
        
        filepath = self.raw_dir / f"{filename}.html"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html)
            
            # 更新索引
            record = PageRecord(
                url=url,
                filename=filename,
                category=category,
                title=title,
                timestamp=datetime.now().isoformat(),
                status='raw',
                content_hash=hashlib.md5(html.encode()).hexdigest()[:16]
            )
            self._raw_index[url] = record
            self._save_index('raw')
            
            logger.debug(f"保存原始HTML: {filename}.html")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"保存HTML失败: {e}")
            return ""
    
    def get_raw(self, url: str) -> Optional[str]:
        """获取原始HTML"""
        record = self._raw_index.get(url)
        if not record:
            return None
        
        filepath = self.raw_dir / f"{record.filename}.html"
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    # ========== 提取内容存储 ==========
    
    def save_extracted(
        self, 
        url: str, 
        content: Dict,
        filename: str = None
    ) -> str:
        """
        保存提取的内容
        
        Args:
            url: 页面URL
            content: 提取的内容字典
            filename: 自定义文件名
            
        Returns:
            保存的文件路径
        """
        # 使用原始索引中的文件名保持一致
        raw_record = self._raw_index.get(url)
        if not filename and raw_record:
            filename = raw_record.filename
        elif not filename:
            filename = self._generate_filename(
                url, 
                content.get('title', ''),
                content.get('category', 'general')
            )
        
        filepath = self.extracted_dir / f"{filename}.json"
        
        try:
            # 添加元数据
            content['_meta'] = {
                'url': url,
                'extracted_at': datetime.now().isoformat(),
                'filename': filename
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
            
            # 更新索引
            record = PageRecord(
                url=url,
                filename=filename,
                category=content.get('category', 'general'),
                title=content.get('title', ''),
                timestamp=datetime.now().isoformat(),
                status='extracted',
                content_hash=content.get('stats', {}).get('content_hash', '')
            )
            self._extracted_index[url] = record
            self._save_index('extracted')
            
            logger.debug(f"保存提取内容: {filename}.json")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"保存提取内容失败: {e}")
            return ""
    
    def get_extracted(self, url: str) -> Optional[Dict]:
        """获取提取的内容"""
        record = self._extracted_index.get(url)
        if not record:
            return None
        
        filepath = self.extracted_dir / f"{record.filename}.json"
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    # ========== 分析结果存储 ==========
    
    def save_analyzed(
        self, 
        url: str, 
        analysis: Dict,
        filename: str = None
    ) -> str:
        """
        保存分析结果
        
        Args:
            url: 页面URL
            analysis: 分析结果字典
            filename: 自定义文件名
            
        Returns:
            保存的文件路径
        """
        # 使用一致的文件名
        for index in [self._extracted_index, self._raw_index]:
            record = index.get(url)
            if record:
                filename = filename or record.filename
                break
        
        if not filename:
            filename = self._generate_filename(
                url,
                analysis.get('title', ''),
                analysis.get('category', 'general')
            )
        
        filepath = self.analyzed_dir / f"{filename}.json"
        
        try:
            # 添加元数据
            analysis['_meta'] = {
                'url': url,
                'analyzed_at': datetime.now().isoformat(),
                'filename': filename
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)
            
            # 更新索引
            category = analysis.get('category', 'general')
            record = PageRecord(
                url=url,
                filename=filename,
                category=category,
                title=analysis.get('title', ''),
                timestamp=datetime.now().isoformat(),
                status='analyzed',
                content_hash='',
                metadata={
                    'relevance_score': analysis.get('relevance_score', 0),
                    'model': analysis.get('model', '')
                }
            )
            self._analyzed_index[url] = record
            self._save_index('analyzed')
            
            logger.debug(f"保存分析结果: {filename}.json")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
            return ""
    
    def get_analyzed(self, url: str) -> Optional[Dict]:
        """获取分析结果"""
        record = self._analyzed_index.get(url)
        if not record:
            return None
        
        filepath = self.analyzed_dir / f"{record.filename}.json"
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    # ========== 报告存储 ==========
    
    def save_report(
        self, 
        name: str, 
        content: str, 
        category: str = None,
        format: str = 'md'
    ) -> str:
        """
        保存报告
        
        Args:
            name: 报告名称
            content: 报告内容
            category: 分类目录
            format: 文件格式
            
        Returns:
            保存的文件路径
        """
        if category:
            report_dir = self.reports_dir / category
            report_dir.mkdir(parents=True, exist_ok=True)
        else:
            report_dir = self.reports_dir
        
        filepath = report_dir / f"{name}.{format}"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.debug(f"保存报告: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"保存报告失败: {e}")
            return ""
    
    # ========== 查询和统计 ==========
    
    def get_all_analyzed(self) -> List[Dict]:
        """获取所有分析结果"""
        results = []
        for url in self._analyzed_index:
            data = self.get_analyzed(url)
            if data:
                results.append(data)
        return results
    
    def get_by_category(self, category: str) -> List[Dict]:
        """按类别获取分析结果"""
        results = []
        for url, record in self._analyzed_index.items():
            if record.category == category:
                data = self.get_analyzed(url)
                if data:
                    results.append(data)
        return results
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        # 按类别统计
        category_stats = {}
        for record in self._analyzed_index.values():
            cat = record.category
            category_stats[cat] = category_stats.get(cat, 0) + 1
        
        return {
            'total_raw': len(self._raw_index),
            'total_extracted': len(self._extracted_index),
            'total_analyzed': len(self._analyzed_index),
            'by_category': category_stats,
            'base_dir': str(self.base_dir)
        }
    
    def is_processed(self, url: str, stage: str = 'analyzed') -> bool:
        """检查URL是否已处理"""
        index = self._get_index(stage)
        return url in index
    
    def get_unprocessed_urls(
        self, 
        from_stage: str = 'extracted', 
        to_stage: str = 'analyzed'
    ) -> List[str]:
        """获取未处理的URL列表"""
        from_index = self._get_index(from_stage)
        to_index = self._get_index(to_stage)
        
        return [url for url in from_index if url not in to_index]
    
    def export_summary(self) -> Dict:
        """导出摘要"""
        summary = {
            'task': {
                'name': self.config.task_name,
                'intent': self.config.user_intent,
                'start_url': self.config.start_url
            },
            'stats': self.get_stats(),
            'pages': []
        }
        
        for url, record in self._analyzed_index.items():
            page_info = {
                'url': url,
                'title': record.title,
                'category': record.category,
                'timestamp': record.timestamp
            }
            if record.metadata:
                page_info.update(record.metadata)
            summary['pages'].append(page_info)
        
        return summary


if __name__ == "__main__":
    # 测试数据管理器
    from config import get_fast_config
    
    config = get_fast_config()
    config.storage.base_dir = "./test_output"
    
    manager = DataManager(config)
    
    # 测试保存
    manager.save_raw(
        url="https://example.com/test",
        html="<html><body>Test</body></html>",
        title="Test Page",
        category="test"
    )
    
    manager.save_extracted(
        url="https://example.com/test",
        content={'title': 'Test', 'text': 'Content'}
    )
    
    manager.save_analyzed(
        url="https://example.com/test",
        analysis={'title': 'Test', 'summary': 'Analysis'}
    )
    
    print(json.dumps(manager.get_stats(), indent=2))
    
    # 清理测试目录
    shutil.rmtree("./test_output", ignore_errors=True)