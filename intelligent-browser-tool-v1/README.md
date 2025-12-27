# 智能浏览器工具

基于 **Ollama + Selenium + Trafilatura** 构建的智能网页分析系统,使用双模型策略进行高效的网页内容提取和分析。

## 🎯 核心特性

- **双模型AI分析**
  - 0.5b 模型:快速页面分类和意图判断
  - 4b 模型:深度内容分析和结构化信息提取

- **智能内容提取**
  - 使用 Trafilatura 精确提取网页主要内容
  - 自动分块处理长文本
  - 提取元数据、链接和关键信息

- **自动化浏览**
  - Selenium 驱动真实浏览器
  - 处理 JavaScript 渲染的动态内容
  - 反爬虫检测规避

- **精心设计的架构**
  - 参考 CleanRL 设计哲学
  - 代码清晰、易于理解和修改
  - 使用 Loguru 提供详细日志

## 📋 系统架构

```
智能浏览器工具/
├── main.py              # 主入口和爬取流程
├── config.py            # 配置管理
├── browser_engine.py    # Selenium 浏览器引擎
├── content_processor.py # Trafilatura 内容处理
├── ai_analyzer.py       # Ollama AI 分析器
├── requirements.txt     # 依赖列表
└── README.md           # 本文件
```

### 数据流

```
URL → Selenium获取HTML → Trafilatura提取内容 → 0.5b分类 → 4b深度分析 → JSON输出
                                                ↓
                                          4b推荐下一个URL
```

## 🚀 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境(推荐)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 安装和启动 Ollama

```bash
# 安装 Ollama (参考 https://ollama.ai)
# 下载所需模型
ollama pull qwen3:1.7b
ollama pull qwen3:1.7b

# 确保 Ollama 服务运行中
# 默认监听 http://localhost:11434
```

### 3. 安装浏览器驱动

程序会自动下载和管理 ChromeDriver,但确保已安装 Chrome 浏览器。

### 4. 运行示例

```bash
# 默认爬取 Stanford 大学官网
python main.py

# 自定义参数
python main.py \
    --url "https://www.stanford.edu" \
    --max-depth 2 \
    --max-pages 20 \
    --output results.json \
    --log-level INFO \
    --headless
```

## ⚙️ 配置说明

### 命令行参数

```
--url           起始URL (默认: https://www.stanford.edu)
--max-depth     最大爬取深度 (默认: 2)
--max-pages     最大页面数 (默认: 20)
--output        输出文件路径 (默认: results.json)
--log-level     日志级别 [DEBUG|INFO|WARNING|ERROR]
--headless      使用无头浏览器模式
```

### Config 类配置

在 `config.py` 中可以调整更多参数:

```python
config = Config(
    # Ollama 配置
    ollama_host="http://localhost:11434",
    small_model="qwen3:1.7b",
    large_model="qwen3:1.7b",
    
    # Selenium 配置
    headless=False,
    page_load_timeout=30,
    
    # Trafilatura 配置
    extract_comments=False,
    include_links=True,
    
    # AI 分析配置
    classification_confidence_threshold=0.6,
    page_categories=["academic_program", "research", ...],
    
    # URL 过滤
    allowed_domains=["stanford.edu"],
    exclude_patterns=["/login", ".pdf", ...]
)
```

## 📊 输出格式

结果保存为 JSON 文件,每个页面包含:

```json
{
  "url": "页面URL",
  "depth": "爬取深度",
  "classification": {
    "category": "页面类别",
    "confidence": "分类置信度",
    "should_extract": "是否深度提取",
    "reasoning": "分类理由"
  },
  "extracted_info": {
    "summary": "内容摘要",
    "key_points": ["要点1", "要点2"],
    "entities": {
      "people": ["人名"],
      "organizations": ["机构"],
      "projects": ["项目"]
    },
    "keywords": ["关键词"],
    "topics": ["主题"]
  },
  "metadata": {
    "title": "页面标题",
    "text": "提取的文本",
    "links": ["链接列表"]
  }
}
```

## 🎨 设计理念

本项目参考了 **CleanRL** 的设计哲学:

1. **单文件自包含** - 每个模块功能完整,易于理解
2. **透明的处理流程** - 所有步骤都清晰可见
3. **最小化抽象** - 避免过度封装,保持代码可读性
4. **便于调试** - 使用全局变量和详细日志

## 🔧 自定义和扩展

### 添加新的页面类别

在 `config.py` 中修改:

```python
page_categories = [
    "academic_program",
    "research",
    "your_new_category",  # 新类别
    ...
]
```

### 修改 Prompt

所有 Prompt 都在 `ai_analyzer.py` 中,可以根据需要调整:

```python
def _get_classification_system_prompt(self) -> str:
    return """你的自定义系统提示..."""
```

### 更换模型

支持任何 Ollama 兼容的模型:

```python
config = Config(
    small_model="gemma:2b",
    large_model="llama3:8b"
)
```

## 📝 日志说明

日志同时输出到:
- **控制台**: 彩色格式,INFO 级别及以上
- **文件**: `browser_tool.log`,详细的 DEBUG 信息

日志格式:
```
2024-01-20 10:30:45 | INFO     | main:crawl_website:123 - 开始爬取网站
```

## 🐛 常见问题

### Q: Ollama 连接失败
A: 确保 Ollama 服务正在运行:
```bash
# 测试连接
curl http://localhost:11434/api/tags
```

### Q: ChromeDriver 不兼容
A: 程序会自动下载匹配的驱动,确保网络连接正常

### Q: 提取内容为空
A: 检查网站是否有反爬虫措施,可以尝试:
- 降低爬取速度 (`request_delay`)
- 使用无头模式 (`--headless`)
- 调整 Trafilatura 参数

### Q: 内存占用过高
A: 调整以下参数:
```python
max_text_length = 5000  # 减小文本长度
max_pages = 10  # 限制页面数量
```

## 📚 参考资料

- [CleanRL](https://github.com/vwxyzjn/cleanrl) - 设计理念参考
- [Selenium Documentation](https://www.selenium.dev/documentation/)
- [Trafilatura](https://trafilatura.readthedocs.io/)
- [Ollama](https://ollama.ai/)

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

---

**Happy Scraping! 🚀**