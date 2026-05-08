# 技术契约与架构设计书：多平台链接解析 + TikHub API 集成

## 文档信息

| 字段 | 值 |
|---|---|
| 规格编号 | `tikhub-integration-spec.md` |
| 版本 | v1.0 |
| 日期 | 2026-04-25 |
| 状态 | 设计完成，待实现 |
| 关联 KB | `.ai/architecture-kb.md` |

---

## 一、需求概述

**目标**：在现有 Flask 后端（`backend/app.py`）基础上，新增多平台分享链接解析服务。用户可以直接粘贴抖音/小红书/TikTok/YouTube 分享链接，后端调用 TikHub API 获取视频信息，自动触发 ASR 转写流程。

**输入**：多平台分享链接（字符串）
**输出**：与现有 `/upload` 端点完全一致的数据结构（`video_url`, `segments`, `full_text`, `punctuated_text`, `original_desc`）

---

## 二、数据模型层（Schema）

### 2.1 请求体 Schema

```python
# backend/schemas.py（新建）

from pydantic import BaseModel, HttpUrl
from typing import Literal

class LinkParseRequest(BaseModel):
    links: list[str]                      # 分享链接列表
    platform: Literal["douyin", "tiktok", "xiaohongshu", "youtube", "auto"] = "auto"
```

### 2.2 响应体 Schema（与现有 `/upload` 一致）

```python
class VideoParseResult(BaseModel):
    """单个视频解析结果"""
    platform: str
    original_url: str
    aweme_id: str | None
    video_url: str                        # Flask 内部访问路径，如 /video/xxx.mp4
    local_path: str                       # 绝对路径
    segments: list[dict]                  # [{start, end, text}, ...]
    full_text: str
    punctuated_text: str
    original_desc: str
    title: str | None
    author: str | None
    download_status: Literal["success", "failed", "cached"]
    error: str | None = None

class LinkParseResponse(BaseModel):
    results: list[VideoParseResult]
    total: int
    success_count: int
    failed_count: int
```

### 2.3 平台识别正则

| 平台 | 正则模式 | 备注 |
|---|---|---|
| 抖音 | `v.douyin.com/` 或 `www.douyin.com/video/` | 短链或长链 |
| TikTok | `tiktok.com/t/` 或 `www.tiktok.com/@.*/video/` | 分享短链 |
| 小红书 | `www.xiaohongshu.com/explore/` 或 `xhslink.com/` | 短链或长链 |
| YouTube | `youtu.be/` 或 `www.youtube.com/watch?v=` | |
| auto | 依次匹配上述全部正则 | |

---

## 三、后端服务层（API）

### 3.1 新增端点

| 端点 | 方法 | 功能 |
|---|---|---|
| `/api/parse_links` | POST | 解析多平台链接，返回解析结果列表 |
| `/api/platforms` | GET | 返回支持的平台列表 |
| `/api/platform_hot` | GET | 获取指定平台热搜（douyin 支持，其他平台降级） |

### 3.2 路由设计

```
POST /api/parse_links
  Request Body: { "links": ["https://v.douyin.com/xxx", ...], "platform": "auto" }
  Response: LinkParseResponse
  内部流程:
    1. 识别平台
    2. 调用 TikHub API 获取视频元信息
    3. 提取视频下载 URL
    4. 下载视频到 uploads/
    5. 执行 Whisper ASR
    6. 返回标准化结果
```

### 3.3 TikHub SDK 调用契约

```python
# TikHub 初始化（单例模式，避免重复加载模型）
from tikhub import TikHub

_tikhub_client: TikHub | None = None

def get_tikhub_client(api_key: str) -> TikHub:
    global _tikhub_client
    if _tikhub_client is None:
        _tikhub_client = TikHub(api_key=api_key)
    return _tikhub_client

# 平台路由映射
PLATFORM_METHOD_MAP = {
    "douyin": {
        "by_share_url": lambda client, url: client.douyin_app_v3.fetch_one_video_by_share_url(share_url=url),
        "by_video_id":  lambda client, vid: client.douyin_app_v3.fetch_one_video(aweme_id=vid),
        "multi_fetch":   lambda client, ids: client.douyin_app_v3.fetch_multi_video(aweme_ids=ids),
    },
    "tiktok": {
        "by_share_url": lambda client, url: client.tiktok_app_v3.fetch_one_video_by_share_url_v2(share_url=url),
    },
    "xiaohongshu": {
        "by_share_url": lambda client, url: client.xiaohongshu_app_v2.get_video_note_detail(url=url),
    },
    "youtube": {
        "by_url": lambda client, url: client.youtube_web.get_video_info(url=url),
    },
}
```

### 3.4 视频 URL 提取策略

```python
def extract_video_download_url(platform: str, api_response_data: dict) -> str | None:
    """从 TikHub API 响应中提取视频下载 URL"""
    
    if platform == "douyin":
        aweme = api_response_data.get("aweme_detail") or api_response_data.get("data", {}).get("aweme_detail")
        if not aweme:
            return None
        video = aweme.get("video", {})
        # 优先 download_addr（无水印），其次 play_addr（有水印）
        for addr_key in ("download_addr", "play_addr", "cover_large"):
            url_list = video.get(addr_key, {}).get("url_list", [])
            if url_list:
                return url_list[0]
                
    elif platform == "tiktok":
        video_data = api_response_data.get("aweme_detail", {})
        play_addr = video_data.get("video_data", {}).get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        if url_list:
            return url_list[0]
            
    elif platform == "xiaohongshu":
        # 小红书响应结构：note.detail.video.url_list
        note = api_response_data.get("data", {}).get("note", {})
        url_list = note.get("detail", {}).get("video", {}).get("url_list", [])
        if url_list:
            return url_list[0]
            
    elif platform == "youtube":
        streaming_data = api_response_data.get("streaming_data", {})
        for quality in ("adaptiveFormats", "formats"):
            for fmt in streaming_data.get(quality, []):
                if fmt.get("type", "").startswith("video/") and fmt.get("url"):
                    return fmt["url"]
        # fallback: hls_manifest
        hls = streaming_data.get("hls_manifest_url")
        if hls:
            return hls
    
    return None
```

### 3.5 ASR + 分词流程（复用现有逻辑）

复用现有 `app.py` 中的 `add_punctuation()` + `model.transcribe()` 逻辑，提取为独立函数：

```python
def run_asr(video_path: str) -> tuple[list[dict], str, str]:
    """执行 ASR，返回 (segments, full_text, punctuated_text)"""
    result = model.transcribe(video_path, language='zh', task='transcribe')
    segments = [...]
    full_text = result['text'].strip()
    punctuated = add_punctuation(full_text)
    return segments, full_text, punctuated
```

### 3.6 API Key 配置

```python
# backend/config.py 新增
TIKHUB_API_KEY = "no1fWNEN62e1xCvLF4KS8guOaByfarA96CKJlFSceaGXlk6tJFbcVS2APw=="
TIKHUB_BASE_URL = "https://api.tikhub.io"  # 国内用户可改为 api.tikhub.dev
```

---

## 四、前端交互层（View）

### 4.1 新增链接输入区（放在现有上传区上方）

```html
<div class="link-input-section">
    <div class="section-title">🔗 多平台链接输入</div>
    <div class="link-input-area">
        <textarea 
            id="linkInput" 
            placeholder="粘贴抖音/小红书/TikTok/YouTube 分享链接，每行一个..."
            rows="4"
        ></textarea>
        <div class="link-actions">
            <button id="parseBtn" class="btn-parse">🔍 解析链接</button>
            <select id="platformSelect">
                <option value="auto">自动识别</option>
                <option value="douyin">抖音</option>
                <option value="tiktok">TikTok</option>
                <option value="xiaohongshu">小红书</option>
                <option value="youtube">YouTube</option>
            </select>
        </div>
        <div id="parseProgress" class="parse-progress"></div>
    </div>
</div>
```

### 4.2 解析结果展示

每个解析结果卡片：
- 平台图标 + 链接原始文本（截断）
- 状态标签（解析中 / 成功 / 失败）
- 视频预览缩略图（若成功）
- 错误信息（若失败）
- ASR 进度条（转写中）
- 操作按钮：播放视频 / 重新解析

### 4.3 原有上传区

保留 `index.html` 中现有的 JSON 文件上传逻辑，作为 TikHub 不可用时的降级方案。

---

## 五、全栈影响面分析

### 5.1 需修改的文件

| 文件 | 操作 | 改动说明 |
|---|---|---|
| `backend/config.py` | 修改 | 新增 `TIKHUB_API_KEY` 等配置 |
| `backend/app.py` | 修改 | 新增 `/api/parse_links` 等端点，抽取 ASR 逻辑 |
| `backend/schemas.py` | 新建 | Pydantic 数据模型 |
| `backend/services/tikhub_client.py` | 新建 | TikHub SDK 封装，平台路由 |
| `backend/services/video_extractor.py` | 新建 | 视频 URL 提取逻辑 |
| `frontend/index.html` | 修改 | 新增链接输入区，解析结果展示 |
| `SPEC.md` | 修改 | 新增 TikHub 集成功能说明 |

### 5.2 不受影响的现有逻辑

- 现有 `/upload` 端点保持不变（JSON 文件上传流程）
- 现有字幕样式定制 + 视频生成流程保持不变
- 现有 Whisper FFmpeg patch 逻辑保持不变

---

## 六、关键风险与缓解

| 风险 | 等级 | 缓解策略 |
|---|---|---|
| TikHub API 调用失败（网络/Key） | 中 | 降级到 yt-dlp 兜底；配置化 API Key |
| 视频下载链接 403/过期 | 高 | 2 次重试；友好错误提示 |
| 批量链接解析并发过大 | 中 | 串行处理 + 前端 loading 状态 |
| 小红书/YouTube API 响应结构差异 | 中 | 逐平台适配提取函数，含 fallback |
| API 计费超出 | 低 | 前端提示当前接口有费用，用户确认 |

---

## 七、实现优先级

### Phase 1（立即实现）
1. `backend/services/tikhub_client.py` — TikHub SDK 初始化 + 平台路由
2. `backend/config.py` — 新增 API Key 配置
3. `backend/app.py` — 新增 `/api/parse_links` 端点（仅支持抖音，分享链接）
4. `backend/schemas.py` — 数据模型定义
5. `frontend/index.html` — 新增链接输入 UI

### Phase 2（后续迭代）
6. 小红书、TikTok、YouTube 平台支持
7. 批量链接解析（10 个链接内）
8. 热搜榜入口（`/api/platform_hot`）
9. yt-dlp 降级兜底
