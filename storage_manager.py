#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储管理器 - 分层数据存储系统

设计理念 (CleanRL Philosophy):
- 单文件自包含: 完整的存储功能实现
- 透明的处理流程: 清晰的存储/读取逻辑
- 最小化抽象: 直接的文件操作
- 便于调试: 详细的存储日志

目录结构:
outputs/
├── raw/              # 原始HTML
├── processed/        # 提取的内容 (JSON)
├── analysis/         # LLM分析结果 (JSON)
├── reports/          # 生成的报告 (Markdown)
├── logs/             # 日志文件
└── state/            # 队列状态和检查点

功能特性:
- 分层存储结构
- 语义化文件命名 (使用LLM)
- 内容去重
- 元数据管理
- 增量存储支持
"""

import sys
import traceback
import json
import hashlib
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

from loguru import logger

from config import Config


# ============================================================================
# 错误处理工具
# ============================================================================

def get_err_message() -> str:
    """获取详细的异常信息"""
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class StoredFile:
    """存储的文件信息"""
    filepath: Path
    filename: str
    content_hash: str
    size_bytes: int
    created_at: str
    category: str  # raw, processed, analysis, reports
    url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "filepath": str(self.filepath),
            "filename": self.filename,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "category": self.category,
            "url": self.url,
            "metadata": self.metadata
        }


@dataclass
class StorageStats:
    """存储统计信息"""
    total_files: int = 0
    total_size_bytes: int = 0
    files_by_category: Dict[str, int] = field(default_factory=dict)
    size_by_category: Dict[str, int] = field(default_factory=dict)
    duplicates_skipped: int = 0
    files_saved: int = 0  # 成功保存的文件数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_files": self.total_files,
            "total_size_bytes": self.total_size_bytes,
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 2),
            "files_by_category": self.files_by_category,
            "size_by_category": self.size_by_category,
            "duplicates_skipped": self.duplicates_skipped,
            "files_saved": self.files_saved
        }


# ============================================================================
# 内容去重器
# ============================================================================

class ContentDeduplicator:
    """
    内容去重器 - 基于哈希的内容去重
    
    使用MD5/SHA256哈希检测重复内容
    """
    
    def __init__(self):
        """初始化去重器"""
        self._seen_hashes: Dict[str, str] = {}  # hash -> filepath
    
    def compute_hash(self, content: str, algorithm: str = "md5") -> str:
        """
        计算内容哈希值
        
        Args:
            content: 内容字符串
            algorithm: 哈希算法 (md5/sha256)
            
        Returns:
            哈希值
        """
        if algorithm == "sha256":
            return hashlib.sha256(content.encode()).hexdigest()
        return hashlib.md5(content.encode()).hexdigest()
    
    def is_duplicate(self, content: str) -> Tuple[bool, Optional[str]]:
        """
        检查内容是否重复
        
        Args:
            content: 内容字符串
            
        Returns:
            (是否重复, 如果重复返回已存在的文件路径)
        """
        content_hash = self.compute_hash(content)
        if content_hash in self._seen_hashes:
            return True, self._seen_hashes[content_hash]
        return False, None
    
    def register(self, content: str, filepath: str):
        """
        注册内容哈希
        
        Args:
            content: 内容字符串
            filepath: 文件路径
        """
        content_hash = self.compute_hash(content)
        self._seen_hashes[content_hash] = filepath
    
    def get_hash(self, content: str) -> str:
        """获取内容哈希"""
        return self.compute_hash(content)
    
    def clear(self):
        """清空已注册的哈希"""
        self._seen_hashes.clear()


# ============================================================================
# 文件命名器
# ============================================================================

class FileNamingHelper:
    """
    文件命名辅助器 - 生成安全的文件名
    
    不依赖LLM的基础命名功能
    """
    
    # 不安全字符替换
    UNSAFE_CHARS = '<>:"/\\|?*\x00'
    
    @classmethod
    def sanitize(cls, name: str, max_length: int = 50) -> str:
        """
        清理文件名
        
        Args:
            name: 原始名称
            max_length: 最大长度
            
        Returns:
            清理后的文件名
        """
        # 替换不安全字符
        for char in cls.UNSAFE_CHARS:
            name = name.replace(char, "_")
        
        # 替换空白字符
        name = "_".join(name.split())
        
        # 小写化
        name = name.lower()
        
        # 只保留字母数字和下划线
        name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        
        # 合并连续下划线
        while "__" in name:
            name = name.replace("__", "_")
        
        # 去除首尾下划线
        name = name.strip("_")
        
        # 限制长度
        if len(name) > max_length:
            name = name[:max_length].rstrip("_")
        
        return name or "unnamed"
    
    @classmethod
    def from_url(cls, url: str) -> str:
        """
        从URL生成文件名
        
        Args:
            url: URL
            
        Returns:
            文件名
        """
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(url)
            
            # 使用路径部分
            path = parsed.path.strip("/")
            if path:
                # 取最后一个路径段
                parts = path.split("/")
                name = parts[-1] if parts else ""
                
                # 移除扩展名
                if "." in name:
                    name = name.rsplit(".", 1)[0]
                
                if name:
                    return cls.sanitize(name)
            
            # 使用域名
            domain = parsed.netloc.replace("www.", "")
            return cls.sanitize(domain.split(".")[0])
            
        except Exception:
            return "page"
    
    @classmethod
    def with_timestamp(cls, base_name: str, extension: str = "") -> str:
        """
        添加时间戳后缀
        
        Args:
            base_name: 基础名称
            extension: 文件扩展名
            
        Returns:
            带时间戳的文件名
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{cls.sanitize(base_name)}_{timestamp}"
        if extension:
            extension = extension.lstrip(".")
            name = f"{name}.{extension}"
        return name
    
    @classmethod
    def with_hash(cls, base_name: str, content: str, extension: str = "") -> str:
        """
        添加内容哈希后缀 (确保唯一性)
        
        Args:
            base_name: 基础名称
            content: 内容 (用于计算哈希)
            extension: 文件扩展名
            
        Returns:
            带哈希的文件名
        """
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        name = f"{cls.sanitize(base_name)}_{content_hash}"
        if extension:
            extension = extension.lstrip(".")
            name = f"{name}.{extension}"
        return name


# ============================================================================
# 存储管理器
# ============================================================================

class StorageManager:
    """
    存储管理器 - 分层数据存储
    
    提供统一的存储接口,管理:
    - 原始HTML存储
    - 处理后内容存储
    - LLM分析结果存储
    - 报告生成存储
    - 状态检查点存储
    
    使用示例:
        storage = StorageManager(config)
        
        # 存储原始HTML
        storage.save_raw_html(url, html_content)
        
        # 存储处理后的内容
        storage.save_processed_content(url, content_dict)
        
        # 存储分析结果
        storage.save_analysis_result(url, analysis_dict)
    """
    
    # 目录名称常量
    DIR_RAW = "raw"
    DIR_PROCESSED = "processed"
    DIR_ANALYSIS = "analysis"
    DIR_REPORTS = "reports"
    DIR_LOGS = "logs"
    DIR_STATE = "state"
    
    def __init__(self, config: Config, file_namer=None):
        """
        初始化存储管理器
        
        Args:
            config: 配置对象
            file_namer: 可选的LLM文件命名器
        """
        self.config = config
        self.file_namer = file_namer  # 可选的LLM命名器
        
        # 基础目录
        self.base_dir = Path(config.storage.base_dir)
        
        # 子目录
        self.raw_dir = self.base_dir / self.DIR_RAW
        self.processed_dir = self.base_dir / self.DIR_PROCESSED
        self.analysis_dir = self.base_dir / self.DIR_ANALYSIS
        self.reports_dir = self.base_dir / self.DIR_REPORTS
        self.logs_dir = self.base_dir / self.DIR_LOGS
        self.state_dir = self.base_dir / self.DIR_STATE
        
        # 去重器
        self._deduplicator = ContentDeduplicator()
        
        # 文件索引
        self._file_index: Dict[str, StoredFile] = {}  # url -> StoredFile
        
        # 统计信息
        self._stats = StorageStats()
        
        # 初始化目录结构
        self._init_directories()
        
        logger.info(f"存储管理器初始化完成: {self.base_dir}")
    
    def _init_directories(self):
        """初始化目录结构"""
        directories = [
            self.raw_dir,
            self.processed_dir,
            self.analysis_dir,
            self.reports_dir,
            self.logs_dir,
            self.state_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"确保目录存在: {directory}")
    
    # ========================================================================
    # 核心存储方法
    # ========================================================================
    
    def save_raw_html(
        self,
        url: str,
        html_content: str,
        filename: Optional[str] = None,
        skip_duplicate: bool = True
    ) -> Optional[StoredFile]:
        """
        保存原始HTML内容
        
        Args:
            url: 页面URL
            html_content: HTML内容
            filename: 可选的文件名
            skip_duplicate: 是否跳过重复内容
            
        Returns:
            存储的文件信息，失败或跳过返回None
        """
        # 检查重复
        if skip_duplicate:
            is_dup, existing_path = self._deduplicator.is_duplicate(html_content)
            if is_dup:
                logger.debug(f"跳过重复HTML: {url} (已存在: {existing_path})")
                self._stats.duplicates_skipped += 1
                return None
        
        # 生成文件名
        if not filename:
            filename = self._generate_filename(url, html_content, "html")
        
        # 确保扩展名
        if not filename.endswith(".html"):
            filename = f"{filename}.html"
        
        # 完整路径
        filepath = self.raw_dir / filename
        
        # 避免覆盖
        filepath = self._ensure_unique_path(filepath)
        
        # 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            
            # 注册哈希
            self._deduplicator.register(html_content, str(filepath))
            
            # 创建文件记录
            stored_file = StoredFile(
                filepath=filepath,
                filename=filepath.name,
                content_hash=self._deduplicator.get_hash(html_content),
                size_bytes=len(html_content.encode("utf-8")),
                created_at=datetime.now().isoformat(),
                category=self.DIR_RAW,
                url=url
            )
            
            # 更新索引和统计
            self._file_index[url] = stored_file
            self._update_stats(stored_file)
            
            logger.debug(f"保存原始HTML: {filepath}")
            return stored_file
            
        except Exception as e:
            logger.error(f"保存HTML失败 ({url}): {e}")
            logger.debug(get_err_message())
            return None
    
    def save_processed_content(
        self,
        url: str,
        content: Dict[str, Any],
        filename: Optional[str] = None
    ) -> Optional[StoredFile]:
        """
        保存处理后的内容 (JSON格式)
        
        Args:
            url: 页面URL
            content: 内容字典
            filename: 可选的文件名
            
        Returns:
            存储的文件信息
        """
        # 添加元数据
        content_with_meta = {
            "url": url,
            "processed_at": datetime.now().isoformat(),
            **content
        }
        
        # 序列化
        json_content = json.dumps(content_with_meta, ensure_ascii=False, indent=2)
        
        # 生成文件名
        if not filename:
            filename = self._generate_filename(url, json_content, "json")
        
        # 确保扩展名
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        
        # 完整路径
        filepath = self.processed_dir / filename
        filepath = self._ensure_unique_path(filepath)
        
        # 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_content)
            
            stored_file = StoredFile(
                filepath=filepath,
                filename=filepath.name,
                content_hash=self._deduplicator.get_hash(json_content),
                size_bytes=len(json_content.encode("utf-8")),
                created_at=datetime.now().isoformat(),
                category=self.DIR_PROCESSED,
                url=url,
                metadata={"keys": list(content.keys())}
            )
            
            self._update_stats(stored_file)
            
            logger.debug(f"保存处理内容: {filepath}")
            return stored_file
            
        except Exception as e:
            logger.error(f"保存处理内容失败 ({url}): {e}")
            logger.debug(get_err_message())
            return None
    
    def save_analysis_result(
        self,
        url: str,
        analysis: Dict[str, Any],
        filename: Optional[str] = None
    ) -> Optional[StoredFile]:
        """
        保存LLM分析结果 (JSON格式)
        
        Args:
            url: 页面URL
            analysis: 分析结果字典
            filename: 可选的文件名
            
        Returns:
            存储的文件信息
        """
        # 添加元数据
        analysis_with_meta = {
            "url": url,
            "analyzed_at": datetime.now().isoformat(),
            **analysis
        }
        
        # 序列化
        json_content = json.dumps(analysis_with_meta, ensure_ascii=False, indent=2)
        
        # 生成文件名
        if not filename:
            base_name = self._generate_filename(url, json_content, "")
            filename = f"analysis_{base_name}.json"
        
        # 确保扩展名
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        
        # 完整路径
        filepath = self.analysis_dir / filename
        filepath = self._ensure_unique_path(filepath)
        
        # 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_content)
            
            stored_file = StoredFile(
                filepath=filepath,
                filename=filepath.name,
                content_hash=self._deduplicator.get_hash(json_content),
                size_bytes=len(json_content.encode("utf-8")),
                created_at=datetime.now().isoformat(),
                category=self.DIR_ANALYSIS,
                url=url,
                metadata={
                    "relevance_score": analysis.get("relevance_score"),
                    "has_urls": bool(analysis.get("prioritized_urls"))
                }
            )
            
            self._update_stats(stored_file)
            
            logger.debug(f"保存分析结果: {filepath}")
            return stored_file
            
        except Exception as e:
            logger.error(f"保存分析结果失败 ({url}): {e}")
            logger.debug(get_err_message())
            return None
    
    def save_report(
        self,
        report_name: str,
        content: str,
        report_type: str = "markdown"
    ) -> Optional[StoredFile]:
        """
        保存报告
        
        Args:
            report_name: 报告名称
            content: 报告内容
            report_type: 报告类型 (markdown/html/json)
            
        Returns:
            存储的文件信息
        """
        # 确定扩展名
        ext_map = {
            "markdown": ".md",
            "html": ".html",
            "json": ".json"
        }
        extension = ext_map.get(report_type, ".md")
        
        # 生成文件名
        filename = FileNamingHelper.sanitize(report_name)
        if not filename.endswith(extension):
            filename = f"{filename}{extension}"
        
        # 完整路径
        filepath = self.reports_dir / filename
        filepath = self._ensure_unique_path(filepath)
        
        # 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            
            stored_file = StoredFile(
                filepath=filepath,
                filename=filepath.name,
                content_hash=self._deduplicator.get_hash(content),
                size_bytes=len(content.encode("utf-8")),
                created_at=datetime.now().isoformat(),
                category=self.DIR_REPORTS,
                metadata={"report_type": report_type}
            )
            
            self._update_stats(stored_file)
            
            logger.info(f"保存报告: {filepath}")
            return stored_file
            
        except Exception as e:
            logger.error(f"保存报告失败 ({report_name}): {e}")
            logger.debug(get_err_message())
            return None
    
    def save_state(self, state_name: str, state_data: Dict[str, Any]) -> Optional[Path]:
        """
        保存状态数据 (用于检查点)
        
        Args:
            state_name: 状态名称
            state_data: 状态数据字典
            
        Returns:
            保存的文件路径
        """
        filename = f"{FileNamingHelper.sanitize(state_name)}.json"
        filepath = self.state_dir / filename
        
        try:
            state_with_meta = {
                "saved_at": datetime.now().isoformat(),
                **state_data
            }
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(state_with_meta, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"保存状态: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"保存状态失败 ({state_name}): {e}")
            logger.debug(get_err_message())
            return None
    
    def load_state(self, state_name: str) -> Optional[Dict[str, Any]]:
        """
        加载状态数据
        
        Args:
            state_name: 状态名称
            
        Returns:
            状态数据字典
        """
        filename = f"{FileNamingHelper.sanitize(state_name)}.json"
        filepath = self.state_dir / filename
        
        if not filepath.exists():
            logger.warning(f"状态文件不存在: {filepath}")
            return None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
                
        except Exception as e:
            logger.error(f"加载状态失败 ({state_name}): {e}")
            logger.debug(get_err_message())
            return None
    
    def save_json(
        self,
        data: Dict[str, Any],
        filename: str,
        subdir: str = ""
    ) -> Optional[Path]:
        """
        保存JSON数据到指定子目录
        
        通用的JSON保存方法,用于灵活保存各种数据
        
        Args:
            data: 要保存的数据字典
            filename: 文件名
            subdir: 子目录名 (可选)
            
        Returns:
            保存的文件路径
        """
        # 确定目标目录
        if subdir:
            target_dir = self.base_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = self.base_dir
        
        # 确保文件名以.json结尾
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        
        filepath = target_dir / filename
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"保存JSON: {filepath}")
            self._stats.files_saved += 1
            return filepath
            
        except Exception as e:
            logger.error(f"保存JSON失败 ({filename}): {e}")
            logger.debug(get_err_message())
            return None
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _generate_filename(
        self,
        url: str,
        content: str,
        extension: str
    ) -> str:
        """
        生成文件名
        
        Args:
            url: URL
            content: 内容
            extension: 扩展名
            
        Returns:
            文件名
        """
        # 优先使用LLM命名器
        if self.file_namer:
            try:
                name = self.file_namer.generate_name(url, content[:500])
                if name:
                    return FileNamingHelper.with_hash(name, content, extension)
            except Exception as e:
                logger.debug(f"LLM命名失败，使用规则命名: {e}")
        
        # 回退到基于URL的命名
        base_name = FileNamingHelper.from_url(url)
        return FileNamingHelper.with_hash(base_name, content, extension)
    
    def _ensure_unique_path(self, filepath: Path) -> Path:
        """
        确保文件路径唯一 (添加数字后缀)
        
        Args:
            filepath: 原始路径
            
        Returns:
            唯一的路径
        """
        if not filepath.exists():
            return filepath
        
        stem = filepath.stem
        suffix = filepath.suffix
        parent = filepath.parent
        
        counter = 1
        while True:
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1
    
    def _update_stats(self, stored_file: StoredFile):
        """更新统计信息"""
        self._stats.total_files += 1
        self._stats.total_size_bytes += stored_file.size_bytes
        
        category = stored_file.category
        self._stats.files_by_category[category] = \
            self._stats.files_by_category.get(category, 0) + 1
        self._stats.size_by_category[category] = \
            self._stats.size_by_category.get(category, 0) + stored_file.size_bytes
    
    # ========================================================================
    # 查询方法
    # ========================================================================
    
    def get_file_by_url(self, url: str) -> Optional[StoredFile]:
        """根据URL获取存储的文件信息"""
        return self._file_index.get(url)
    
    def list_files(
        self,
        category: Optional[str] = None,
        limit: int = 100
    ) -> List[StoredFile]:
        """
        列出存储的文件
        
        Args:
            category: 可选的分类过滤
            limit: 最大返回数量
            
        Returns:
            文件列表
        """
        files = list(self._file_index.values())
        
        if category:
            files = [f for f in files if f.category == category]
        
        # 按创建时间排序 (最新的在前)
        files.sort(key=lambda x: x.created_at, reverse=True)
        
        return files[:limit]
    
    def get_stats(self) -> StorageStats:
        """获取存储统计信息"""
        return self._stats
    
    def get_directory_size(self, directory: Path) -> int:
        """
        获取目录总大小 (字节)
        
        Args:
            directory: 目录路径
            
        Returns:
            总大小
        """
        total = 0
        try:
            for item in directory.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
        except Exception as e:
            logger.error(f"计算目录大小失败: {e}")
        return total
    
    # ========================================================================
    # 清理方法
    # ========================================================================
    
    def clean_category(self, category: str, older_than_days: int = 7) -> int:
        """
        清理指定分类的旧文件
        
        Args:
            category: 分类名称
            older_than_days: 删除多少天前的文件
            
        Returns:
            删除的文件数量
        """
        dir_map = {
            self.DIR_RAW: self.raw_dir,
            self.DIR_PROCESSED: self.processed_dir,
            self.DIR_ANALYSIS: self.analysis_dir,
            self.DIR_REPORTS: self.reports_dir
        }
        
        target_dir = dir_map.get(category)
        if not target_dir or not target_dir.exists():
            logger.warning(f"无效的分类或目录不存在: {category}")
            return 0
        
        import time
        cutoff_time = time.time() - (older_than_days * 24 * 60 * 60)
        deleted_count = 0
        
        try:
            for filepath in target_dir.iterdir():
                if filepath.is_file() and filepath.stat().st_mtime < cutoff_time:
                    filepath.unlink()
                    deleted_count += 1
                    logger.debug(f"删除旧文件: {filepath}")
            
            logger.info(f"清理完成: 删除 {deleted_count} 个文件 (分类: {category})")
            
        except Exception as e:
            logger.error(f"清理失败: {e}")
            logger.debug(get_err_message())
        
        return deleted_count
    
    def clean_all(self, confirm: bool = False) -> bool:
        """
        清空所有存储
        
        Args:
            confirm: 确认删除
            
        Returns:
            是否成功
        """
        if not confirm:
            logger.warning("清空存储需要确认 (confirm=True)")
            return False
        
        try:
            # 删除并重建目录
            if self.base_dir.exists():
                shutil.rmtree(self.base_dir)
            
            # 重新初始化
            self._init_directories()
            
            # 清空索引和统计
            self._file_index.clear()
            self._deduplicator.clear()
            self._stats = StorageStats()
            
            logger.info("存储已清空")
            return True
            
        except Exception as e:
            logger.error(f"清空存储失败: {e}")
            logger.debug(get_err_message())
            return False
    
    # ========================================================================
    # 导出方法
    # ========================================================================
    
    def export_index(self, filepath: Optional[Path] = None) -> Path:
        """
        导出文件索引
        
        Args:
            filepath: 可选的输出路径
            
        Returns:
            导出的文件路径
        """
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self.state_dir / f"file_index_{timestamp}.json"
        
        index_data = {
            "exported_at": datetime.now().isoformat(),
            "stats": self._stats.to_dict(),
            "files": [f.to_dict() for f in self._file_index.values()]
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"导出文件索引: {filepath}")
        return filepath
    
    # ========================================================================
    # 调试和显示
    # ========================================================================
    
    def print_status(self):
        """打印存储状态"""
        stats = self.get_stats()
        
        print("\n" + "=" * 50)
        print("存储管理器状态")
        print("=" * 50)
        print(f"基础目录: {self.base_dir}")
        print(f"总文件数: {stats.total_files}")
        print(f"总大小: {stats.total_size_bytes / (1024*1024):.2f} MB")
        print(f"重复跳过: {stats.duplicates_skipped}")
        print("\n分类统计:")
        for category, count in stats.files_by_category.items():
            size_mb = stats.size_by_category.get(category, 0) / (1024*1024)
            print(f"  {category}: {count} 个文件, {size_mb:.2f} MB")
        print("=" * 50 + "\n")


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    """测试存储管理器"""
    from config import Config
    
    print("=" * 60)
    print("存储管理器测试")
    print("=" * 60)
    
    # 创建配置
    config = Config()
    
    # 创建存储管理器
    storage = StorageManager(config)
    
    # 测试保存原始HTML
    print("\n--- 测试保存原始HTML ---")
    html_content = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Stanford University</h1>
        <p>Welcome to Stanford.</p>
    </body>
    </html>
    """
    result = storage.save_raw_html(
        url="https://www.stanford.edu/",
        html_content=html_content
    )
    print(f"  保存结果: {result}")
    
    # 测试重复检测
    print("\n--- 测试重复检测 ---")
    result2 = storage.save_raw_html(
        url="https://www.stanford.edu/duplicate",
        html_content=html_content
    )
    print(f"  重复保存结果: {result2}")
    
    # 测试保存处理内容
    print("\n--- 测试保存处理内容 ---")
    processed_content = {
        "title": "Stanford University",
        "text": "Welcome to Stanford.",
        "links": ["https://stanford.edu/admissions", "https://stanford.edu/research"]
    }
    result3 = storage.save_processed_content(
        url="https://www.stanford.edu/",
        content=processed_content
    )
    print(f"  处理内容保存结果: {result3}")
    
    # 测试保存分析结果
    print("\n--- 测试保存分析结果 ---")
    analysis_result = {
        "relevance_score": 0.85,
        "key_findings": ["Top university", "Located in California"],
        "prioritized_urls": [
            {"url": "https://stanford.edu/admissions", "priority": 1}
        ]
    }
    result4 = storage.save_analysis_result(
        url="https://www.stanford.edu/",
        analysis=analysis_result
    )
    print(f"  分析结果保存结果: {result4}")
    
    # 测试保存报告
    print("\n--- 测试保存报告 ---")
    report_content = """
# Stanford Crawl Report

## Summary
- Pages crawled: 10
- Relevant pages: 7

## Details
...
    """
    result5 = storage.save_report(
        report_name="stanford_crawl_report",
        content=report_content
    )
    print(f"  报告保存结果: {result5}")
    
    # 测试保存和加载状态
    print("\n--- 测试状态持久化 ---")
    state_data = {
        "crawl_progress": 50,
        "last_url": "https://stanford.edu/admissions"
    }
    storage.save_state("crawl_checkpoint", state_data)
    loaded_state = storage.load_state("crawl_checkpoint")
    print(f"  加载的状态: {loaded_state}")
    
    # 测试文件命名辅助器
    print("\n--- 测试文件命名 ---")
    print(f"  sanitize('Hello World!'): {FileNamingHelper.sanitize('Hello World!')}")
    print(f"  from_url('https://stanford.edu/admissions/graduate'): "
          f"{FileNamingHelper.from_url('https://stanford.edu/admissions/graduate')}")
    print(f"  with_timestamp('report'): {FileNamingHelper.with_timestamp('report', 'md')}")
    
    # 打印状态
    print("\n--- 存储状态 ---")
    storage.print_status()
    
    # 导出索引
    print("\n--- 导出索引 ---")
    index_path = storage.export_index()
    print(f"  索引导出到: {index_path}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)