"""
文件命名器模块 - 使用LLM生成智能文件名

设计理念 (CleanRL哲学):
- 单文件自包含: 命名逻辑独立完整
- 透明的处理流程: 命名规则清晰
- 最小化抽象: 直接的LLM调用
- 便于调试: 命名过程可追踪

功能:
- 使用 qwen3:0.6b 快速生成语义化文件名
- 支持多种内容类型
- 保证文件名合法性
"""

import re
import hashlib
from typing import Optional
from datetime import datetime

from loguru import logger

from llm_client import LLMClient
from utils import extract_json_from_text, truncate_text


# ============================================================================
# Prompt模板
# ============================================================================

FILE_NAMING_PROMPT = """/no_think
为以下内容生成简短的文件名。

内容类型: {content_type}
标题: {title}
摘要: {summary}

要求:
1. 文件名3-6个英文单词，用下划线连接
2. 简洁但能反映内容主题
3. 不包含特殊字符
4. 全小写

输出JSON: {{"filename": "suggested_filename"}}
只输出JSON。"""


# ============================================================================
# 文件命名器类
# ============================================================================

class FileNamer:
    """
    文件命名器 - 使用LLM生成语义化文件名
    
    使用方式:
        namer = FileNamer(llm_client)
        name = namer.generate_name(title, summary, content_type)
        print(name)  # stanford_admission_requirements
    """
    
    def __init__(self, llm_client: LLMClient):
        """
        初始化文件命名器
        
        Args:
            llm_client: LLM客户端实例
        """
        self.llm_client = llm_client
        logger.info("文件命名器初始化完成")
    
    def generate_name(
        self,
        title: str,
        summary: str = "",
        content_type: str = "webpage",
        use_llm: bool = True
    ) -> str:
        """
        生成文件名
        
        Args:
            title: 内容标题
            summary: 内容摘要
            content_type: 内容类型
            use_llm: 是否使用LLM (False则使用规则)
            
        Returns:
            生成的文件名 (不含扩展名)
        """
        if use_llm:
            name = self._llm_generate_name(title, summary, content_type)
            if name:
                return name
        
        # 回退到规则生成
        return self._rule_based_name(title)
    
    def _llm_generate_name(
        self,
        title: str,
        summary: str,
        content_type: str
    ) -> Optional[str]:
        """
        使用LLM生成文件名
        
        Args:
            title: 标题
            summary: 摘要
            content_type: 内容类型
            
        Returns:
            生成的文件名
        """
        prompt = FILE_NAMING_PROMPT.format(
            content_type=content_type,
            title=title[:100],
            summary=summary[:200]
        )
        
        response = self.llm_client.fast_generate(prompt)
        
        if not response.success:
            logger.debug("LLM命名失败，使用规则生成")
            return None
        
        try:
            result = extract_json_from_text(response.content)
            if result and 'filename' in result:
                name = result['filename']
                # 验证和清理
                name = self._sanitize_filename(name)
                if name:
                    logger.debug(f"LLM生成文件名: {name}")
                    return name
        except Exception as e:
            logger.debug(f"解析LLM响应失败: {e}")
        
        return None
    
    def _rule_based_name(self, title: str) -> str:
        """
        基于规则生成文件名
        
        Args:
            title: 标题
            
        Returns:
            生成的文件名
        """
        # 清理标题
        name = title.lower()
        
        # 移除特殊字符
        name = re.sub(r'[^a-z0-9\s\u4e00-\u9fff]', ' ', name)
        
        # 处理中文 - 转为拼音或哈希
        if re.search(r'[\u4e00-\u9fff]', name):
            # 简单处理：提取英文部分 + 哈希
            english_parts = re.findall(r'[a-z]+', name)
            if english_parts:
                name = '_'.join(english_parts[:4])
            else:
                # 无英文，使用哈希
                name = f"page_{hashlib.md5(title.encode()).hexdigest()[:8]}"
        else:
            # 纯英文
            words = name.split()
            # 取前4-6个有意义的词
            words = [w for w in words if len(w) > 2][:6]
            name = '_'.join(words) if words else f"page_{hashlib.md5(title.encode()).hexdigest()[:8]}"
        
        # 最终清理
        name = self._sanitize_filename(name)
        
        logger.debug(f"规则生成文件名: {name}")
        
        return name or f"unnamed_{datetime.now().strftime('%H%M%S')}"
    
    def _sanitize_filename(self, name: str) -> str:
        """
        清理文件名
        
        Args:
            name: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 转小写
        name = name.lower()
        
        # 只保留字母数字和下划线
        name = re.sub(r'[^a-z0-9_]', '_', name)
        
        # 合并多个下划线
        name = re.sub(r'_+', '_', name)
        
        # 去除首尾下划线
        name = name.strip('_')
        
        # 限制长度
        if len(name) > 50:
            name = name[:50].rstrip('_')
        
        return name
    
    def generate_unique_name(
        self,
        title: str,
        summary: str = "",
        content_type: str = "webpage",
        existing_names: set = None
    ) -> str:
        """
        生成唯一的文件名
        
        Args:
            title: 标题
            summary: 摘要
            content_type: 内容类型
            existing_names: 已存在的文件名集合
            
        Returns:
            唯一的文件名
        """
        base_name = self.generate_name(title, summary, content_type)
        
        if existing_names is None or base_name not in existing_names:
            return base_name
        
        # 添加数字后缀
        counter = 1
        while f"{base_name}_{counter}" in existing_names:
            counter += 1
        
        return f"{base_name}_{counter}"
    
    def generate_timestamped_name(
        self,
        title: str,
        summary: str = "",
        content_type: str = "webpage"
    ) -> str:
        """
        生成带时间戳的文件名
        
        Args:
            title: 标题
            summary: 摘要
            content_type: 内容类型
            
        Returns:
            带时间戳的文件名
        """
        base_name = self.generate_name(title, summary, content_type)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        return f"{base_name}_{timestamp}"


# ============================================================================
# 工厂函数
# ============================================================================

def create_file_namer(llm_client: LLMClient) -> FileNamer:
    """
    创建文件命名器实例
    
    Args:
        llm_client: LLM客户端
        
    Returns:
        FileNamer实例
    """
    return FileNamer(llm_client)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    from config import LLMConfig
    from llm_client import create_llm_client
    
    print("=" * 60)
    print("文件命名器模块测试")
    print("=" * 60)
    
    # 创建LLM客户端
    llm_config = LLMConfig()
    llm_client = create_llm_client(llm_config)
    
    # 创建命名器
    namer = create_file_namer(llm_client)
    
    # 测试用例
    test_cases = [
        {
            "title": "Stanford Admission Requirements 2024",
            "summary": "Undergraduate admission requirements including GPA and test scores",
            "content_type": "admission"
        },
        {
            "title": "斯坦福大学研究成果",
            "summary": "最新的人工智能研究进展",
            "content_type": "research"
        },
        {
            "title": "Contact Us - Stanford University",
            "summary": "Phone numbers and email addresses",
            "content_type": "contact"
        },
        {
            "title": "!!!Special @#$ Characters Test!!!",
            "summary": "Testing special character handling",
            "content_type": "test"
        },
    ]
    
    # 检查LLM连接
    use_llm = llm_client.check_connection()
    if not use_llm:
        print("无法连接Ollama，使用规则生成")
    
    print("\n--- 文件命名测试 ---")
    existing_names = set()
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n测试 {i}:")
        print(f"  标题: {case['title']}")
        
        # LLM生成
        if use_llm:
            llm_name = namer.generate_name(
                case['title'],
                case['summary'],
                case['content_type'],
                use_llm=True
            )
            print(f"  LLM生成: {llm_name}")
        
        # 规则生成
        rule_name = namer.generate_name(
            case['title'],
            case['summary'],
            case['content_type'],
            use_llm=False
        )
        print(f"  规则生成: {rule_name}")
        
        # 唯一名称
        unique_name = namer.generate_unique_name(
            case['title'],
            case['summary'],
            case['content_type'],
            existing_names
        )
        existing_names.add(unique_name)
        print(f"  唯一名称: {unique_name}")
        
        # 时间戳名称
        ts_name = namer.generate_timestamped_name(
            case['title'],
            case['summary'],
            case['content_type']
        )
        print(f"  时间戳名称: {ts_name}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
