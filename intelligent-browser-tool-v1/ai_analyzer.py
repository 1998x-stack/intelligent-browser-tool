"""
AI分析器 - 使用Ollama进行智能内容分析

设计理念:
- 0.5b模型: 快速分类和意图判断
- 4b模型: 深度分析和结构化提取
- 精心设计的Prompt体系
- JSON格式输出便于解析
"""

import json
import re
from typing import Dict, List, Optional
import requests
from loguru import logger

from config import Config


class AIAnalyzer:
    """
    AI分析器 - 使用Ollama模型进行内容分析
    
    两阶段分析策略:
    1. 使用小模型(0.5b)快速分类
    2. 使用大模型(4b)深度提取
    """
    
    def __init__(self, config: Config):
        """
        初始化AI分析器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.ollama_url = f"{config.ollama_host}/api/generate"
        
        # 验证Ollama连接
        if not self._check_ollama_connection():
            logger.warning("无法连接到Ollama服务,请确保Ollama正在运行")
        
        logger.info(f"AI分析器初始化完成 (小模型: {config.small_model}, 大模型: {config.large_model})")
    
    def _check_ollama_connection(self) -> bool:
        """检查Ollama服务是否可用"""
        try:
            response = requests.get(f"{self.config.ollama_host}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _call_ollama(
        self, 
        prompt: str, 
        model: str, 
        system: Optional[str] = None,
        temperature: float = 0.1
    ) -> Optional[str]:
        """
        调用Ollama API
        
        Args:
            prompt: 提示词
            model: 模型名称
            system: 系统提示(可选)
            temperature: 温度参数
            
        Returns:
            模型响应文本
        """
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": 2000  # 最大生成token数
                }
            }
            
            if system:
                payload["system"] = system
            
            logger.debug(f"调用Ollama模型: {model}")
            
            response = requests.post(
                self.ollama_url,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '')
            else:
                logger.error(f"Ollama API错误: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Ollama API超时 (模型: {model})")
            return None
        except Exception as e:
            logger.error(f"调用Ollama时出错: {e}", exc_info=True)
            return None
    
    # ============ Phase 1: 使用小模型进行分类 ============
    
    def classify_page(self, title: str, text_preview: str) -> Dict:
        """
        使用0.5b模型对页面进行快速分类
        
        Args:
            title: 页面标题
            text_preview: 文本预览(前500字符)
            
        Returns:
            分类结果字典
        """
        system_prompt = self._get_classification_system_prompt()
        user_prompt = self._get_classification_user_prompt(title, text_preview)
        
        response = self._call_ollama(
            prompt=user_prompt,
            model=self.config.small_model,
            system=system_prompt,
            temperature=0.1  # 低温度保证稳定输出
        )
        
        if not response:
            return self._default_classification()
        
        # 解析JSON响应
        classification = self._parse_json_response(response)
        
        if not classification:
            return self._default_classification()
        
        # 验证和标准化
        category = classification.get('category', 'general_info')
        confidence = float(classification.get('confidence', 0.5))
        
        # 判断是否需要深度提取
        should_extract = (
            category in self.config.extract_categories and 
            confidence >= self.config.classification_confidence_threshold
        )
        
        return {
            'category': category,
            'confidence': confidence,
            'should_extract': should_extract,
            'reasoning': classification.get('reasoning', '')
        }
    
    def _get_classification_system_prompt(self) -> str:
        """获取分类任务的系统提示"""
        categories = ', '.join(self.config.page_categories)
        
        return f"""你是一个网页内容分类专家。你的任务是快速准确地判断网页的类别。

可用类别: {categories}

请严格按照以下JSON格式输出(不要有任何其他文字):
{{
    "category": "类别名称",
    "confidence": 0.0到1.0之间的数字,
    "reasoning": "简短的分类理由"
}}

注意:
1. category必须是上述类别之一
2. confidence表示你对分类的信心程度
3. 只输出JSON,不要有任何解释或额外文字"""
    
    def _get_classification_user_prompt(self, title: str, text_preview: str) -> str:
        """获取分类任务的用户提示"""
        return f"""请分类以下网页:

标题: {title}

内容预览:
{text_preview}

请输出JSON格式的分类结果。"""
    
    # ============ Phase 2: 使用大模型进行深度分析 ============
    
    def extract_core_info(
        self, 
        title: str, 
        content: str, 
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        使用4b模型提取核心信息
        
        Args:
            title: 页面标题
            content: 页面内容
            metadata: 元数据
            
        Returns:
            提取的核心信息
        """
        system_prompt = self._get_extraction_system_prompt()
        user_prompt = self._get_extraction_user_prompt(title, content, metadata)
        
        response = self._call_ollama(
            prompt=user_prompt,
            model=self.config.large_model,
            system=system_prompt,
            temperature=0.2  # 稍高温度增加创造性
        )
        
        if not response:
            return {'error': '提取失败'}
        
        # 解析JSON响应
        extracted = self._parse_json_response(response)
        
        return extracted if extracted else {'error': '解析失败', 'raw': response}
    
    def _get_extraction_system_prompt(self) -> str:
        """获取信息提取任务的系统提示"""
        return """你是一个信息提取专家,专门从学术网页中提取结构化信息。

你的任务:
1. 提取关键信息并组织成JSON格式
2. 生成简洁的摘要
3. 识别重要的实体(人名、机构、项目等)
4. 提取关键词

输出JSON格式(不要有其他文字):
{
    "summary": "简洁的摘要(2-3句话)",
    "key_points": ["要点1", "要点2", ...],
    "entities": {
        "people": ["人名1", "人名2", ...],
        "organizations": ["机构1", "机构2", ...],
        "projects": ["项目1", "项目2", ...]
    },
    "keywords": ["关键词1", "关键词2", ...],
    "topics": ["主题1", "主题2", ...],
    "contact_info": {
        "email": "邮箱",
        "phone": "电话",
        "address": "地址"
    }
}

注意:
- 只输出JSON,不要有解释
- 如果某个字段没有信息,使用空列表或null
- 保持简洁,避免冗余"""
    
    def _get_extraction_user_prompt(
        self, 
        title: str, 
        content: str, 
        metadata: Optional[Dict]
    ) -> str:
        """获取信息提取任务的用户提示"""
        # 限制内容长度
        max_length = 5000
        if len(content) > max_length:
            content = content[:max_length] + "..."
        
        prompt = f"""请从以下网页中提取核心信息:

标题: {title}

内容:
{content}
"""
        
        if metadata:
            prompt += f"\n\n元数据: {json.dumps(metadata, ensure_ascii=False)}"
        
        prompt += "\n\n请输出JSON格式的提取结果。"
        
        return prompt
    
    # ============ Phase 3: 使用大模型提取下一步URL ============
    
    def extract_next_urls(
        self, 
        current_url: str, 
        page_content: str, 
        links: List[Dict]
    ) -> List[str]:
        """
        使用4b模型分析并推荐下一步要访问的URL
        
        Args:
            current_url: 当前URL
            page_content: 页面内容
            links: 所有链接列表
            
        Returns:
            推荐访问的URL列表(按优先级排序)
        """
        # 如果链接太多,先做预过滤
        if len(links) > 50:
            links = self._prefilter_links(links)
        
        system_prompt = self._get_url_extraction_system_prompt()
        user_prompt = self._get_url_extraction_user_prompt(
            current_url, 
            page_content, 
            links
        )
        
        response = self._call_ollama(
            prompt=user_prompt,
            model=self.config.large_model,
            system=system_prompt,
            temperature=0.3
        )
        
        if not response:
            # 降级方案:返回类型为academic或research的链接
            return [link['url'] for link in links if link.get('type') in ['academic', 'research']][:10]
        
        # 解析JSON响应
        result = self._parse_json_response(response)
        
        if result and 'recommended_urls' in result:
            return result['recommended_urls'][:15]  # 最多返回15个
        
        # 降级方案
        return [link['url'] for link in links[:10]]
    
    def _get_url_extraction_system_prompt(self) -> str:
        """获取URL提取任务的系统提示"""
        return """你是一个网页导航专家,帮助用户发现有价值的链接。

你的任务:
1. 分析当前页面的内容和所有可用链接
2. 推荐最值得访问的链接
3. 按重要性排序

输出JSON格式(不要有其他文字):
{
    "recommended_urls": [
        "完整URL1",
        "完整URL2",
        ...
    ],
    "reasoning": "简短说明推荐理由"
}

优先推荐:
- 学术项目、研究成果页面
- 教职员工介绍页面
- 详细的课程/项目信息页面

避免推荐:
- 登录、搜索、地图等功能性页面
- 外部链接(除非特别重要)
- 重复的导航链接

注意:
- 只输出JSON
- 推荐5-15个URL
- URL必须完整,可以直接访问"""
    
    def _get_url_extraction_user_prompt(
        self, 
        current_url: str, 
        page_content: str, 
        links: List[Dict]
    ) -> str:
        """获取URL提取任务的用户提示"""
        # 限制内容长度
        content_preview = page_content[:1000] if page_content else ""
        
        # 格式化链接列表
        links_text = "\n".join([
            f"- {link['text'][:50]}: {link['url']}" 
            for link in links[:50]  # 最多显示50个
        ])
        
        return f"""当前页面: {current_url}

页面内容预览:
{content_preview}

可用链接:
{links_text}

请分析这些链接,推荐最值得深入访问的5-15个URL。输出JSON格式。"""
    
    # ============ 辅助方法 ============
    
    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """
        解析模型返回的JSON响应
        
        Args:
            response: 原始响应文本
            
        Returns:
            解析的字典,失败返回None
        """
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取JSON块
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"无法解析JSON响应: {response[:200]}")
        return None
    
    def _default_classification(self) -> Dict:
        """返回默认分类结果"""
        return {
            'category': 'general_info',
            'confidence': 0.5,
            'should_extract': False,
            'reasoning': '分类失败,使用默认值'
        }
    
    def _prefilter_links(self, links: List[Dict]) -> List[Dict]:
        """
        预过滤链接(基于规则)
        
        Args:
            links: 链接列表
            
        Returns:
            过滤后的链接列表
        """
        priority_types = ['academic', 'research', 'people']
        
        # 优先保留特定类型的链接
        priority_links = [l for l in links if l.get('type') in priority_types]
        other_links = [l for l in links if l.get('type') not in priority_types]
        
        # 组合:优先链接 + 其他链接的前20个
        return priority_links + other_links[:20]