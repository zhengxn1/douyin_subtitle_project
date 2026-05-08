# Architecture KB — 抖音字幕项目

## 已知缺陷模式

### [FIXED] Whisper FFmpeg FileNotFoundError on Windows
- **模式**: `FileNotFoundError: [WinError 2] 系统找不到指定的文件。` / `subprocess.run(["ffmpeg", ...])` fails
- **根因**: `os.environ["PATH"]` 在 Python 进程内修改，不传递给 `subprocess.Popen` 的 `CreateProcess` PATH 查找。在 Windows + Flask debug reloader 环境下尤为明显。
- **修复**: patch `whisper.audio.run` → 用 `imageio_ffmpeg.get_ffmpeg_exe()` 的绝对路径替换 `"ffmpeg"` 参数
- **涉及文件**: `backend/app.py` 第 27-34 行

### [FIXED] Flask debug reloader 导致 subprocess 环境丢失
- **模式**: Flask debug mode 默认 `use_reloader=True`，创建父子进程。子进程的 Python 代码 `import app` 时，`model.transcribe()` 在子进程内触发 FFmpeg subprocess，但子进程不继承父进程 Python 内存中的 `os.environ` 修改。
- **修复**: `app.run(..., use_reloader=False)`
- **涉及文件**: `backend/app.py` 第 179 行

## 架构陷阱与注意事项

1. **venv 路径**: venv 在项目根目录 `E:\vibecoding\douyin_subtitle_project\venv`，`backend/` 下无 venv。启动命令必须是 `cd project-root && .\venv\Scripts\python backend\app.py`
2. **sys.path 必须加 backend/**: Flask 从项目根目录启动时，`sys.path[0]` = 项目根目录，不含 `backend/`。**必须在 `backend/app.py` 顶部加 `sys.path.insert(0, os.path.dirname(__file__))`**，否则 `import config`、`from services.xhs_cookie_client` 全部报 `No module named`。
3. **config.py 相对路径**: `app.py` 用 `os.path.dirname(os.path.abspath(config.__file__))` 推导路径，依赖 `config.py` 在同一目录，不依赖 cwd
4. **上传文件清理**: `finally` 块负责删除临时 JSON 文件
5. **视频缓存**: 按 `aweme_id.mp4` 缓存，重复上传同一视频不会重新下载

## 数据流陷阱

- Tikhub API JSON 结构：可能是 `{aweme_detail: {...}}` 或 `{data: {aweme_detail: {...}}}`，必须两层都检查
- 视频 URL 有两种：`download_addr.url_list[0]` 和 `play_addr.url_list[0]`，前者优先

## 依赖说明

| 依赖 | 版本 | 来源 | 用途 |
|---|---|---|---|
| whisper | latest | pip | 语音转文字 |
| imageio-ffmpeg | latest | pip | FFmpeg 二进制 |
| flask + flask-cors | latest | pip | Web 服务 |
| jieba | latest | pip | 中文分词（标点插入） |
| openai | latest | pip | 翻译 API（GPT-4o-mini）|

## 新项目：内容二创工厂

- **规格文档**: `.ai/specs/content-factory-spec.md`
- **Phase 1**: 搭建脚手架 + 链接解析 + ASR + AI二创 + 剪辑（预计 2-3 周）

### 新架构关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 后端框架 | FastAPI | 异步任务 + SSE 原生支持 |
| 前端 | React + Vite + TailwindCSS | 组件化 + 开发效率 |
| LLM 调用 | LangChain + GPT-4o-mini | 知识库 RAG 工具链 |
| 向量化 | sentence-transformers | 本地零成本 |
| 数字人 | 抽象接口层 | 多平台可切换 |
| 视频剪辑 | FFmpeg | 本地零成本，控制粒度更细 |
| 数据库 | SQLite（初期）| 轻量，可迁移 PostgreSQL |

### 平台链接解析风险

| 平台 | 方案 | 风险 |
|---|---|---|
| YouTube/TikTok | TikHub API ✅ | 低 |
| 抖音 | TikHub API ✅ | 低 |
| 小红书 | Cookie + 自解析 HTML ✅ | 低 |
| 视频号/快手 | 导出本地文件手动上传 | 高 |

### 迁移注意事项

- 原 `backend/app.py` (Flask) 替换为 `backend/main.py` (FastAPI)
- 原 `frontend/index.html` 替换为 `frontend/src/` (React SPA)
- venv 路径不变：`E:\vibecoding\douyin_subtitle_project\venv`
- `uploads/` 目录继续作为共享存储

### TikHub API 集成（2026-04-25）

- **规格文档**: `.ai/specs/tikhub-integration-spec.md`
- **SDK 包名**: `tikhub`（PyPI），不是 `tikhub-sdk-v2`
- **SDK 初始化**: `TikHub(api_key="...")`，类名大写
- **模块路径**: `client.douyin_app_v3`（下划线，不是点）
- **Base URL**: `https://api.tikhub.io`（国内用 `api.tikhub.dev`）
- **关键端点**:
  - 抖音分享链接: `client.douyin_app_v3.fetch_one_video_by_share_url(share_url="...")`
  - 抖音直接 ID（v3）: `client.douyin_app_v3.fetch_one_video_v3(aweme_id="...")` — v1 端点已损坏（HTTP 400），优先用 v3
  - 抖音批量: `client.douyin_app_v3.fetch_multi_video(aweme_ids=[...])`
  - TikTok: `client.tiktok_app_v3.fetch_one_video_by_share_url_v2(share_url="...")`
- **视频URL优先级**: `download_addr.url_list[0]` > `play_addr.url_list[0]`（无水印 > 有水印）
- **API Key**: `no1fWNEN62e1xCvLF4KS8guOaByfarA96CKJlFSceaGXlk6tJFbcVS2APw==`
- **Scope**: 62 scopes（抖音/TikTok/小红书/YouTube 等 16+ 平台）

### TikHub API 各平台可用端点（2026-04-26）

**实测结论**（API Key: `no1fWNEN62e1xCvLF4KS8guOaByfarA96CKJlFSceaGXlk6tJFbcVS2APw==`）：

| 平台 | 方法 | 参数 | 状态 | 响应路径 |
|---|---|---|---|---|
| 抖音 | `fetch_one_video_v3` | `aweme_id=` | ✅ 可用 | `data.aweme_detail` |
| 抖音 | `fetch_one_video_v2` | `aweme_id=` | ✅ 可用 | `data.aweme_detail` |
| 抖音 | `fetch_one_video` | `aweme_id=` | ❌ HTTP 400 | - |
| 抖音 | `fetch_one_video_by_share_url` | `share_url=` | ✅ 可用 | `data.aweme_detail` |
| TikTok | `fetch_one_video_by_share_url_v2` | `share_url=` | ✅ 可用 | `data.aweme_detail` |
| TikTok | `fetch_one_video` | `aweme_id=` | ❌ 返回空 data | - |
| YouTube | `get_video_info_v2` | `video_id=` | ✅ 可用 | `data.streamingData` |
| YouTube | `get_video_info` / `v3` | `video_id=` | ❌ HTTP 402 | - |
| 小红书（app_v2）| `get_video_note_detail` | `note_id=`, `share_text=` | ❌ HTTP 400 | - |
| 小红书（web v2/v4/v7）| `get_note_info_*` | `note_id=`, `share_text=` | ❌ HTTP 402 | - |

**结论**：当前 API Key 有抖音/TikTok/YouTube 权限，**无小红书权限**（小红书 HTTP 400，抖音/TikTok/YouTube 均可正常调用）。

### 4链接批量测试实测（2026-04-26）

| 平台 | URL | detect_platform | ID提取 | API success | 视频URL HEAD | 文件大小 |
|------|-----|----------------|--------|-------------|--------------|---------|
| YouTube 短链 | `youtu.be/7f2q6tWbYQc` | youtube ✅ | 7f2q6tWbYQc ✅ | ✅ | 200 / 15MB ✅ | |
| YouTube 标准 | `youtube.com/watch?v=7f2q6tWbYQc` | youtube ✅ | 7f2q6tWbYQc ✅ | ✅ | 200 / 15MB ✅ | |
| TikTok | `tiktok.com/video/7630032792180526352` | tiktok ✅ | 7630032792180526352 ✅ | ✅ | 200 / 13MB ✅ | |
| 小红书 | `xiaohongshu.com/explore/...` | xiaohongshu ✅ | 69ea38ff... ✅ | ❌ HTTP 400 | - | API无权限 |

**YouTube 签名URL有效期**：TikHub 返回的 `googlevideo.com` 签名URL，当前测试有效（HEAD 200）。签名URL会随时间过期，需在获取后尽快下载。ASR 本身约需 60-80 秒，YouTube 视频较大，建议关注下载超时。

**上次77秒超时原因**：ASR 约 60-70 秒（Whisper base 模型转写）+ API 调用 5-10 秒 = 正常范围，非代码 bug。若单次 ASR 超 2 分钟需检查 FFmpeg 音频提取步骤。

### 抖音 TikHub 搜索 API 实测（2026-04-27）

**`douyin_search.fetch_experience_search`（综合搜索）**：
- 返回 `business_data[n].data.aweme_info`（视频详情 dict）✅
- `aweme_info` 结构：`aweme_id, desc, author{nickname,avatar_uri}, video{cover,duration}, statistics{play_count,digg_count,...}`
- 速度：~2.4s

**`douyin_search.fetch_challenge_search_v1`（话题搜索）**：
- 返回 `challenge_list[n].items` = aweme_dict（扁平，无 aweme_info 包裹）
- ⚠️ `items` 永远为空数组（实测 0 个视频），仅作备用
- 数据路径同综合搜索：`items[i].aweme_id`

**`douyin_app_v3.fetch_general_search_result`**：
- HTTP 403 "需要登录"，data.data 为空 → **废弃**

**性能优化**：两路并行（`ThreadPoolExecutor`），取并集去重，总耗时 ~2.4s（不等最慢）。

### 详情页 ASR 策略（2026-04-28）

**三 API 分工**：
- `/api/quick_parse`（新增）：快速查询，只调 TikHub API 取元数据，不下载不 ASR，< 1s
- `/api/parse_links`：完整解析（含下载 + ASR）
- `/api/video_detail` + `run_asr=false`（默认）：仅元数据，< 1s
- `/api/video_detail` + `run_asr=true`：下载 + ASR，60-80s

**前端交互**：
- 首页「查询」按钮 → 调 `/api/quick_parse` → 秒出结果到列表
- 点「详情」→ 用列表已有数据渲染，字幕区显示「点『生成字幕』提取文案」
- 点「生成字幕」→ `run_asr: true` → 60-80s 后展示字幕 + 视频

**关键设计**：`tikhub_client.py` 新增 `extract_metadata_from_response()` 统一归一化各平台元数据字段。

### 小红书 TikHub 搜索 API 实测（2026-04-27）

**`xiaohongshu_web_v3.fetch_search_notes`**：
- 偶发 HTTP 400 限速，重试 3 次可恢复
- 返回 `items[n].noteCard`（**camelCase 大写C**）
- `noteId` 在 **item 顶层**（不在 noteCard 内）
- `noteCard.user = {nickName, avatar}`（camelCase）
- `noteCard.interactInfo = {likedCount, collectedCount, commentCount, sharedCount}`（字符串数字）
- `noteCard.cover` = 字符串 URL（或 dict 嵌套）
- `noteCard.displayTitle` = 搜索专用标题
- 分享链接构造：`https://www.xiaohongshu.com/explore/{noteId}`
- 速度：1.8-2.4s（含重试）

### 小红书 XHS 获取（2026-04-27）

- TikHub API → HTTP 400（无权限）
- Cookie + HTML 解析 → `noteDetailMap.null.note = {}`（会话不一致，数据为空）
- **yt-dlp + Cookie** → ✅ 唯一可行方案（内部处理签名）
- 视频 URL 在 `formats[0].url`，Cookie 需 Netscape 格式临时文件

### 抖音 URL 类型与 API 调用策略（2026-04-26）

### 抖音 URL 类型与 API 调用策略（2026-04-26）

|| URL 类型 | 示例 | TikHub API |
|---|---|---|---|
|| 分享短链 | `https://v.douyin.com/xxx` | `fetch_one_video_by_share_url()` |
|| 视频页 | `https://www.douyin.com/video/7632320135316379749` | `fetch_one_video(aweme_id=)` |
|| 精选/搜索入口页 | `https://www.douyin.com/jingxuan?modal_id=7629300002552122664` | `fetch_one_video(aweme_id=)` |

- `extract_douyin_video_id()`：统一提取函数，支持短链 follow redirect、`/video/` 直接 ID、`modal_id` 参数三种情况
- 平台识别用域名级正则（`www\.douyin\.com`），不限制路径，不漏任何入口页
- URL 正则字符类 `[^\s\u4e00-\u9fff]*` 不含 `?`，查询参数被截断 → 前端改用通用 URL 正则兜底过滤

### [FIXED] URL 正则查询参数截断

- **模式**: `https://www.douyin.com/jingxuan?modal_id=xxx` 被识别为"未知平台"
- **根因**: 正则 `[^\s\u4e00-\u9fff]*` 不含 `?`，导致 `?` 后内容被截断；且重复检测点导致路径关键词表永远有漏洞
- **修复**:
  - 前端：通用 URL 正则 + `new URL().hostname` 过滤，不依赖路径关键词
  - 后端：`detect_platform()` 改用 `urlparse().hostname` 字符串包含判断，域名级识别
- **涉及文件**: `frontend/index.html`、`backend/services/tikhub_client.py`
- **架构原则**: URL 平台识别统一用 **hostname 包含判断**，永不依赖路径关键词

### [FIXED] YouTube 英文视频 ASR 语言错误

- **模式**: YouTube 英文视频传入后，`language="zh"` 导致 Whisper 强制中文识别，"hello" → "哈喽" 等大量错识别
- **根因**: `app.py` 和 `tikhub_client.py` 统一用 `language="zh"`，英文内容被强制中文化
- **修复**: Whisper 改为 `language=None`（自动检测音频语言）；返回 `detected_language` 字段
- **涉及文件**: `backend/app.py`、`backend/services/tikhub_client.py`
- **架构原则**: 不用平台判断语言，统一让 Whisper 自动检测，英文出英文、中文出中文
