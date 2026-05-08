# 前端重构规格说明书：视频搜索与详情页

## 1. 背景与目标

### 现状
- 首页仅支持粘贴链接批量解析，无搜索、无列表、无详情
- 用户体验依赖"先有链接再处理"，无法发现内容

### 目标
1. 首页支持两种入口：**链接查询** + **关键词搜索**
2. 搜索结果以**卡片列表**展示（封面、点赞、播放、评论、收藏、转发）
3. 右侧/详情页：完整字幕 → 视频播放器 + 分段字幕 → 互动数据 → 评论内容
4. 预留**评论分析**扩展位
5. **性能优先**：慢查询异步化，不阻塞主线程，不影响 ASR 速度

---

## 2. 全栈架构

### 数据流

```
用户输入关键词 / 链接
    ↓
前端 立即渲染空列表 + loading
    ↓
后端 /api/search (关键词) → 异步 → 爬取搜索结果
后端 /api/parse_links (链接) → 同步 → 视频解析 + ASR（慢）
    ↓
前端展示 卡片列表 / 详情页
```

### 性能设计原则
- **搜索**：后端异步返回，前端轮询 / SSE
- **ASR**：保持原有逻辑（Whisper），不改动
- **列表加载**：首屏优先（只加载前20条），无限滚动
- **详情页**：视频 URL 懒加载（点进去才请求）
- **评论**：点"评论"tab 才加载，不阻塞首屏

---

## 3. 后端 API 设计

### 新增端点

#### `POST /api/search`
```json
// 请求
{
  "keyword": "李子柒 美食",
  "platform": "douyin",   // douyin | xiaohongshu | auto
  "page": 1,
  "page_size": 20
}

// 响应
{
  "success": true,
  "results": [
    {
      "video_id": "7321890123456789012",
      "platform": "douyin",
      "title": "...",
      "author": "...",
      "author_avatar": "https://...",
      "cover_url": "https://...",
      "video_url": null,         // 详情页才解析
      "share_url": "https://v.douyin.com/xxx",
      "stats": {
        "play_count": 1234000,
        "like_count": 89500,
        "comment_count": 3200,
        "collect_count": 15000,
        "share_count": 8900
      },
      "duration": 120,
      "duration_formatted": "02:00"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20
}
```

#### `POST /api/video_detail`
```json
// 请求（获取视频详情，含字幕）
{
  "video_id": "7321890123456789012",
  "platform": "douyin",
  "share_url": "https://v.douyin.com/xxx"   // 可选，提供则更准
}

// 响应
{
  "success": true,
  "video_id": "...",
  "platform": "...",
  "title": "...",
  "author": "...",
  "cover_url": "...",
  "video_url": "/video/tikhub_douyin_xxx.mp4",  // 本地缓存路径
  "segments": [...],        // Whisper 字幕分段
  "full_text": "...",
  "punctuated_text": "...",
  "stats": {...},
  "comments": [...],        // 评论列表（懒加载）
  "download_status": "success",
  "asr_done": true
}
```

#### `GET /api/video_comments`
```json
// 请求
{
  "video_id": "...",
  "platform": "...",
  "page": 1,
  "page_size": 20
}

// 响应
{
  "success": true,
  "comments": [
    {
      "id": "...",
      "user": "...",
      "avatar": "...",
      "content": "...",
      "like_count": 1234,
      "timestamp": "2026-01-15"
    }
  ],
  "total": 500,
  "has_more": true
}
```

### 修改端点

#### `POST /api/parse_links`
- 响应增加 `cover_url`, `stats`, `author`, `author_avatar`, `duration`, `duration_formatted`
- 小红书支持 `comment_count`（yt-dlp 可获取）

---

## 4. 数据模型变更 (schemas.py)

```python
class VideoStats(BaseModel):
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    share_count: int = 0

class SearchResult(BaseModel):
    video_id: str
    platform: str
    title: str
    author: str | None
    author_avatar: str | None
    cover_url: str | None
    video_url: str | None       # 列表中为 null，详情才解析
    share_url: str
    stats: VideoStats
    duration: int | None         # 秒
    duration_formatted: str | None  # "02:30"

class SearchRequest(BaseModel):
    keyword: str
    platform: Literal["douyin", "xiaohongshu", "auto"] = "auto"
    page: int = 1
    page_size: int = 20

class SearchResponse(BaseModel):
    success: bool
    results: list[SearchResult]
    total: int
    page: int
    page_size: int
    error: str | None = None
```

---

## 5. 前端页面结构

### 整体布局（双栏）
```
┌─────────────────────────────────────────────────────────┐
│  Header: Logo + 搜索框 + 链接输入切换 Tab               │
├──────────────────────────┬──────────────────────────────┤
│                          │                              │
│   左侧：结果列表          │   右侧：视频详情              │
│   （可点击卡片展开）       │   （固定在右侧，sticky）      │
│                          │                              │
│   - 封面缩略图           │   - 完整字幕（可复制）        │
│   - 标题（2行截断）       │   - 视频播放器（可点击全屏）   │
│   - 作者                  │   - 分段字幕（点击跳转）        │
│   - 点赞/播放/评论/收藏    │   - 互动数据                 │
│   - 点击 → 右侧加载详情   │   - 评论 Tab                 │
│                          │   - 预留分析位（灰色提示）     │
│   无限滚动加载更多         │                              │
└──────────────────────────┴──────────────────────────────┘
```

### 详情页模块顺序
1. **完整字幕**（可复制全文）
2. **视频播放器** + **分段字幕**（点击跳转）
3. **互动数据**（点赞 / 播放 / 评论 / 收藏 / 转发，数字格式化）
4. **评论区**（懒加载，点击加载更多）
5. **预留分析位**（显示提示文案"评论区分析功能即将上线"）

### 卡片 Hover 效果
- 鼠标悬停：卡片轻微上浮 + 阴影加深
- 右侧显示"▶ 查看详情"按钮

---

## 6. 实现计划

### Phase 1：后端 API（1-2小时）
1. `schemas.py`：新增 `SearchRequest/Response`, `VideoStats`, `SearchResult`
2. `backend/app.py`：新增 `/api/search`, `/api/video_detail`, `/api/video_comments` 三个端点
3. 抖音搜索：调用 TikHub `fetch_search_result` 或直接调抖音搜索 API
4. 小红书搜索：yt-dlp `--get-title --get-thumbnail` 方式（简单方案）
5. 评论获取：TikHub 有对应端点

### Phase 2：前端页面（2-3小时）
1. 重写 `index.html`：整体布局改为双栏
2. Tab 切换：链接模式 vs 搜索模式
3. 列表渲染：卡片 + 瀑布流/grid
4. 详情面板：5个模块顺序实现
5. 无限滚动
6. 评论懒加载

### Phase 3：数据填充
1. 抖音搜索 + 详情 + 评论
2. 小红书搜索（简单版）
3. 评论分析预留位文案

---

## 7. 平台限制说明

| 平台 | 搜索 | 评论 | 详情 | ASR |
|------|------|------|------|-----|
| 抖音 | TikHub `fetch_search_result` ✅ | TikHub ✅ | TikHub ✅ | Whisper ✅ |
| 小红书 | yt-dlp 简单方案 ⚠️ | ❌ 需 Cookie | yt-dlp ✅ | Whisper ✅ |
| TikTok | ❌ | ❌ | TikHub ✅ | Whisper ✅ |
| YouTube | ❌ | ❌ | TikHub ✅ | Whisper ✅ |

---

## 8. 文件清单

### 需修改
- `backend/schemas.py` — 新增数据模型
- `backend/app.py` — 新增3个 API 端点

### 需重写
- `frontend/index.html` — 整体重构（双栏布局 + 搜索 + 详情）

### 预留扩展
- `backend/services/search_client.py`（新建，搜索逻辑封装）
- `backend/services/comment_client.py`（新建，评论获取）
