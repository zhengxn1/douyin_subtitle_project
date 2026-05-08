# Douyin Subtitle Project - Specification

## 1. Project Overview

**Project Name:** Douyin Subtitle Project
**Type:** Web application (Flask backend + HTML/JS frontend)
**Core Functionality:** Upload a Douyin/TikTok JSON subtitle file or paste share links (via TikHub API), extract video, transcribe with Whisper ASR, then generate a burned-in subtitle video with customizable font styling.
**Target Users:** Content creators who want to add styled subtitles to Douyin/TikTok videos.

---

## 2. UI/UX Specification

### Layout Structure

Single-page application with centered card layout.

- **Header:** App title + subtitle tagline
- **Main Card:** Two-column layout on desktop, single-column on mobile
  - Left column: Subtitle file upload + Preview section
  - Right column: Video upload + Output settings + Generate button
- **Footer:** Minimal copyright line

Responsive breakpoints:
- Desktop (>= 900px): Two-column layout, max-width 1100px
- Tablet/Mobile (< 900px): Single-column stacked layout

### Visual Design

**Color Palette:**
- Background: `#0f0f1a` (deep dark navy)
- Card background: `#1a1a2e` (dark purple-navy)
- Card border: `#2d2d4a` (subtle purple border)
- Primary accent: `#ff2d78` (hot pink/magenta - Douyin brand inspired)
- Secondary accent: `#7b2ff7` (electric purple)
- Text primary: `#f0f0f5` (near white)
- Text secondary: `#8888aa` (muted lavender)
- Success: `#00e676` (neon green)
- Error: `#ff5252` (bright red)
- Input background: `#12122a` (darker than card)
- Input border: `#3a3a5c` (medium purple-gray)

**Typography:**
- Font family: `'Inter'` from Google Fonts, fallback `'PingFang SC', 'Microsoft YaHei', sans-serif`
- Heading (H1): 28px, font-weight 700
- Heading (H2): 16px, font-weight 600, uppercase, letter-spacing 2px
- Body text: 14px, font-weight 400
- Small/muted text: 12px
- Monospace (for code/duration): `'JetBrains Mono', monospace`

**Spacing System:**
- Base unit: 8px
- Card padding: 32px
- Section gap: 24px
- Element gap: 16px
- Inner element gap: 8px

**Visual Effects:**
- Card: subtle box-shadow `0 8px 32px rgba(0,0,0,0.4)`, border-radius 16px
- Buttons: gradient backgrounds, hover scale 1.02, active scale 0.98
- Upload zones: dashed border, hover border-color transitions
- Progress bar: animated gradient shimmer
- Glassmorphism header strip

### Components

**1. File Upload Zone**
- States: default (dashed border #3a3a5c), hover/over (border-color #ff2d78, bg rgba(255,45,120,0.05)), file-loaded (solid border #00e676, shows filename)
- Icon: upload cloud icon (SVG inline)
- Text: instruction + supported format

**2. Subtitle Preview Panel**
- Scrollable list of subtitle entries
- Each entry: index number + timestamp range + text content
- Alternating row backgrounds for readability
- Shows "No subtitles loaded" empty state

**3. Video Preview Area**
- HTML5 `<video>` element, responsive width
- Controls enabled (play/pause/seek)
- Shows "No video loaded" placeholder with icon

**4. Settings Panel**
- Subtitle font size: range slider (16px - 72px, default 36px)
- Subtitle color: color picker (default #ffffff)
- Subtitle stroke: color picker (default #000000)
- Stroke width: range slider (0 - 4px, default 2)
- Vertical position: range slider (bottom offset 10% - 40%, default 20%)
- Font family selector: dropdown with options (Noto Sans SC, SimHei, Microsoft YaHei, Arial)

**5. Generate Button**
- Large, full-width button
- Gradient: linear-gradient(135deg, #ff2d78, #7b2ff7)
- Text: "Generate Video" in white, bold
- States: default, hover (glow effect), loading (spinner + "Processing..."), disabled (grayed out)
- Disabled when: no subtitle file uploaded AND no video uploaded

**6. Progress Indicator**
- Shown during processing
- Animated bar with gradient
- Percentage text
- Step description (e.g., "Merging subtitles...", "Encoding video...")

**7. Download Button**
- Appears after successful generation
- Gradient green background: linear-gradient(135deg, #00e676, #00c853)
- Shows file size

---

## 3. Functionality Specification

### Core Features

**F0. TikHub 多平台链接解析**
- 输入：多平台分享链接（抖音/TikTok/小红书/YouTube），支持嵌入在任意文本中
- 自动识别平台，支持手动指定
- **支持所有抖音 URL 类型**：分享短链（`v.douyin.com/xxx`）、视频页（`/video/{id}`）、精选/搜索入口页（`/jingxuan?modal_id=xxx`）
- 调用 TikHub API 获取视频元信息
- 自动下载视频（支持缓存，按 `aweme_id` 命名）
- ASR 转写 + 标点插入（全流程自动化）
- 支持部分成功（某些链接失败不影响其他）
- API Key 配置在 `backend/config.py`
- 端点：`POST /api/parse_links`、`GET /api/platforms`

**F1. JSON Subtitle File Upload**
- Accept `.json` files via drag-and-drop or file picker
- Parse JSON and extract subtitle entries
- Expected JSON format (Douyin/TikTok export format):
  ```json
  {
    "doc_info": {
      "title": "..."
    },
    "body": {
      "contents": [
        {
          "start": 0,
          "end": 3000,
          "content": "subtitle text"
        }
      ]
    }
  }
  ```
- Also support simpler array format:
  ```json
  [
    { "start": 0, "end": 3000, "text": "subtitle text" },
    { "start": 3000, "end": 6000, "text": "..." }
  ]
  ```
- Display subtitle count after load

**F2. Video File Upload**
- Accept `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`
- Store temporarily in `backend/uploads/`
- Show video player preview

**F3. Subtitle Preview**
- Display all parsed subtitle entries in scrollable list
- Show index, time range (MM:SS.mmm), and text

**F4. Video Preview**
- Play/pause/seek the uploaded video
- Responsive sizing

**F5. Subtitle Styling**
- Font size (16-72px)
- Text color (color picker)
- Stroke color (color picker)
- Stroke width (0-4px)
- Vertical position offset from bottom
- Font family selection

**F6. Video Generation**
- Use FFmpeg via `subprocess` to burn subtitles into video
- Generate ASS subtitle file from JSON
- Apply styling via ASS styles
- Encode output as H.264 MP4
- Output filename: `output_<timestamp>.mp4`
- Store output in `backend/uploads/`

**F7. Progress Feedback**
- Real-time progress via polling endpoint
- Show percentage and current step

**F8. Download**
- Serve generated video for download
- Auto-cleanup of temporary files after download

### User Interactions and Flows

1. **Load Subtitles Flow:**
   User drags JSON file onto upload zone → File parsed → Subtitle preview populated → Subtitle count shown

2. **Load Video Flow:**
   User drags video file → Stored in uploads → Video preview shown → Generate button becomes enabled (if both files present)

3. **Customize Flow:**
   User adjusts sliders/selectors → Settings updated in real-time (stored in JS state)

4. **Generate Flow:**
   Click Generate → Progress bar appears → Backend processes → On complete: download button appears → User downloads

5. **Reset Flow:**
   Clear buttons on each upload zone reset that section

### Data Flow

```
Frontend (index.html)
  ├── Paste share links → POST /api/parse_links → { results: [...] }
  │     └── loadResultAsVideo(idx) → load video + subtitles
  ├── File upload → POST /upload or /upload_subtitle
  ├── Settings → Stored in JS state (no server call until generate)
  ├── Generate → POST /generate with { subtitle_path, video_path, settings }
  ├── Poll → GET /progress
  └── Download → GET /download/<filename>

Backend (app.py)
  ├── /api/parse_links → TikHub SDK → download video → Whisper ASR → return results
  ├── /api/platforms → return supported platforms list
  ├── /upload_subtitle → Save JSON, parse, return { subtitles, count }
  ├── /upload_video → Save video, return { filename, size }
  ├── /generate → Spawn FFmpeg, update progress dict, return { output_file }
  ├── /progress → Return { percent, step }
  └── /download/<filename> → Serve file
```

### Edge Cases

- Invalid JSON format → Show error message, don't crash
- Video format not supported → Show error, reject upload
- FFmpeg not installed → Show helpful error with install instructions
- Very long video (>30 min) → Show warning about processing time
- No subtitles in JSON → Show "No subtitle entries found"
- Duplicate uploads → Replace previous file
- Generation failure → Show FFmpeg error, allow retry
- File size too large → Show limit warning (cap at 500MB)

---

## 4. Technical Specification

### Backend (Flask)

- **Framework:** Flask 3.x
- **Video Processing:** FFmpeg (system binary, called via subprocess)
- **Subtitle Format:** ASS (Advanced Substation Alpha) - better styling than SRT
- **File Handling:** Werkzeug for secure file uploads
- **CORS:** Flask-CORS for local development
- **Endpoints:**
  - `POST /upload_subtitle` - Accept JSON file
  - `POST /upload_video` - Accept video file
  - `POST /generate` - Start FFmpeg processing
  - `GET /progress` - Poll processing status
  - `GET /download/<filename>` - Download output file
  - `GET /health` - Health check

### Frontend (Vanilla HTML/JS)

- **No framework** - Pure HTML/CSS/JS
- **Drag & Drop:** HTML5 Drag and Drop API
- **HTTP Client:** Fetch API
- **Responsive:** CSS Grid + Flexbox + media queries
- **Font Loading:** Google Fonts (Inter)

### Dependencies (Python)

- Flask>=3.0.0
- Flask-CORS>=4.0.0
- Werkzeug>=3.0.0
- tikhub>=2.0.0
- requests>=2.31.0

### System Requirements

- FFmpeg must be installed and in PATH
- Python 3.9+
- Modern browser (Chrome, Firefox, Edge, Safari)

---

## 5. Acceptance Criteria

- [ ] JSON subtitle files can be uploaded and parsed correctly
- [ ] Video files can be uploaded and previewed
- [ ] Subtitle list is displayed with timestamps and text
- [ ] Video player works with native controls
- [ ] All styling settings (size, color, stroke, position, font) are applied
- [ ] Generated video has burned-in subtitles at correct timestamps
- [ ] Progress bar updates during generation
- [ ] Download button works for generated video
- [ ] UI is responsive on mobile devices
- [ ] Error states are handled gracefully with user-friendly messages
- [ ] No console errors during normal operation
