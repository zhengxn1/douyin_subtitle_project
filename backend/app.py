import concurrent.futures
import os
import sys

# 入口起点：将 backend/ 加入 sys.path，确保 services / config 等内部模块可导入
# （Flask 从项目根目录启动时，sys.path[0] = 项目根目录，不含 backend/）
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import json
import tempfile
import requests

# ============================================================
# 路径配置：所有路径基于 config.py 的位置，不依赖 cwd
# ============================================================
import config
_CONFIG_DIR = os.path.dirname(os.path.abspath(config.__file__))
UPLOAD_FOLDER = os.path.join(_CONFIG_DIR, config.UPLOAD_DIR)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# TikHub 服务
from services.tikhub_client import parse_single_link, SUPPORTED_PLATFORMS, detect_platform
from schemas import (
    LinkParseRequest, LinkParseResponse, VideoParseResult,
    PlatformListResponse,
    SearchRequest, SearchResponse,
    VideoDetailRequest, VideoDetailResponse,
    CommentsRequest, CommentsResponse,
    VideoStats, SearchResult, CommentItem,
)

# ============================================================
# FFmpeg 配置：Whisper 的 subprocess 直接调用 "ffmpeg"，
# 只从 PATH 找，不读 FFMPEG_BINARY。
# 在 Windows + Flask (reloader=False) 环境下，Python 的
# os.environ 修改不自动传递给 subprocess.Popen。
# 解决方式：patch whisper.audio.run，让它用绝对路径调用 ffmpeg。
# ============================================================
import imageio_ffmpeg
_ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
_ffmpeg_dir = os.path.dirname(_ffmpeg_bin)

from subprocess import run as _subprocess_run, CalledProcessError, PIPE

def _ffmpeg_run(cmd, capture_output=True, check=True):
    """patch 后的 run：确保 ffmpeg 用绝对路径，绕过 PATH 查找"""
    if cmd and cmd[0] == "ffmpeg":
        cmd = [_ffmpeg_bin] + cmd[1:]
    return _subprocess_run(cmd, capture_output=capture_output, check=check)

import whisper.audio
whisper.audio.run = _ffmpeg_run

# Patch load_audio：使用绝对路径 + 安全音频流映射
# - map 0:a?  只取第一个音频流（不存在时不报错），避免 "does not contain any stream"
# - ignore_unknown  跳过不支持的容器流类型
_orig_load_audio = whisper.audio.load_audio

def _safe_load_audio(file: str, sr: int = whisper.audio.SAMPLE_RATE):
    cmd = [
        _ffmpeg_bin,
        "-nostdin",
        "-threads", "0",
        "-ignore_unknown",
        "-i", file,
        "-map", "0:a?",
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sr),
        "-",
    ]
    try:
        out = _subprocess_run(cmd, capture_output=True, check=True).stdout
    except CalledProcessError as e:
        raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
    return whisper.audio.np.frombuffer(out, whisper.audio.np.int16).flatten().astype(whisper.audio.np.float32) / 32768.0

whisper.audio.load_audio = _safe_load_audio

# ============================================================
# 中文分词 + 标点插入（基于 jieba 规则引擎）
# ============================================================
import jieba


def add_punctuation(raw_text: str) -> str:
    """
    给纯文本加标点，规则：
    - 语气词（啊/呢/吧/吗/嘛/呀/哦）后插逗号
    - 连接词（但是/然后/因为/所以/如果/虽然/而且/不过）前断句
    - 每 40 字左右插逗号（自然停顿）
    - 累积超过 65 字强制断句
    结果每句约 30-65 字，适合阅读
    """
    if not raw_text or not raw_text.strip():
        return raw_text

    _PAUSE = set('啊呢吧吗嘛呀哦哈嗯嘿')
    _CONN = {'但是', '然后', '因为', '所以', '如果', '虽然', '而且', '不过'}
    _END_PUNCT = set('。！？，、；：')
    _SENT_END = set('。！？')

    result = []
    current = ""
    current_len = 0
    i = 0

    while i < len(raw_text):
        ch = raw_text[i]

        # 语气词 → 逗号
        if ch in _PAUSE:
            if current and current[-1] not in _END_PUNCT:
                current += '，'
                current_len += 1
            current += ch
            current_len += 1
            i += 1
            continue

        # 连接词
        is_conn = False
        conn_len = 0
        for w in _CONN:
            if raw_text[i:].startswith(w):
                is_conn = True
                conn_len = len(w)
                break

        if is_conn:
            # 前面有内容则断句
            if current_len > 10 and current[-1] not in _END_PUNCT:
                current += '。'
                result.append(current)
                current = ""
                current_len = 0
            # 连接词作为新句开头
            current += raw_text[i:i + conn_len]
            current_len += conn_len
            i += conn_len
            continue

        current += ch
        current_len += 1

        # 已有句末标点 → 这句结束，开始新句
        if ch in _SENT_END:
            result.append(current)
            current = ""
            current_len = 0
            i += 1
            continue

        # 累积超 65 字强制断句（退回到最近逗号处）
        if current_len >= 65:
            last_comma = current.rfind('，')
            if last_comma > 5:
                result.append(current[:last_comma + 1])
                current = current[last_comma + 1:]
                current_len = len(current)
            else:
                result.append(current + '。')
                current = ""
                current_len = 0
            i += 1
            continue

        # 每 40 字自动插逗号（自然停顿，不重复插）
        if current_len >= 40 and current[-1] not in _END_PUNCT:
            last_comma = current.rfind('，')
            if last_comma == -1 or current_len - last_comma > 20:
                current += '，'
                current_len += 1

        i += 1

    if current:
        if current[-1] not in _END_PUNCT:
            current += '。'
        result.append(current)

    return "".join(result)


# ============================================================
# Flask 应用
# ============================================================
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import whisper

app = Flask(__name__)
CORS(app)

# 视频访问路径前缀（相对于 Flask 静态路由）
VIDEO_ROUTE_PREFIX = "/video"


@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')


@app.route(f'{VIDEO_ROUTE_PREFIX}/<path:filename>')
def serve_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, mimetype='video/mp4')


def extract_video_url_from_json(json_data):
    """兼容 Tikhub 返回的 JSON，提取视频下载链接（download_addr 或 play_addr）"""
    aweme_detail = json_data.get('aweme_detail')
    if not aweme_detail and 'data' in json_data:
        aweme_detail = json_data['data'].get('aweme_detail')
    if not aweme_detail:
        return None

    video = aweme_detail.get('video', {})
    # 优先 download_addr
    download_addr = video.get('download_addr', {})
    url_list = download_addr.get('url_list', [])
    if url_list:
        return url_list[0]
    # 其次 play_addr
    play_addr = video.get('play_addr', {})
    url_list = play_addr.get('url_list', [])
    if url_list:
        return url_list[0]
    return None


def download_video(url, save_path):
    """带重试和 headers 的视频下载，防止 403"""
    # Referer 必须与视频 CDN 域名匹配，否则 403
    if 'xiaohongshu.com' in url or 'xhscdn.com' in url:
        referer = 'https://www.xiaohongshu.com/'
    elif 'douyin.com' in url or 'amemv.com' in url:
        referer = 'https://www.douyin.com/'
    elif 'tiktok.com' in url:
        referer = 'https://www.tiktok.com/'
    elif 'youtube.com' in url or 'youtu.be' in url:
        referer = 'https://www.youtube.com/'
    else:
        referer = 'https://www.xiaohongshu.com/'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': referer,
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            if resp.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            elif resp.status_code == 403:
                raise Exception(f"403 (URL may have expired): {url[:100]}")
            else:
                resp.raise_for_status()
        except Exception as e:
            if attempt == 0:
                continue
            raise e
    return False


@app.route('/upload', methods=['POST'])
def upload_json():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'Only JSON files are allowed'}), 400

    json_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(json_path)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        video_url = extract_video_url_from_json(json_data)
        if not video_url:
            return jsonify({'error': 'No valid video URL found in JSON. Please ensure JSON contains aweme_detail.video.download_addr or play_addr.'}), 400

        aweme_id = (
            json_data.get('aweme_detail', {}).get('aweme_id')
            or json_data.get('data', {}).get('aweme_detail', {}).get('aweme_id')
            or 'temp'
        )
        video_filename = f"{aweme_id}.mp4"
        video_path = os.path.join(UPLOAD_FOLDER, video_filename)

        # 若缓存不存在则下载
        if not os.path.exists(video_path):
            print(f"[Download] from {video_url[:80]}...")
            download_video(video_url, video_path)
            print(f"[Download] saved to {video_path}")
        else:
            print(f"[Cache] using existing {video_path}")

        # ASR：language=None 让 Whisper 自动检测音频语言
        result = model.transcribe(video_path, language=None, task='transcribe')
        segments = [
            {'start': round(seg['start'], 2), 'end': round(seg['end'], 2), 'text': seg['text'].strip()}
            for seg in result['segments']
        ]
        full_text = result['text'].strip()
        punctuated_text = add_punctuation(full_text)
        basic_desc = (
            json_data.get('aweme_detail', {}).get('desc')
            or json_data.get('data', {}).get('aweme_detail', {}).get('desc', '')
        )

        return jsonify({
            'video_url': f'{VIDEO_ROUTE_PREFIX}/{video_filename}',
            'segments': segments,
            'full_text': full_text,
            'punctuated_text': punctuated_text,
            'original_desc': basic_desc,
            'detected_language': result.get('language', 'unknown'),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()  # 打印到 stderr（终端可见）
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500
    finally:
        if os.path.exists(json_path):
            os.unlink(json_path)


# ============================================================
# TikHub 链接解析端点
# ============================================================

@app.route('/api/quick_parse', methods=['POST'])
def api_quick_parse():
    """
    快速查询：只调 TikHub API 取元数据，不下载不 ASR。
    用于首页"查询"按钮。

    返回字段：video_id / platform / title / author / cover_url / stats / ...
    """
    try:
        data = request.get_json()
        req = LinkParseRequest(**data)
    except Exception as e:
        return jsonify({"error": f"请求格式错误: {e}"}), 400

    from services.tikhub_client import fetch_video_by_link, extract_metadata_from_response

    results = []
    for url in req.links:
        raw = fetch_video_by_link(
            url=url,
            platform=req.platform,
            xhs_cookie=req.xhs_cookie,
        )
        meta = extract_metadata_from_response(raw)
        results.append(_quick_result_to_parse_result(url, meta))

    success_count = sum(1 for r in results if r.download_status == "success")
    failed_count = len(results) - success_count

    resp = LinkParseResponse(
        results=results,
        total=len(results),
        success_count=success_count,
        failed_count=failed_count,
    )
    return jsonify(resp.model_dump())


def _quick_result_to_parse_result(url: str, meta: dict) -> VideoParseResult:
    """将 extract_metadata_from_response 输出映射为 VideoParseResult（兼容 schema）"""
    s = meta.get("stats") or {}
    return VideoParseResult(
        platform=meta.get("platform") or "unknown",
        original_url=url,
        aweme_id=meta.get("video_id") or None,
        video_url=None,
        local_path=None,
        segments=[],
        full_text="",
        punctuated_text="",
        original_desc=meta.get("title") or "",
        title=meta.get("title"),
        author=meta.get("author"),
        download_status="success" if meta.get("success") else "failed",
        error=meta.get("error"),
    )


@app.route('/api/parse_links', methods=['POST'])
def api_parse_links():
    """
    批量完整解析（含下载 + ASR 字幕生成）。
    默认仅返回元数据，run_asr=True 时触发 ASR。
    """
    try:
        data = request.get_json()
        req = LinkParseRequest(**data)
    except Exception as e:
        return jsonify({"error": f"请求格式错误: {e}"}), 400

    from services.tikhub_client import parse_single_link

    results = []
    for url in req.links:
        result = parse_single_link(
            url=url,
            platform=req.platform,
            upload_folder=UPLOAD_FOLDER,
            xhs_cookie=req.xhs_cookie,
        )
        results.append(result)

    success_count = sum(1 for r in results if r["download_status"] != "failed")
    failed_count = len(results) - success_count

    resp = LinkParseResponse(
        results=results,
        total=len(results),
        success_count=success_count,
        failed_count=failed_count,
    )
    return jsonify(resp.model_dump())


@app.route('/api/platforms', methods=['GET'])
def api_platforms():
    """返回支持的平台列表"""
    resp = PlatformListResponse(platforms=SUPPORTED_PLATFORMS)
    return jsonify(resp.model_dump())


# ============================================================
# 搜索 & 详情页 API
# ============================================================

@app.route('/api/search', methods=['POST'])
def api_search():
    """关键词搜索（当前优先抖音；小红书/其他平台返回链接粘贴引导）"""
    try:
        req = SearchRequest(**request.get_json())
    except Exception as e:
        return jsonify({"success": False, "error": f"请求格式错误: {e}", "results": [], "total": 0}), 400

    results = []
    total = 0
    error_msg = None

    try:
        if req.platform in ("auto", "douyin"):
            results, total = _search_douyin(req.keyword, req.page, req.page_size)
        elif req.platform == "xiaohongshu":
            results, total = _search_xiaohongshu(req.keyword, req.page, req.page_size)
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)

    resp = SearchResponse(
        success=error_msg is None,
        results=results,
        total=total,
        page=req.page,
        page_size=req.page_size,
        error=error_msg,
    )
    return jsonify(resp.model_dump())


def _search_douyin(keyword: str, page: int, page_size: int):
    """
    抖音搜索：fetch_experience_search（综合搜索） + fetch_challenge_search_v1（话题搜索）
    两路并行请求，取并集，速度 ~2.4s（不等最慢那个）。

    实测结论（2026-04-27）：
    - fetch_challenge_search_v1 → challenge_list[n].items 永远为空（0个视频）
    - fetch_experience_search → business_data[n].data.aweme_info 有视频 ✅
    - fetch_general_search_result → HTTP 403 需要登录
    """
    from services.tikhub_client import get_tikhub_client
    client = get_tikhub_client(timeout=15.0)
    results = {}   # keyed by video_id, dedup
    cursor = (page - 1) * page_size

    def _call_experience():
        try:
            return client.douyin_search.fetch_experience_search(keyword=keyword, cursor=cursor) or {}
        except Exception:
            return {}

    def _call_challenge():
        try:
            return client.douyin_search.fetch_challenge_search_v1(keyword=keyword, cursor=cursor) or {}
        except Exception:
            return {}

    # 两路并行
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut_exp = pool.submit(_call_experience)
        fut_chl = pool.submit(_call_challenge)
        exp_raw = fut_exp.result()
        chl_raw = fut_chl.result()

    # 综合搜索：business_data[n].data.aweme_info
    for entry in (exp_raw.get("data", {}).get("business_data") or []):
        aweme = entry.get("data", {}).get("aweme_info") or entry.get("aweme_info") or {}
        aweme_id = str(aweme.get("aweme_id", ""))
        if not aweme_id or aweme_id in results:
            continue
        _add_aweme(aweme, results)

    # 话题搜索：challenge_list[n].items
    for challenge in (chl_raw.get("data", {}).get("challenge_list") or []):
        for aweme in (challenge.get("items") or []):
            aweme_id = str(aweme.get("aweme_id", ""))
            if not aweme_id or aweme_id in results:
                continue
            _add_aweme(aweme, results)

    items = list(results.values())
    return items[:page_size], len(items)


def _add_aweme(aweme: dict, results: dict):
    """将单个 aweme dict 加入 results（按 video_id dedup）"""
    aweme_id = str(aweme.get("aweme_id", ""))
    if not aweme_id or aweme_id in results:
        return
    video = aweme.get("video") or {}
    cover_list = (video.get("cover") or {}).get("url_list") or []
    stats = aweme.get("statistics") or {}
    results[aweme_id] = SearchResult(
        video_id=aweme_id,
        platform="douyin",
        title=str(aweme.get("desc") or ""),
        author=aweme.get("author", {}).get("nickname"),
        author_avatar=aweme.get("author", {}).get("avatar_uri"),
        cover_url=cover_list[0] if cover_list else None,
        share_url=str(aweme.get("share_url") or ""),
        stats=VideoStats(
            play_count=stats.get("play_count", 0),
            like_count=stats.get("digg_count", 0),
            comment_count=stats.get("comment_count", 0),
            collect_count=stats.get("collect_count", 0),
            share_count=stats.get("share_count", 0),
        ),
        duration=video.get("duration"),
        duration_formatted=_format_duration(video.get("duration")),
    )


def _search_xiaohongshu(keyword: str, page: int, page_size: int):
    """
    小红书搜索：fetch_search_notes。

    实测结论（2026-04-27）：
    - 可能遭遇 HTTP 400 限速，重试可恢复
    - item.noteCard 包含：displayTitle, user, interactInfo, cover, type
    - noteId 不在 noteCard 内，在 item 顶层
    - item.noteCard.user = {nickName, avatar, userId}  (camelCase)
    - item.noteCard.interactInfo = {likedCount, collectedCount, commentCount, sharedCount} (字符串)
    - item.noteCard.displayTitle = 搜索专用标题
    - 分享链接需要 noteId，可构造 https://www.xiaohongshu.com/explore/{noteId}
    """
    import time, urllib.error
    from services.tikhub_client import get_tikhub_client
    client = get_tikhub_client(timeout=15.0)
    results = []
    raw_items = []

    # 重试机制：TikHub 搜索接口偶发 400 限速
    for attempt in range(3):
        try:
            r = client.xiaohongshu_web_v3.fetch_search_notes(keyword=keyword, page=page)
            if isinstance(r, dict) and r.get("code") == 200:
                xraw = r.get("data", {})
                inner = xraw.get("data") if isinstance(xraw, dict) else None
                if isinstance(inner, dict):
                    raw_items = inner.get("items") or []
                elif isinstance(xraw, list):
                    raw_items = xraw
                break
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1.5)

    for item in raw_items:
        nc = item.get("noteCard") or {}
        # noteId 在 item 顶层，不在 noteCard 内
        nid = item.get("noteId") or item.get("note_id") or item.get("id") or ""
        if not nid:
            continue

        user = nc.get("user") or {}
        interact = nc.get("interactInfo") or {}
        cover_raw = nc.get("cover")

        def _int(v, default=0):
            try:
                return int(v) if isinstance(v, (int, str)) and str(v).isdigit() else default
            except (ValueError, TypeError):
                return default

        # cover 可能是字符串、dict 或 None
        cover_url = None
        if isinstance(cover_raw, str) and cover_raw:
            cover_url = cover_raw
        elif isinstance(cover_raw, dict):
            cover_url = cover_raw.get("urlDefault") or cover_raw.get("url")

        results.append(SearchResult(
            video_id=str(nid),
            platform="xiaohongshu",
            # 搜索场景专用标题优先
            title=str(nc.get("displayTitle") or nc.get("title") or ""),
            author=user.get("nickName") or user.get("nickname"),
            author_avatar=user.get("avatar"),
            cover_url=cover_url,
            share_url=f"https://www.xiaohongshu.com/explore/{nid}",
            stats=VideoStats(
                like_count=_int(interact.get("likedCount", 0)),
                comment_count=_int(interact.get("commentCount", 0)),
                collect_count=_int(interact.get("collectedCount", 0)),
                share_count=_int(interact.get("sharedCount", 0)),
            ),
            duration=nc.get("duration"),
            duration_formatted=_format_duration(nc.get("duration")),
        ))

    return results[:page_size], len(results)


@app.route('/api/video_detail', methods=['POST'])
def api_video_detail():
    """
    获取视频详情。

    - run_asr=False（默认）：仅返回元数据（标题/作者/互动数据），< 1s
    - run_asr=True：触发下载+ASR，返回字幕，60-80s

    性能原则：详情展示永远不自动 ASR，按需手动触发。
    """
    try:
        req = VideoDetailRequest(**request.get_json())
    except Exception as e:
        return jsonify({"success": False, "error": f"请求格式错误: {e}"}), 400

    from services.tikhub_client import detect_platform

    url = req.share_url
    if not url:
        if req.platform == "douyin":
            url = f"https://www.douyin.com/video/{req.video_id}"
        elif req.platform == "xiaohongshu":
            url = f"https://www.xiaohongshu.com/explore/{req.video_id}"
        else:
            url = req.video_id

    platform = req.platform
    if platform == "auto":
        platform = detect_platform(url)

    # ── 快速路径：只拿元数据，不下载不 ASR ──
    if not req.run_asr:
        return _quick_detail(url, platform, req.video_id)

    # ── 完整路径：下载视频 + ASR ──
    from services.tikhub_client import parse_single_link
    result = parse_single_link(url=url, platform=platform, upload_folder=UPLOAD_FOLDER)

    comments = []
    comments_total = 0
    comments_has_more = False
    if result.get("download_status") != "failed":
        try:
            comments, comments_total, comments_has_more = _fetch_comments(req.video_id, platform)
        except Exception:
            pass

    return jsonify(VideoDetailResponse(
        success=result.get("download_status") != "failed",
        video_id=result.get("aweme_id") or req.video_id,
        platform=platform,
        title=result.get("title") or result.get("original_desc", ""),
        author=result.get("author"),
        cover_url=result.get("cover_url"),
        video_url=result.get("video_url"),
        share_url=url,
        stats=VideoStats(
            play_count=result.get("stats", {}).get("play_count", 0),
            like_count=result.get("stats", {}).get("like_count", 0),
            comment_count=comments_total,
            collect_count=result.get("stats", {}).get("collect_count", 0),
            share_count=result.get("stats", {}).get("share_count", 0),
        ),
        duration=result.get("duration"),
        duration_formatted=_format_duration(result.get("duration")),
        segments=result.get("segments", []),
        full_text=result.get("full_text", ""),
        punctuated_text=result.get("punctuated_text", ""),
        original_desc=result.get("original_desc", ""),
        comments=comments,
        comments_total=comments_total,
        comments_has_more=comments_has_more,
        download_status=result.get("download_status", "failed"),
        asr_done=len(result.get("segments", [])) > 0,
        error=result.get("error"),
    ).model_dump())


def _quick_detail(url: str, platform: str, video_id: str):
    """
    快速获取视频元数据（标题/作者/互动数据/封面/时长）。
    不下载视频，不执行 ASR，预期 < 1s。
    """
    from services.tikhub_client import fetch_video_by_link, detect_platform

    if platform == "auto":
        platform = detect_platform(url)

    result = fetch_video_by_link(url, platform)
    if not result.get("success"):
        return jsonify({
            "success": False,
            "error": result.get("error", "获取视频信息失败"),
            "video_id": video_id,
            "platform": platform,
        }), 200

    data = result.get("data", {})
    aweme_detail = data.get("aweme_detail") or data
    # 小红书数据路径
    xhs_note = result.get("xhs_note_info") or {}

    video_info = aweme_detail.get("video", {}) if aweme_detail else {}
    stats_info = aweme_detail.get("statistics", {}) if aweme_detail else {}
    author_info = aweme_detail.get("author", {}) if aweme_detail else {}
    xhs_user = xhs_note.get("user", {}) or {}

    # 封面
    cover_url = None
    cover_raw = (
        aweme_detail.get("video", {}).get("cover", {}).get("url_list")
        if aweme_detail else None
    )
    if cover_raw:
        cover_url = cover_raw[0] if isinstance(cover_raw, list) else None

    # 分享链接
    share_url = (
        aweme_detail.get("share_url")
        if aweme_detail else xhs_note.get("share_url")
    ) or url

    return jsonify(VideoDetailResponse(
        success=True,
        video_id=video_id,
        platform=platform,
        title=(
            aweme_detail.get("desc") or aweme_detail.get("title")
            or xhs_note.get("title") or xhs_note.get("displayTitle") or ""
        ),
        author=(
            author_info.get("nickname")
            or xhs_user.get("nickName")
            or xhs_user.get("nickname") or ""
        ),
        author_avatar=(
            author_info.get("avatar_uri")
            or xhs_user.get("avatar") or None
        ),
        cover_url=cover_url,
        video_url=None,          # 快速路径不返回 video_url（需要下载）
        share_url=share_url,
        stats=VideoStats(
            play_count=stats_info.get("play_count", 0),
            like_count=stats_info.get("digg_count", 0),
            comment_count=stats_info.get("comment_count", 0),
            collect_count=stats_info.get("collect_count", 0),
            share_count=stats_info.get("share_count", 0),
        ),
        duration=(
            int(video_info.get("duration", 0) // 1000)
            if video_info.get("duration") else xhs_note.get("duration")
        ),
        duration_formatted=_format_duration(
            int(video_info.get("duration", 0) // 1000)
            if video_info.get("duration") else xhs_note.get("duration")
        ),
        segments=[],
        full_text="",
        punctuated_text="",
        original_desc=aweme_detail.get("desc") if aweme_detail else "",
        comments=[],
        comments_total=0,
        comments_has_more=False,
        download_status="failed",
        asr_done=False,
        error=None,
    ).model_dump())


@app.route('/api/video_comments', methods=['GET'])
def api_video_comments():
    """获取视频评论（分页）"""
    try:
        req = CommentsRequest(
            video_id=request.args.get("video_id", ""),
            platform=request.args.get("platform", "douyin"),
            page=int(request.args.get("page", 1)),
            page_size=int(request.args.get("page_size", 20)),
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"参数错误: {e}", "comments": []}), 400

    try:
        comments, total, has_more = _fetch_comments(req.video_id, req.platform, req.page, req.page_size)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "comments": []}), 200

    resp = CommentsResponse(success=True, comments=comments, total=total, has_more=has_more)
    return jsonify(resp.model_dump())


def _fetch_comments(video_id: str, platform: str, page: int = 1, page_size: int = 20):
    """获取评论列表"""
    from services.tikhub_client import get_tikhub_client
    client = get_tikhub_client()
    comments = []
    total = 0
    has_more = False

    if platform == "douyin":
        try:
            r = client.douyin_app_v3.fetch_general_search_result(
                keyword="", offset=(page - 1) * page_size, count=page_size
            )
            # 抖音评论暂无直接端点，用搜索结果占位
            # TODO: 接入抖音评论 API
        except Exception:
            pass
    elif platform == "xiaohongshu":
        try:
            r = client.xiaohongshu_web_v3.fetch_note_comments(note_id=video_id, page=page)
            if isinstance(r, dict):
                raw = r.get("data", {}).get("comments", []) if isinstance(r.get("data"), dict) else []
                for c in raw:
                    comments.append(CommentItem(
                        id=str(c.get("id", "")),
                        user=c.get("user_info", {}).get("nickname", "匿名"),
                        avatar=c.get("user_info", {}).get("avatar"),
                        content=c.get("content", ""),
                        like_count=c.get("like_count", 0),
                        timestamp=c.get("create_time"),
                    ))
                total = r.get("data", {}).get("cursor", {}).get("total", 0) or 0
                has_more = r.get("data", {}).get("has_more", False)
        except Exception:
            pass

    return comments, total, has_more


def _format_duration(seconds: int | None) -> str:
    """秒 → MM:SS"""
    if not seconds:
        return ""
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}:{secs:02d}"


# 加载 Whisper 模型（启动时一次性加载）
model = whisper.load_model("base")


if __name__ == '__main__':
    print(f"[Config] UPLOAD_FOLDER = {UPLOAD_FOLDER}")
    print(f"[Config] FFmpeg = {imageio_ffmpeg.get_ffmpeg_exe()}")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
