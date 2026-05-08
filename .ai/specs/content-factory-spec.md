# 内容二创超级工厂 — 技术规格说明书

> **版本**: v1.0
> **日期**: 2026-04-25
> **架构师**: Claude (system-architect)
> **目标用户**: 内容创作者（个人 / MCN / 企业）

---

## 一、项目愿景与核心价值

**一句话定位**：
> 一站式 AI 短视频二创工具 — 输入链接，自动提取文案 → AI 二创 → 数字人录制 → 自动剪辑 → 多平台发布

**用户旅程**：
```
输入链接（多平台）
    → 提取文案（ASR/网页抓取）
    → AI 二创（知识库 + LLM）
    → 选择方案
    → 数字人录制（可选）
    → 剪辑模板
    → 多平台发布
```

---

## 二、系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户端 (Browser SPA)                     │
│   React + Vite + TailwindCSS + React Query + Zustand            │
└──────────┬──────────────────┬─────────────────┬─────────────────┘
           │                  │                 │
    ┌──────▼──────┐    ┌──────▼──────┐   ┌──────▼──────┐
    │  链接解析   │    │  AI 二创    │   │  剪辑合成   │
    │  服务       │    │  服务       │   │  服务       │
    │  (Python)   │    │  (Python)   │   │  (Python)   │
    └──────┬──────┘    └──────┬──────┘   └──────┬──────┘
           │                  │                 │
    ┌──────▼──────────────────▼─────────────────▼──────┐
    │               共享存储层 (本地 / 云 OSS)            │
    │   uploads/  │  scripts/  │  outputs/  │  kb/     │
    └──────────────────────────────────────────────────┘
           │                  │                 │
    ┌──────▼──────┐    ┌──────▼──────┐   ┌──────▼──────┐
    │  视频提取   │    │  LLM API   │   │  TTS/数字人  │
    │  (yt-dlp)   │    │  (OpenAI)  │   │  (三方服务)  │
    └─────────────┘    └────────────┘   └─────────────┘
```

---

## 三、技术栈

| 层级 | 技术选型 | 理由 |
|---|---|---|
| 前端 | React 18 + Vite 5 + TailwindCSS 3 | 组件化、开发效率高、生态成熟 |
| 状态管理 | Zustand | 轻量、比 Redux 好维护 |
| 数据请求 | React Query (TanStack Query) | 自动缓存 + 轮询 |
| 后端框架 | FastAPI (替换 Flask) | 异步、性能好、自动 OpenAPI 文档 |
| ASR/字幕 | Whisper (本地) + yt-dlp | 视频提取通用方案 |
| AI 二创 | LangChain + GPT-4o-mini / Claude Haiku | 知识库增强 |
| 数字人 | 硅基智能 / 腾讯智影 / 腾讯云 TI-ONE | 按需接入，抽象接口层 |
| 视频剪辑 | FFmpeg + MoviePy | 本地剪辑，零成本 |
| 存储 | 本地文件系统（uploads/）| 初期够用，后续迁 OSS |
| 数据库 | SQLite (轻量) / PostgreSQL (生产) | 记录任务状态 |
| 部署 | Docker + Docker Compose | 一键部署 |

---

## 四、支持的平台与链接解析

### 4.1 链接类型支持矩阵

| 平台 | 分享链接 | 网页链接 | 直接分享文本 | 视频下载 | 文案提取 |
|---|---|---|---|---|---|
| 抖音 | ✅ | ✅ | ✅ | ✅ (yt-dlp) | ✅ (Whisper ASR) |
| TikTok | ✅ | ✅ | ✅ | ✅ (yt-dlp) | ✅ (Whisper ASR) |
| 小红书 | ✅ | ✅ | ✅ | ✅ (网页抓取) | ✅ (文字+Whisper) |
| 微信视频号 | ❌ | ✅ | ❌ | ⚠️ (需模拟) | ✅ (Whisper ASR) |
| YouTube | ✅ | ✅ | ✅ | ✅ (yt-dlp) | ✅ (yt-dlp 字幕) |
| 快手 | ✅ | ✅ | ❌ | ⚠️ (需模拟) | ✅ (Whisper ASR) |

### 4.2 链接标准化

```python
# 链接解析路由
/link/parse  POST
Request:  { "url": "https://v.douyin.com/xxxxx" }
Response: {
    "platform": "douyin",
    "normalized_url": "https://www.douyin.com/video/123456",
    "video_id": "123456",
    "title": "视频标题",
    "thumbnail": "https://...",
    "status": "ready"
}
```

### 4.3 链接解析实现策略

```
分享链接文本
  → 检测平台类型（正则匹配）
  → 调用平台对应解析器：
    - 抖音/小红书 → TikHub API / 自建解析
    - YouTube/TikTok → yt-dlp -J 提取元信息
    - 视频号/快手 → 网页抓取 + 正则提取
  → 返回标准化结构
```

---

## 五、功能模块设计

### 5.1 模块总览

```
M1. 链接解析与视频提取
M2. 语音转文字（ASR）
M3. 知识库管理（KB）
M4. AI 二创引擎
M5. 数字人录制
M6. 剪辑合成
M7. 多平台发布
M8. 任务状态管理
```

---

### M1. 链接解析与视频提取

#### 数据模型

```python
class ExtractionTask(BaseModel):
    task_id: str          # UUID
    url: str              # 原始输入
    platform: Platform     # 枚举：douyin|tiktok|xiaohongshu|youtube|wechat|kuaishou
    video_id: str         # 平台视频ID
    status: TaskStatus    # pending|extracting|transcribing|done|failed
    video_path: str       # 本地视频路径
    transcript: str       # 原始转录文本
    punctuated_text: str  # 加标点文本
    created_at: datetime
    updated_at: datetime
```

#### API 路由

| 方法 | 路由 | 描述 |
|---|---|---|
| POST | `/api/tasks` | 创建提取任务（输入链接） |
| GET | `/api/tasks/{task_id}` | 查询任务状态 |
| GET | `/api/tasks/{task_id}/stream` | SSE 流式获取进度 |
| DELETE | `/api/tasks/{task_id}` | 删除任务 |

#### 提取流程（SSE 流式推送）

```
POST /api/tasks
  → 创建 task_id，写入 DB (status=pending)
  → 返回 task_id
  → 后台 worker 启动：
      [extracting]  yt-dlp 下载视频
      [transcribing]  Whisper ASR 转文字
      [punctuating]  jieba 标点插入
      [done]  完成
  → 前端通过 SSE /api/tasks/{id}/stream 实时接收状态
```

---

### M2. 语音转文字（ASR）

沿用现有 Whisper 实现，无需大改。

**关键参数**：
- 模型：`base`（默认）/ `small`（更高精度）
- 语言：`auto` 或显式指定 `zh`
- 输出：时间戳分段的 JSON

```python
result = model.transcribe(video_path, language='zh', task='transcribe')
# segments: [{'start': 0.0, 'end': 2.5, 'text': '今天天气很好'}]
```

---

### M3. 知识库管理

#### 核心概念

知识库 = 用户上传的参考文档集合，用于 AI 二创时提供背景知识。

#### 数据模型

```python
class KnowledgeBase(BaseModel):
    kb_id: str
    name: str
    description: str
    docs: list[Document]  # 分段后的文档

class Document(BaseModel):
    doc_id: str
    kb_id: str
    content: str          # 文本段落
    metadata: dict        # {"source": "filename.txt", "tags": []}
    embedding: list[float]  # 向量化向量（用于语义检索）
```

#### API

| 方法 | 路由 | 描述 |
|---|---|---|
| GET | `/api/kb` | 列出所有知识库 |
| POST | `/api/kb` | 创建知识库 |
| POST | `/api/kb/{kb_id}/docs` | 上传文档（txt/pdf/docx） |
| DELETE | `/api/kb/{kb_id}/docs/{doc_id}` | 删除文档 |
| POST | `/api/kb/{kb_id}/query` | 语义检索（返回相关段落） |

#### 向量化

使用 `sentence-transformers` (all-MiniLM-L6-v2) 本地向量化，不依赖 OpenAI Embedding API。

---

### M4. AI 二创引擎（核心模块）

#### 工作流程

```
输入：转录文本 + 知识库片段 + 用户指令
     ↓
1. 检索知识库（语义相似度 Top-K）
     ↓
2. 构建 Prompt（Few-shot）
     ↓
3. 调用 LLM（流式输出）
     ↓
4. 解析响应，生成多个方案
     ↓
5. 存储方案，返回前端展示
```

#### Prompt 设计

```python
SYSTEM_PROMPT = """
你是一位短视频文案专家，帮助用户将原始视频文案二创为适合多平台分发的版本。

规则：
1. 保留核心信息，改变表达方式
2. 前3秒必须有强钩子（悬念/冲突/数字/情绪）
3. 每15-30秒一个爆点
4. 结尾引导互动（评论/转发/关注）
5. 输出3个不同风格的版本

风格选项：
- 风格A：情感共鸣型（故事化、有温度）
- 风格B：知识干货型（实用价值感强）
- 风格C：娱乐型（轻松有趣、节奏快）

每次输出3个方案，每个方案包含：
- 标题（吸引眼球）
- 开场钩子（3秒）
- 正文（可读性强）
- 互动引导
"""

USER_PROMPT = """
【原始文案】
{transcript}

【参考知识】
{retrieved_context}

【用户指令】
{user_instruction}
"""
```

#### API

| 方法 | 路由 | 描述 |
|---|---|---|
| POST | `/api/rewrite` | 发起二创 |
| GET | `/api/rewrite/{rewrite_id}/versions` | 获取多个方案 |
| POST | `/api/rewrite/{rewrite_id}/versions/{version}/select` | 选择方案 |
| GET | `/api/rewrite/{rewrite_id}/stream` | SSE 流式接收生成过程 |

#### 请求/响应

```python
# POST /api/rewrite
Request: {
    "task_id": "uuid",
    "instruction": "改成更适合小红书的风格，注重实用价值",
    "style_preference": "干货型",  # 可选
    "platform": "xiaohongshu"  # 可选，影响输出格式
}

Response: {
    "rewrite_id": "uuid",
    "status": "streaming"
}

# SSE stream:
data: {"type": "context_retrieval", "content": "已检索相关知识库内容..."}
data: {"type": "generating", "content": "正在生成方案A..."}
data: {"type": "version", "index": 0, "data": {"title": "...", "body": "..."}}
data: {"type": "done", "versions_count": 3}
```

---

### M5. 数字人录制

#### 架构策略

**不绑定任何特定供应商**，抽象为统一接口：

```python
class DigitalHumanProvider(ABC):
    @abstractmethod
    def generate(self, script: str, avatar_id: str, **kwargs) -> str:
        """返回生成的视频文件路径"""
        pass

    @abstractmethod
    def list_avatars(self) -> list[Avatar]:
        """列出可用形象"""
        pass
```

#### 初始实现：腾讯智影 / 硅基智能（按需扩展）

```python
# 接入示例（腾讯智影 API）
class TencentZhiYingProvider(DigitalHumanProvider):
    def generate(self, script: str, avatar_id: str, **kwargs) -> str:
        # 调用腾讯智影 API
        # 返回视频文件路径
        pass
```

#### API

| 方法 | 路由 | 描述 |
|---|---|---|
| GET | `/api/avatars` | 列出可用数字人形象 |
| POST | `/api/digital-human/generate` | 生成数字人视频 |
| GET | `/api/digital-human/{task_id}/status` | 查询生成状态 |

#### 工作流

```
用户选择文案版本
  → 选择数字人形象
  → TTS 合成音频（如需）
  → 数字人口播视频生成
  → 返回视频路径
  → 进入剪辑模块
```

---

### M6. 剪辑合成

#### 剪辑模板系统

预定义多个剪辑模板：

| 模板名 | 适用场景 | 特点 |
|---|---|---|
| `standard` | 通用口播 | 字幕 + 片头片尾 |
| `shorts` | 短视频平台 | 快节奏、字幕大字 |
| `talk_show` | 对话/访谈 | 分栏字幕、双人对比 |
| `tutorial` | 知识干货 | 屏幕标注 + 字幕高亮 |
| `emotional` | 情感内容 | 慢节奏、背景音乐、滤镜 |

#### 模板数据结构

```python
class ClipTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    config: dict  # YAML 配置
```

#### 模板配置示例

```yaml
# templates/standard.yaml
name: "标准口播模板"
stages:
  - type: intro
    duration: 3
    overlay:
      - text: "{title}"
        font_size: 48
        position: center
        animation: fade_in
  - type: main_content
    subtitle:
      enabled: true
      font_size: 36
      position: bottom_center
      background: rgba(0,0,0,0.6)
      border_radius: 8
  - type: outro
    duration: 2
    overlay:
      - text: "关注我，获取更多干货"
        font_size: 36
        animation: slide_up
```

#### FFmpeg 剪辑管线

```
输入：原视频 / 数字人视频
  → 字幕烧录（ASS）
  → 片头合成（image + text overlay）
  → 片尾合成（subscribe CTA）
  → 背景音乐混音（可选）
  → 统一编码（H.264, 1080p）
  → 输出 MP4
```

---

### M7. 多平台发布

#### 发布目标平台

| 平台 | 状态 | API 方案 |
|---|---|---|
| 抖音 | ✅ | 抖音开放平台（需资质认证）|
| TikTok | ✅ | TikTok for Developers |
| 小红书 | ⚠️ | 开放平台（企业号可用）|
| 视频号 | ⚠️ | 视频号助手 API（企业）|
| YouTube | ✅ | YouTube Data API v3 |
| 快手 | ❌ | 暂不支持（API 封闭）|

#### 统一发布接口

```python
class Publisher(ABC):
    @abstractmethod
    def publish(self, video_path: str, title: str, description: str, **kwargs) -> PublishResult:
        pass

class DouyinPublisher(Publisher):
    def publish(self, video_path, title, description, **kwargs):
        # 调用抖音开放平台 API
        pass

class YouTubePublisher(Publisher):
    def publish(self, video_path, title, description, **kwargs):
        # 调用 YouTube Data API v3
        pass
```

#### API

| 方法 | 路由 | 描述 |
|---|---|---|
| POST | `/api/publish` | 一键发布到指定平台 |
| GET | `/api/publish/status/{publish_id}` | 查询发布状态 |

---

### M8. 任务状态管理

#### 数据库 Schema（SQLite → PostgreSQL）

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    video_path TEXT,
    transcript TEXT,
    punctuated_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE rewrites (
    rewrite_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(task_id),
    instruction TEXT,
    status TEXT DEFAULT 'pending',
    versions TEXT,  -- JSON array
    selected_version INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE publications (
    publish_id TEXT PRIMARY KEY,
    rewrite_id TEXT REFERENCES rewrites(rewrite_id),
    platform TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    external_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 六、前端页面结构

### 页面划分

```
/ (HomePage)
├── /workspace/:taskId  (工作台 — 主流程)
│   ├── Step 1: 链接输入
│   ├── Step 2: 文案提取结果
│   ├── Step 3: AI 二创（多版本选择）
│   ├── Step 4: 数字人录制（可选）
│   └── Step 5: 剪辑预览 + 发布
├── /knowledge (知识库管理)
│   ├── 知识库列表
│   └── 文档上传
└── /history (历史任务)
```

### 核心组件

```
App
├── Header (Logo + 导航)
├── LinkInputPanel (Step 1: 链接输入 + 平台识别)
├── ExtractionPanel (Step 2: 视频预览 + 原始文案)
├── RewritePanel (Step 3: AI 二创 + 多版本卡片)
├── DigitalHumanPanel (Step 4: 形象选择 + 预览)
├── ClipPanel (Step 5: 剪辑预览 + 模板选择)
├── PublishModal (发布弹窗)
└── KbManager (知识库管理)
```

---

## 七、文件目录结构

```
douyin_subtitle_project/   ← 项目根目录（git 仓库根）
│
├── frontend/              ← React SPA
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── HomePage.tsx
│   │   │   ├── WorkspacePage.tsx
│   │   │   ├── KnowledgeBasePage.tsx
│   │   │   └── HistoryPage.tsx
│   │   ├── components/
│   │   │   ├── LinkInput.tsx
│   │   │   ├── ExtractionView.tsx
│   │   │   ├── RewriteView.tsx
│   │   │   ├── DigitalHumanView.tsx
│   │   │   ├── ClipView.tsx
│   │   │   ├── PublishModal.tsx
│   │   │   └── ui/            # 通用 UI 组件
│   │   ├── hooks/
│   │   │   ├── useTask.ts
│   │   │   ├── useRewrite.ts
│   │   │   └── useSSE.ts
│   │   ├── store/
│   │   │   └── useAppStore.ts  # Zustand
│   │   ├── api/
│   │   │   └── client.ts       # Axios / fetch 封装
│   │   └── styles/
│   │       └── index.css
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── tsconfig.json
│
├── backend/              ← FastAPI 后端
│   ├── main.py           ← FastAPI 入口
│   ├── config.py
│   ├── requirements.txt
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── tasks.py      # 链接解析 + 视频提取
│   │   ├── rewrite.py    # AI 二创
│   │   ├── knowledge.py  # 知识库管理
│   │   ├── digital_human.py  # 数字人
│   │   ├── clip.py       # 剪辑合成
│   │   └── publish.py    # 多平台发布
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── extractor.py  # 视频提取（yt-dlp 封装）
│   │   ├── asr.py        # Whisper ASR
│   │   ├── punctuation.py  # 标点插入（复用）
│   │   ├── embedder.py   # 向量化
│   │   ├── retriever.py  # 知识库检索
│   │   ├── llm.py        # LLM 调用封装
│   │   ├── clipper.py    # FFmpeg 剪辑
│   │   └── publishers/   # 各平台发布器
│   │       ├── __init__.py
│   │       ├── douyin.py
│   │       ├── youtube.py
│   │       └── tiktok.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py   # SQLAlchemy models
│   │   └── schemas.py    # Pydantic schemas
│   │
│   └── workers/
│       ├── __init__.py
│       └── extraction_worker.py  # 后台任务 worker
│
├── uploads/              ← 共享存储
│   ├── videos/          ← 提取的视频
│   ├── audios/          ← TTS 音频
│   ├── avatars/        ← 数字人视频
│   ├── outputs/        ← 剪辑输出
│   └── kb/             ← 知识库文档
│
├── templates/           ← 剪辑模板 YAML
│   ├── standard.yaml
│   ├── shorts.yaml
│   ├── talk_show.yaml
│   ├── tutorial.yaml
│   └── emotional.yaml
│
├── .env.example         ← 环境变量模板
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
├── pyproject.toml
├── README.md
└── SPEC.md             ← 项目规格文档
```

---

## 八、API 完整路由表

| 方法 | 路由 | 描述 |
|---|---|---|
| POST | `/api/tasks` | 创建提取任务 |
| GET | `/api/tasks/{task_id}` | 查询任务 |
| GET | `/api/tasks/{task_id}/stream` | SSE 任务进度流 |
| DELETE | `/api/tasks/{task_id}` | 删除任务 |
| GET | `/api/tasks` | 列出所有任务（分页）|
| POST | `/api/rewrite` | 发起二创 |
| GET | `/api/rewrite/{id}` | 查询二创结果 |
| GET | `/api/rewrite/{id}/stream` | SSE 流式接收方案 |
| POST | `/api/rewrite/{id}/select` | 选择方案 |
| GET | `/api/kb` | 列出知识库 |
| POST | `/api/kb` | 创建知识库 |
| POST | `/api/kb/{kb_id}/docs` | 上传文档 |
| POST | `/api/kb/{kb_id}/query` | 语义检索 |
| GET | `/api/avatars` | 列出数字人形象 |
| POST | `/api/digital-human/generate` | 生成数字人视频 |
| GET | `/api/digital-human/{id}/status` | 查询数字人状态 |
| POST | `/api/clip` | 执行剪辑 |
| GET | `/api/clip/{id}/status` | 查询剪辑状态 |
| GET | `/api/clip/{id}/preview` | 预览剪辑结果 |
| POST | `/api/publish` | 发布到平台 |
| GET | `/api/publish/{id}/status` | 查询发布状态 |
| GET | `/api/templates` | 列出剪辑模板 |

---

## 九、环境变量配置

```bash
# .env.example

# LLM
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1  # 或代理地址

# 数字人（按需填写）
TENCENT_ZHIYING_API_KEY=
SILICON_AI_API_KEY=

# 平台发布（OAuth）
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=

# 数据库
DATABASE_URL=sqlite:///./data/app.db

# 存储
UPLOAD_DIR=./uploads
MAX_VIDEO_SIZE_MB=500

# ASR
WHISPER_MODEL=base
```

---

## 十、开发阶段规划

### Phase 1：核心链路（MVP）

- [ ] 项目脚手架搭建（FastAPI + React）
- [ ] 链接解析（yt-dlp，支持抖音/TikTok/YouTube）
- [ ] Whisper ASR（复用现有代码）
- [ ] 标点插入（复用现有代码）
- [ ] AI 二创（GPT-4o-mini，无知识库版本）
- [ ] 剪辑合成（FFmpeg + 标准模板）
- [ ] 基础前端（链路式工作台）

**预计工作量**：2-3 周

### Phase 2：数字人 + 高级功能

- [ ] 数字人接口抽象 + 腾讯智影接入
- [ ] TTS 合成
- [ ] 剪辑模板系统（YAML 可配置）
- [ ] 知识库（向量化 + 语义检索）
- [ ] 知识库增强的 AI 二创

**预计工作量**：2-3 周

### Phase 3：发布 + 平台化

- [ ] 多平台发布 API（YouTube 已确认）
- [ ] 任务历史 + 草稿管理
- [ ] 用户认证（多账号管理）
- [ ] Docker 部署

**预计工作量**：2 周

---

## 十一、全栈影响面分析

### 改动范围总结

| 层级 | 改动文件 | 新建文件 |
|---|---|---|
| **前端** | `frontend/index.html` → 重建为 React | `frontend/src/*` (完整 SPA) |
| **后端** | `backend/app.py` → 替换为 FastAPI | `backend/routers/`, `backend/services/` |
| **存储** | 共享 `uploads/` 目录 | `uploads/{videos,audios,avatars,outputs,kb}/` |
| **配置** | `.env.example` | `templates/*.yaml` |
| **部署** | — | `Dockerfile.*`, `docker-compose.yml` |

### 关键依赖关系

```
前端 LinkInput
  → POST /api/tasks → task_id
  → GET /api/tasks/{id}/stream (SSE)
  → GET /api/tasks/{id} (结果)

前端 RewritePanel
  → POST /api/rewrite {task_id, instruction}
  → GET /api/rewrite/{id}/stream (SSE)
  → POST /api/rewrite/{id}/select

前端 ClipPanel
  → POST /api/clip {rewrite_id, template_id}
  → GET /api/clip/{id}/preview

前端 PublishModal
  → POST /api/publish {clip_id, platform}
```

---

## 十二、技术决策记录

| 决策点 | 选项A（已选）| 选项B（放弃）| 理由 |
|---|---|---|---|
| 后端框架 | FastAPI | Flask | 异步任务 + SSE 原生支持，性能更好 |
| 前端框架 | React + Vite | 纯 HTML/JS | 项目复杂度需要组件化 |
| LLM 调用 | LangChain | 直接 OpenAI SDK | 知识库 RAG 需要工具链 |
| 向量化 | sentence-transformers | OpenAI Embedding | 本地化，零成本 |
| 数字人 | 抽象接口层 | 绑定单一供应商 | 支持多平台切换 |
| 视频剪辑 | FFmpeg | 云剪辑 API | 本地零成本，控制粒度更细 |
| 数据库 | SQLite（初期）| 直接文件 | 支持任务持久化 |
| 部署 | Docker Compose | 纯手动 | 一键启动 |

---

## 十三、已知风险

| 风险 | 概率 | 影响 | 缓解策略 |
|---|---|---|---|
| 抖音/小红书视频 URL 提取失败（签名墙）| 高 | 中 | TikHub 商业 API 兜底；定期更新解析逻辑 |
| 数字人 API 成本高 | 中 | 高 | 抽象接口，先接低成本方案（腾讯智影按量计费）|
| Whisper 本地推理慢（长视频）| 低 | 中 | 异步任务 + 进度反馈；可选 small 模型 |
| 多平台发布需要资质认证 | 高 | 低 | 先实现 YouTube（最开放），抖音走手动导出 |
| 视频号/快手 API 封闭 | 高 | 低 | 导出本地文件，手动上传 |

---

*文档版本：v1.0 | 状态：待评审*
