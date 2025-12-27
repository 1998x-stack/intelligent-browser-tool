# 项目结构说明

## 📁 完整文件列表

```
intelligent-browser-tool/
│
├── 📄 main.py                    # 主入口文件和爬取流程
├── 📄 config.py                  # 配置管理
├── 📄 browser_engine.py          # Selenium浏览器引擎
├── 📄 content_processor.py       # Trafilatura内容处理器
├── 📄 ai_analyzer.py             # Ollama AI分析器
│
├── 📄 requirements.txt           # Python依赖列表
├── 📄 README.md                  # 项目说明文档
├── 📄 PROJECT_STRUCTURE.md       # 本文件
│
├── 📄 example_usage.py           # 使用示例脚本
├── 📄 test_components.py         # 组件测试脚本
│
├── 📁 .cache/                    # 缓存目录(自动创建)
├── 📁 logs/                      # 日志目录(可选)
└── 📄 browser_tool.log           # 主日志文件
```

## 📋 核心文件详解

### 1. main.py (主入口)
**功能**: 整个系统的入口点和主要爬取逻辑

**关键函数**:
- `main()`: 命令行入口,解析参数
- `crawl_website()`: 核心爬取流程,包含5个步骤:
  1. 使用Selenium获取页面
  2. 使用Trafilatura提取内容
  3. 使用0.5b模型分类
  4. 使用4b模型深度提取
  5. 使用4b模型提取下一个URL
- `setup_logging()`: 配置日志系统
- `save_results()`: 保存结果到JSON

**设计特点**:
- 参考CleanRL,将主要逻辑放在单个函数中
- 使用全局变量 `VISITED_URLS` 和 `EXTRACTED_DATA`
- 清晰的步骤注释和日志

---

### 2. config.py (配置管理)
**功能**: 集中管理所有配置参数

**主要类**:
- `Config`: 主配置类,使用dataclass
  - Ollama配置 (模型、地址)
  - Selenium配置 (浏览器、超时)
  - Trafilatura配置 (提取选项)
  - AI分析配置 (分类阈值)
  - URL过滤配置 (白名单、黑名单)

**预定义配置**:
- `get_stanford_config()`: Stanford专用
- `get_fast_config()`: 快速测试模式
- `get_deep_config()`: 深度分析模式

**设计特点**:
- 使用dataclass减少样板代码
- 提供合理的默认值
- 包含配置验证

---

### 3. browser_engine.py (浏览器引擎)
**功能**: 封装Selenium,提供简单的页面获取接口

**主要类**:
- `BrowserEngine`: 浏览器控制类

**关键方法**:
- `fetch_page()`: 获取页面HTML
- `_scroll_page()`: 滚动触发懒加载
- `_is_valid_url()`: URL验证
- `click_element()`: 点击元素
- `take_screenshot()`: 截图

**特性**:
- 自动下载和管理ChromeDriver
- 反爬虫检测规避
- 智能等待页面加载
- 支持无头模式

---

### 4. content_processor.py (内容处理器)
**功能**: 使用Trafilatura提取和处理网页内容

**主要类**:
- `ContentProcessor`: 内容处理类

**关键方法**:
- `extract_content()`: 主要提取函数
- `_extract_links()`: 提取所有链接
- `_chunk_text()`: 文本分块
- `_classify_link()`: 链接分类
- `extract_metadata_only()`: 仅提取元数据

**输出结构**:
```python
{
    'title': '标题',
    'text': '主要文本',
    'author': '作者',
    'date': '日期',
    'links': [{'url': '...', 'text': '...', 'type': '...'}],
    'chunks': [...],  # 如果文本太长
    'stats': {...}
}
```

---

### 5. ai_analyzer.py (AI分析器)
**功能**: 使用Ollama模型进行智能分析

**主要类**:
- `AIAnalyzer`: AI分析类

**三大核心功能**:

#### 1) 页面分类 (0.5b模型)
```python
classify_page(title, text_preview) -> {
    'category': '类别',
    'confidence': 0.85,
    'should_extract': True,
    'reasoning': '理由'
}
```

#### 2) 核心信息提取 (4b模型)
```python
extract_core_info(title, content, metadata) -> {
    'summary': '摘要',
    'key_points': [...],
    'entities': {...},
    'keywords': [...],
    'topics': [...]
}
```

#### 3) URL推荐 (4b模型)
```python
extract_next_urls(url, content, links) -> [
    'url1', 'url2', ...
]
```

**Prompt设计**:
- 所有Prompt都要求JSON输出
- 使用system和user分离
- 低温度保证稳定性

---

## 🔄 数据流图

```
┌─────────────┐
│ 起始URL     │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ Selenium            │
│ browser_engine.py   │
│ - 获取HTML          │
│ - 处理JavaScript    │
└──────┬──────────────┘
       │ HTML
       ▼
┌─────────────────────┐
│ Trafilatura         │
│ content_processor.py│
│ - 提取主要内容      │
│ - 提取链接          │
│ - 提取元数据        │
└──────┬──────────────┘
       │ 结构化内容
       ▼
┌─────────────────────┐
│ 0.5b 模型           │
│ ai_analyzer.py      │
│ - 快速分类          │
│ - 意图判断          │
└──────┬──────────────┘
       │ 分类结果
       ▼
    是否深度提取?
       │
       ├─Yes─────────────┐
       │                 ▼
       │          ┌─────────────────────┐
       │          │ 4b 模型             │
       │          │ ai_analyzer.py      │
       │          │ - 核心信息提取      │
       │          │ - 结构化数据        │
       │          └──────┬──────────────┘
       │                 │
       ▼                 ▼
┌─────────────────────────────┐
│ 4b 模型                     │
│ ai_analyzer.py              │
│ - 分析所有链接              │
│ - 推荐下一个URL             │
└──────┬──────────────────────┘
       │ URL列表
       ▼
  添加到爬取队列
       │
       ▼
  继续爬取 or 结束
```

---

## 🛠️ 辅助文件说明

### example_usage.py
**6个使用示例**:
1. 基础使用
2. Stanford配置
3. 快速模式
4. 自定义分类
5. 结果分析
6. 单页面分析

### test_components.py
**6个测试**:
1. 依赖包检查
2. Ollama连接测试
3. 浏览器引擎测试
4. 内容处理器测试
5. AI分析器测试
6. 完整流程测试

---

## 📦 依赖关系

```
main.py
  ├── config.py
  ├── browser_engine.py
  │     └── config.py
  │     └── selenium
  ├── content_processor.py
  │     └── config.py
  │     └── trafilatura
  └── ai_analyzer.py
        └── config.py
        └── requests (调用Ollama)
```

---

## 🎯 设计原则

本项目遵循 **CleanRL** 的设计哲学:

### 1. 单文件自包含
每个模块都是独立的,包含所有必要的逻辑:
- `browser_engine.py`: 完整的浏览器控制
- `content_processor.py`: 完整的内容提取
- `ai_analyzer.py`: 完整的AI分析

### 2. 透明的处理流程
- 在 `main.py` 的 `crawl_website()` 中可以看到所有步骤
- 每个步骤都有清晰的注释
- 详细的日志输出

### 3. 最小化抽象
- 避免过度封装
- 使用简单的数据结构(dict, list)
- 直接的函数调用

### 4. 便于调试
- 使用全局变量存储状态
- 详细的日志记录
- 清晰的错误处理

---

## 🚀 快速开始流程

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装Ollama和模型
ollama pull qwen3:1.7b
ollama pull qwen3:1.7b

# 3. 运行测试
python test_components.py

# 4. 查看示例
python example_usage.py

# 5. 运行主程序
python main.py --url https://www.stanford.edu --max-pages 10
```

---

## 📝 扩展指南

### 添加新的浏览器
在 `browser_engine.py` 中添加:
```python
def _init_firefox_driver(self):
    # 新浏览器初始化逻辑
    pass
```

### 添加新的页面类别
在 `config.py` 中修改:
```python
page_categories = [
    "existing_category",
    "new_category",  # 新类别
]
```

### 修改AI Prompt
在 `ai_analyzer.py` 中找到对应的 `_get_*_prompt()` 方法并修改

### 更换AI模型
在 `config.py` 中修改:
```python
small_model = "gemma:2b"
large_model = "llama3:8b"
```

---

## 📊 性能优化建议

1. **使用无头模式**: `--headless`
2. **限制页面数**: `--max-pages 20`
3. **调整请求间隔**: 修改 `config.request_delay`
4. **使用缓存**: 启用 `config.enable_cache`
5. **减少文本长度**: 调整 `config.max_text_length`

---

## 🐛 故障排查

### Ollama连接失败
```bash
# 检查服务
curl http://localhost:11434/api/tags
```

### ChromeDriver不兼容
```bash
# 清除缓存,重新下载
rm -rf ~/.wdm
```

### 内存占用过高
```python
# 减小配置参数
max_text_length = 5000
max_pages = 10
```

---

**最后更新**: 2024-12
**维护者**: 项目作者