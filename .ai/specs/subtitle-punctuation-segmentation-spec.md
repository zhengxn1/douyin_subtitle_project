# 技术契约与架构设计书：字幕标点 + 分段重排

## 一、需求摘要

| 需求 | 现状 | 目标 |
|---|---|---|
| 标点符号 | Whisper 输出一句话一段，无标点 | 自动补全标点（逗号、句号、问号等） |
| 分段策略 | 一句话一段（粒度过细） | 用户自定义每段字数（50/100/自定义），自然语义断句 |
| 前端交互 | 无控制项 | 增加分段字数滑块/输入框 |

---

## 二、数据模型层（Schema）

### 2.1 后端 → 前端 API 响应（变更）

**原字段 `full_text`**（保持兼容，新增字段）：

```json
{
  "video_url": "...",
  "segments": [                          // Whisper 原始分段（不变）
    { "start": 0.0, "end": 2.5, "text": "今天天气很好" }
  ],
  "full_text": "...",                   // 原始无标点全文（不变）
  "original_desc": "...",

  // -------- 新增字段 -------- //
  "punctuated_text": "今天天气很好，我决定出门散步。",
  "re分段": [                           // 按用户设置重排后的分段
    {
      "start": 0.0,
      "end": 3.5,
      "text": "今天天气很好，我决定出门散步。"
    }
  ],
  "segment_char_limit": 100            // 本次使用的分段字数上限
}
```

> **全栈影响**：`index.html` 的 `fullTextDiv` 改为显示 `punctuated_text`，`renderSubtitles` 改为使用 `re分段` 数据。

---

### 2.2 前端 → 后端请求（新增参数）

`POST /upload` 支持 `FormData` 追加字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `segment_char_limit` | int | `100` | 每段最大中文字符数 |

---

## 三、后端服务层（API）

### 3.1 修改文件

**`backend/app.py`**

**变更点 1：分词工具依赖**

Whisper 的中文输出天然按词分token（如 `"今 天 天 气 很 好"` 或直接连写的 `"今天天气很好"`），需要做中文分词后再合句。

推荐工具（按优先级）：

1. **`jieba`（推荐）** — 最轻量，无需模型，安装即用：
   ```bash
   .\venv\Scripts\pip install jieba
   ```
   - 标点插入：用逗号连接短句，用句号/问号/感叹号在段落边界断句
   - 语义边界识别：`jieba` 分词后，根据标点列表和累积字数动态切分

2. **`pkuTextBreaker`（备选）** — 北京大学分词库，更精准但需额外依赖

**变更点 2：新增 `segment_by_char_limit()` 函数**

```python
def segment_by_char_limit(segments: list, char_limit: int) -> list:
    """
    将 Whisper 原始 segments 按字符数限制重排为更长的段落。
    算法：贪心合并——累积当前段字符数达到阈值时，以标点边界切分。
    返回 [{start, end, text}, ...]
    """
    # 1. 拼接所有文本
    # 2. 使用 jieba 分词 + 标点检测，找到自然断点
    # 3. 断点优先于字数阈值；若字数超限但无标点，强切
```

**变更点 3：`upload_json()` 修改**

```
请求参数: request.form.get('segment_char_limit', 100)
处理流程:
  1. Whisper 转录 → segments（不变）
  2. 合并 segments.text → raw_text
  3. 调用标点函数 → punctuated_text
  4. 调用 segment_by_char_limit() → re分段
  5. 返回响应（见 2.1 新增字段）
```

**变更点 4：`/config` 路由（可选，方便前端动态读默认值）**

```
GET /config
Response: { "default_segment_char_limit": 100 }
```

---

### 3.2 标点算法设计

#### 策略：规则引擎 + jieba 辅助（无需外部 API）

```
输入: raw_text = "今天天气很好我决定出门散步外面阳光明媚"
输出: punctuated_text = "今天天气很好，我决定出门散步。外面阳光明媚。"
```

**分句触发条件（优先级从高到低）：**

1. 已有标点（从 Whisper 输出中保留）
2. 语气词停顿：`啊` `呢` `吧` `吗` `嘛` `呀` `哦` → 后跟逗号或句号
3. 语义连接词：`然后` `但是` `因为` `所以` `如果` `虽然` → 前可断
4. 字数累积触发：连续超过 `char_limit * 1.5` 无断点，强切于最后一个完整词

**分词辅助（jieba）：** 用 `jieba.lcut(raw_text)` 获取词边界，在强切时优先在词边界处断开。

**示例算法伪代码：**

```
def add_punctuation_and_segment(raw_text, char_limit):
    words = jieba.lcut(raw_text)
    sentences = []
    current = ""
    for word in words:
        current += word
        # 检测断点
        if ends_with_punctuation(word) or ends_with_pause_word(word):
            sentences.append(current)
            current = ""
        elif len(current) > char_limit * 1.5 and current:
            # 强切于最后词的边界
            sentences.append(current)
            current = ""
    if current:
        sentences.append(current)
    return "，".join(sentences[: -1]) + "。" + sentences[-1] if sentences else ""
```

---

### 3.3 分段算法设计

```python
def segment_by_char_limit(segments: list, char_limit: int) -> list:
    """
    将连续多个 Whisper segment 合并为更长段落。
    - 合并相邻 segment.text（用空格隔开）
    - 当合并文本达到 char_limit 且遇标点/语气词时，切一段
    - 保留合并后段落的 start（第一个 segment 的 start）和 end（最后一个 segment 的 end）
    """
    if not segments:
        return []

    result = []
    buffer_start = segments[0]['start']
    buffer_end = segments[0]['end']
    buffer_text = ""

    def flush():
        nonlocal buffer_start, buffer_end, buffer_text
        if buffer_text:
            result.append({
                'start': round(buffer_start, 2),
                'end': round(buffer_end, 2),
                'text': buffer_text.strip()
            })
            buffer_text = ""

    for seg in segments:
        text = seg['text'].strip()
        if not text:
            continue
        buffer_text += (" " if buffer_text else "") + text
        buffer_end = seg['end']

        # 检查是否触发断句
        if should_break(buffer_text, char_limit):
            flush()
            buffer_start = seg['end']  # 下一段从当前之后开始

    flush()
    return result
```

---

## 四、前端交互层（View）

### 4.1 修改文件

**`frontend/index.html`**

#### 变更 1：上传区增加分段字数控制

```html
<div class="upload-area">
    <label class="upload-label" for="jsonFile">📁 上传 JSON 文件</label>
    <input type="file" id="jsonFile" accept=".json">

    <!-- 新增：分段字数控制 -->
    <div style="margin-top: 1rem; display: flex; align-items: center; gap: 0.75rem; justify-content: center;">
        <span style="font-size: 0.85rem; color: #6b7280;">每段字数：</span>
        <input type="range" id="charLimitSlider" min="30" max="200" value="100"
               style="width: 150px;" oninput="charLimitValue.innerText = this.value">
        <span id="charLimitValue" style="font-weight: 600; min-width: 2ch;">100</span>
        <span style="font-size: 0.8rem; color: #9ca3af;">字</span>
    </div>

    <div id="loadingMsg" class="loading"></div>
    <div id="errorMsg" class="error"></div>
</div>
```

#### 变更 2：发送请求时附带参数

```javascript
// 在 fetch('/upload') 前追加
formData.append('segment_char_limit', parseInt(charLimitSlider.value));
```

#### 变更 3：完整文本显示改为 punctuated_text

```javascript
fullTextDiv.innerText = data.punctuated_text || data.full_text || '未识别到语音';
```

#### 变更 4：`renderSubtitles` 改为使用 `re分段`

```javascript
// segments = data.segments || [];          // 旧：原始分段
segments = (data.re分段 || data.segments) || [];  // 新：优先重排分段
renderSubtitles(segments);
```

#### 变更 5：Tab 切换（可选）

在"完整文本"区域增加 Tab：`【原始文本】` / `【加标点】`，方便对比。

---

## 五、全栈文件清单

| 层级 | 文件 | 操作 |
|---|---|---|
| 依赖 | `requirements.txt` | 新增 `jieba` |
| 后端 | `backend/app.py` | 修改：新增函数，修改 `/upload` 路由 |
| 前端 | `frontend/index.html` | 修改：新增控制 UI，修改请求/渲染逻辑 |
| 架构知识 | `.ai/architecture-kb.md` | 追加 FFmpeg PATH patch 已知缺陷 [FIXED] |

---

## 六、待确认问题

1. **标点精度要求**：纯规则引擎的标点准确率约 80-90%，对于短视频口播足够。如果需要更高精度，可引入轻量 NLP（如 `paddlenlp` 的 `pipelines`），但会显著增加推理时间。你倾向于哪种？
2. **tab 切换功能**：是否需要"原始文本 vs 加标点文本"的 Tab 对比，还是直接替换显示？
3. **实时预览**：用户修改字数滑块后，是否需要**不重新请求**就实时预览分段效果（前端 JS 做分段重排）？这样体验更流畅。
