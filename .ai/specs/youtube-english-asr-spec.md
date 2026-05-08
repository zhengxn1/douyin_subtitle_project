# 技术契约：YouTube 英文识别 + 中文翻译

## 需求

用户上传 YouTube 英文视频链接，系统转写为文字字幕后，**自动追加中文翻译**，最终展示双语字幕（英文原文 + 中文翻译）。

测试链接：`https://www.youtube.com/watch?v=WLj8B3coAUU`

---

## 现状分析

### 当前 ASR 流程

```
parse_single_link (tikhub_client.py:417)
    model.transcribe(video_path, language="zh", task="transcribe")
        ↓
    full_text = asr_result["text"].strip()
        ↓
    punctuated_text = add_punctuation_fn(full_text)  ← 仅加标点，无翻译
        ↓
    return { full_text, punctuated_text, segments, ... }
```

### 核心问题

1. **ASR 语言错误**：所有平台统一用 `language="zh"`，英文视频被强制当中文识别，大量错识别（"hello" → "哈喽"/"河洛"）
2. **缺少翻译**：ASR 结果只经过 `add_punctuation()` 加标点，没有翻译步骤
3. **返回值不完整**：`segments` 中只有 `text`，没有 `translation` 字段，前端无法渲染双语

### 各平台当前语言配置（app.py:417）

| 平台 | 当前 | 问题 |
|------|------|------|
| YouTube | `"zh"` ❌ | 英文视频强制中文识别，大量错字 |
| TikTok | `"zh"` ⚠️ | 同上（但大部分是中文视频，影响小）|
| 抖音 | `"zh"` ✅ | 正确，无需改动 |

---

## 解决方案

### 设计决策

**ASR 语言自动推断**：不依赖平台猜测语言，而是用 **Whisper 的语言检测能力**，让 Whisper 自己决定说什么语言。

**实现方案**：把 `language="zh"` 改为 `language=None`，Whisper 会自动检测音频语言并用该语言转写。

**翻译策略**：对于 YouTube 英文视频，在 `add_punctuation()` 之后追加翻译步骤。翻译不改变现有 `add_punctuation()` 的行为，新增独立翻译函数。

### 数据流（修改后）

```
parse_single_link
    ↓
model.transcribe(video_path, language=None)   ← 改为自动检测
    ↓
full_text (Whisper 检测到的语言，英文视频就是英文)
    ↓
punctuated_text = add_punctuation(full_text)
    ↓
translations = translate_text(punctuated_text, src_lang)   ← 新增：翻译
    ↓
segments = [{ text, translation }, ...]   ← segments 增加 translation 字段
    ↓
return { full_text, punctuated_text, translations, segments, ... }
```

---

## 契约设计

### 后端 → 前端响应字段变更

**现有字段（保持不变）**：

```json
{
  "platform": "youtube",
  "original_url": "...",
  "aweme_id": "...",
  "video_url": "/video/...",
  "segments": [
    { "start": 0.0, "end": 5.0, "text": "Hello everyone" }
  ],
  "full_text": "Hello everyone. Welcome to my channel.",
  "punctuated_text": "Hello everyone, welcome to my channel."
}
```

**新增字段**：

```json
{
  "detected_language": "en",          // Whisper 自动检测的语言代码
  "language_name": "English",          // 人类可读语言名
  "translations": {
    "full_text": "大家好，欢迎来到我的频道。",
    "punctuated_text": "大家好，欢迎来到我的频道。"
  },
  "segments": [
    {
      "start": 0.0,
      "end": 5.0,
      "text": "Hello everyone",       // 原文（Whisper 检测语言）
      "translation": "大家好"           // 中文翻译
    }
  ]
}
```

**语言检测 + 翻译决策规则**：

| 检测到的语言 | 是否翻译 | 翻译目标语言 |
|-------------|---------|-------------|
| `zh`（中文）| 不翻译 | - |
| `en`（英文）| 翻译 | 中文 |
| `ja`（日语）| 翻译 | 中文 |
| `ko`（韩语）| 翻译 | 中文 |
| 其他语言 | 翻译 | 中文 |

**为什么不用平台判断语言？**
- YouTube 视频可能是任何语言（英语/日语/韩语/中文都有）
- TikTok 也有大量英语内容
- 让 Whisper 自动检测是最准确的方式

---

## API 翻译方案选择

| 方案 | 成本 | 速度 | 准确性 | 实现复杂度 |
|------|------|------|--------|-----------|
| OpenAI API (GPT-4o-mini) | $0.15/1M tokens | 快（~500字/秒）| 高 | 中（需 API Key）|
| Google Translate API | $20/1M chars | 快 | 高 | 中 |
| 百度翻译 API | 免费额度 | 快 | 中 | 中 |
| DeepL API | 免费版有限额 | 快 | 高 | 中 |
| **本地模型（gpt4all）** | 免费 | 慢（CPU）| 中 | 高 |
| **规则替换（字典）** | 免费 | 极快 | 低 | 低 |

**推荐：OpenAI API (GPT-4o-mini)**

理由：
1. 翻译质量远高于免费方案
2. `gpt-4o-mini` 成本极低（约 $0.15/1M tokens），一段 10 分钟字幕约 2000 字，成本不到 $0.001
3. Whisper ASR 已经依赖网络，多一个 API 调用不是额外负担
4. 可以一次性把全文翻译，不按 segment 逐条调用（减少 API 次数）

**备选：DeepL API**（免费版每月 500K 字符，适合个人使用）

---

## 文件修改清单

### 1. `backend/config.py`（新建）

新增配置：

```python
# 翻译 API 配置
TRANSLATION_API = "openai"          # 可选: openai / deepl / baidu / none
OPENAI_API_KEY = ""                  # OpenAI API Key（从环境变量或手动填写）
OPENAI_MODEL = "gpt-4o-mini"         # 翻译用模型
DEEPL_API_KEY = ""                    # DeepL API Key（备选）
```

### 2. `backend/services/translation.py`（新建）

翻译服务模块：
- `detect_language(text)` — 从 Whisper 结果推断语言代码
- `translate_text(text, src_lang, target_lang)` — 统一翻译入口
- `translate_with_openai(text, model)` — OpenAI 翻译实现
- `translate_segments(segments, src_lang)` — 按 segment 逐条翻译（用于字幕对齐）
- `_split_into_chunks(text, max_chars)` — 按段落分块，避免单次请求超限

### 3. `backend/services/tikhub_client.py`（修改）

**修改点 1**：`parse_single_link()` 第 417 行

```python
# 修改前
asr_result = model.transcribe(video_path, language="zh", task="transcribe")

# 修改后
asr_result = model.transcribe(video_path, language=None, task="transcribe")
```

**修改点 2**：在 `asr_result` 处理后，调用翻译服务

```python
# 检测语言
detected_lang = detect_language_from_asr(asr_result)
need_translate = detected_lang not in ("zh", "zh-CN", "zh-TW")

translations = {}
if need_translate:
    translations = {
        "full_text": translate_text(punctuated_text, detected_lang, "zh"),
        "punctuated_text": translate_text(punctuated_text, detected_lang, "zh"),
    }

# 翻译 segments
if need_translate:
    for seg in segments:
        seg["translation"] = translate_text(seg["text"], detected_lang, "zh")
else:
    for seg in segments:
        seg["translation"] = None
```

**修改点 3**：返回值增加字段

```python
return {
    # ... 现有字段 ...
    "detected_language": detected_lang,
    "language_name": LANG_CODE_TO_NAME.get(detected_lang, detected_lang),
    "translations": translations,
}
```

### 4. `backend/app.py`（无修改）

Flask 端点无需修改，`parse_single_link` 已被 `api_parse_links` 调用，端点 I/O 不变。

### 5. `frontend/index.html`（修改）

**修改点 1**：subtitle-item 增加翻译显示

```html
<div class="subtitle-item" onclick="seekVideo(this)" data-start="${s.start}" data-end="${s.end}">
    <div class="time">${fmt(s.start)} - ${fmt(s.end)}</div>
    <div class="text">${escapeHtml(s.text)}</div>
    ${s.translation ? `<div class="translation">${escapeHtml(s.translation)}</div>` : ''}
</div>
```

**修改点 2**：新增 CSS

```css
.translation {
    color: #9333ea;
    font-size: 0.9em;
    margin-top: 4px;
    padding-top: 4px;
    border-top: 1px solid #e5e7eb;
}
```

**修改点 3**：显示语言标签（在字幕区标题栏）

```javascript
if (result.detected_language) {
    langLabel.innerText = `字幕语言: ${result.language_name} ${result.translations ? '→ 中文' : '(无需翻译)'}`;
}
```

---

## 全栈影响面

| 层次 | 变更 | 影响 |
|------|------|------|
| **后端逻辑** | Whisper language=None | 抖音/TikTok/YouTube 全部自动语言检测 |
| **后端逻辑** | 新增翻译服务 | 新增 `translation.py` |
| **后端返回** | `segments[].translation` | 前端需要适配新字段 |
| **后端返回** | `detected_language`, `language_name` | 前端新增语言标签显示 |
| **前端显示** | 双语字幕渲染 | UI 小幅调整 |
| **配置** | 新增 API Key 配置 | 用户需填写 OpenAI Key |
| **现有字段** | `full_text`, `punctuated_text` | 完全保持不变，向后兼容 |

---

## 一次解决不返工的关键决策

1. **不改 ASR 语言逻辑架构**：不改平台判断语言，只把 `"zh"` 改为 `None`，让 Whisper 自动检测。这是根本解法，YouTube/TikTok/抖音任何语言视频都正确。
2. **翻译作为独立模块**：`translation.py` 独立封装，不污染 `tikhub_client.py`，以后可换翻译 API。
3. **segment 级翻译**：翻译按每个时间轴片段独立翻译，保证时间轴和翻译一一对应，不会乱序。
4. **返回字段命名**：`translation` 而不是 `cn_text`，因为未来可能扩展为其他语言翻译。
5. **前端向后兼容**：`translation` 字段不存在时（中文视频）前端不显示翻译块，现有功能完全不受影响。
6. **翻译缓存策略**：同 aweme_id 的视频，翻译结果可复用（可选优化，后续再做）。

---

## 实现顺序

1. `config.py` 新增翻译配置
2. `services/translation.py` 实现翻译服务（先 Mock 实现验证流程，再接入真实 API）
3. `tikhub_client.py` 修改 `parse_single_link`
4. `frontend/index.html` 更新字幕显示
5. 端到端测试（YouTube 英文视频）
6. 更新 architecture-kb.md
