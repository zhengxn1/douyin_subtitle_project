"""
TikHub API 客户端封装
支持：抖音、TikTok、小红书（视 API Key 权限）、YouTube
"""

import re
import os
import hashlib
from urllib.parse import urlparse

import config


# ============================================================
# TikHub 客户端单例
# ============================================================
_tikhub_client = None


def get_tikhub_client(timeout: float = 30.0):
    """获取 TikHub 客户端单例"""
    global _tikhub_client
    if _tikhub_client is None:
        from tikhub import TikHub
        _tikhub_client = TikHub(api_key=config.TIKHUB_API_KEY, timeout=timeout)
    return _tikhub_client


SUPPORTED_PLATFORMS = [
    {"id": "douyin",     "name": "抖音",      "icon": "🎵"},
    {"id": "tiktok",     "name": "TikTok",    "icon": "🎬"},
    {"id": "xiaohongshu","name": "小红书",    "icon": "📕"},
    {"id": "youtube",    "name": "YouTube",   "icon": "▶️"},
]


# ============================================================
# 平台识别（基于域名，不依赖路径关键词）
# ============================================================
def detect_platform(url: str) -> str:
    """
    从 URL 自动识别平台，返回 platform id 或 'unknown'。
    基于 hostname 解析，不依赖 URL 路径，任何子路径都能识别。
    """
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return "unknown"
        hostname = hostname.lower()
        if 'douyin.com' in hostname or 'amemv.com' in hostname:
            return "douyin"
        if 'tiktok.com' in hostname:
            return "tiktok"
        if 'xiaohongshu.com' in hostname or 'xhslink.com' in hostname:
            return "xiaohongshu"
        if 'youtube.com' in hostname or 'youtu.be' in hostname:
            return "youtube"
    except Exception:
        pass
    return "unknown"


# ============================================================
# 各平台视频 ID 提取（基于 URL 解析，不依赖 TikHub API）
# ============================================================

def extract_douyin_video_id(url: str) -> str | None:
    """从任意抖音 URL 提取 aweme_id"""
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]modal_id=(\d+)', url)
    if m:
        return m.group(1)
    if 'v.douyin.com' in url:
        import requests
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10)
            return extract_douyin_video_id(resp.url)
        except Exception:
            return None
    return None


def extract_tiktok_video_id(url: str) -> str | None:
    """从任意 TikTok URL 提取 aweme_id"""
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'tiktok\.com/t/(\w+)', url)
    if m:
        return m.group(1)
    return None


def extract_xiaohongshu_note_id(url: str) -> str | None:
    """从任意小红书 URL 提取 note_id"""
    m = re.search(r'/discovery/item/([0-9a-fA-F]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/explore/([0-9a-fA-F]+)', url)
    if m:
        return m.group(1)
    return None


def extract_youtube_video_id(url: str) -> str | None:
    """从任意 YouTube URL 提取 video_id"""
    m = re.search(r'youtu\.be/([\w-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]v=([\w-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/shorts/([\w-]+)', url)
    if m:
        return m.group(1)
    return None


# ============================================================
# 视频下载 URL 提取（兼容 v1 / v2 / v3 API 响应结构）
# ============================================================

def extract_douyin_aweme_id(api_resp: dict) -> str | None:
    """从抖音 API 响应中提取 aweme_id"""
    aweme = (
        api_resp.get("aweme_detail")
        or api_resp.get("data", {}).get("aweme_detail")
    )
    if aweme:
        return str(aweme.get("aweme_id", ""))
    return None


def extract_douyin_video_url(api_resp: dict) -> str | None:
    """从抖音 API 响应中提取视频下载 URL（优先无水印）"""
    aweme = (
        api_resp.get("aweme_detail")
        or api_resp.get("data", {}).get("aweme_detail")
    )
    if not aweme:
        return None
    video = aweme.get("video", {})
    for addr_key in ("download_addr", "play_addr"):
        url_list = video.get(addr_key, {}).get("url_list", [])
        if url_list:
            return url_list[0]
    return None


def extract_tiktok_video_url(api_resp: dict) -> str | None:
    """从 TikTok API 响应中提取视频下载 URL"""
    # 尝试多个可能的路径：
    # - data.aweme_detail (抖音/旧 TikTok 格式)
    # - data.aweme_details[0] (TikTok share_url v2 格式)
    # - data.aweme_list[0] (某些版本)
    data = api_resp.get("data", {})
    aweme = (
        api_resp.get("aweme_detail")
        or data.get("aweme_detail")
        or data.get("aweme_details", [{}])[0]
        or data.get("aweme_list", [{}])[0]
    )
    if not aweme:
        return None

    # 优先无水印 download_addr，回退 play_addr
    for addr_key in ("download_addr", "play_addr"):
        play_addr = (
            aweme.get("video_data", {}).get(addr_key, {})
            or aweme.get("video", {}).get(addr_key, {})
        )
        url_list = play_addr.get("url_list", [])
        if url_list:
            return url_list[0]

    # fallback: 直接从 data 顶层找
    for key in ("video_url", "play_addr", "download_addr"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def extract_xiaohongshu_video_url(api_resp: dict) -> str | None:
    """从小红书 API 响应中提取视频下载 URL"""
    note = api_resp.get("data", {}).get("note", {})
    url_list = (
        note.get("detail", {}).get("video", {}).get("url_list", [])
        or note.get("video", {}).get("url_list", [])
    )
    if url_list:
        return url_list[0]
    # fallback: 直接从 data 顶层遍历
    data = api_resp.get("data", {})
    for val in data.values():
        if isinstance(val, str) and ("video" in val.lower() or val.startswith("http")):
            return val
    return None


def extract_youtube_video_url(api_resp: dict) -> str | None:
    """从 YouTube API 响应中提取视频下载 URL

    优先级：
    1. formats（含音视频混合流，可直接 ASR）优先
    2. adaptiveFormats 中音频质量非空的流次之
    3. adaptiveFormats 纯视频流兜底
    """
    streaming = api_resp.get("data", {}).get("streamingData", {})
    formats = streaming.get("formats", [])
    adaptive = streaming.get("adaptiveFormats", [])

    # 1. formats 含音视频混合流（YouTube 的 formats[0] 通常是 mp4 含音频）
    for fmt in formats:
        if fmt.get("url"):
            return fmt["url"]

    # 2. adaptiveFormats 中有 audioQuality 的流（有音频轨道）
    for fmt in adaptive:
        audio_q = fmt.get("audioQuality")
        if audio_q and fmt.get("url"):
            return fmt["url"]

    # 3. adaptiveFormats 纯视频兜底（Whisper 可能无音频可转写）
    for fmt in adaptive:
        if fmt.get("url"):
            return fmt["url"]

    return streaming.get("hlsManifestUrl")


VIDEO_URL_EXTRACTORS = {
    "douyin": extract_douyin_video_url,
    "tiktok": extract_tiktok_video_url,
    "xiaohongshu": extract_xiaohongshu_video_url,
    "youtube": extract_youtube_video_url,
}


# ============================================================
# TikHub API 调用入口
# 策略：URL 直接含 ID → 直接 ID 调用；否则走分享链接 API
# ============================================================
def fetch_video_by_link(url: str, platform: str = "auto", xhs_cookie: str = None) -> dict:
    """
    根据分享链接调用 TikHub API，返回原始响应 dict。
    返回格式: {"success": True, "data": {...}} 或 {"success": False, "error": "..."}
    """
    if platform == "auto":
        platform = detect_platform(url)

    if platform == "unknown":
        return {"success": False, "error": f"无法识别的链接平台: {url}"}

    try:
        client = get_tikhub_client()

        # ── 抖音 ──────────────────────────────────────────────
        if platform == "douyin":
            video_id = extract_douyin_video_id(url)
            if video_id and 'v.douyin.com' not in url:
                try:
                    resp = client.douyin_app_v3.fetch_one_video_v3(aweme_id=video_id)
                except Exception:
                    resp = client.douyin_app_v3.fetch_one_video_v2(aweme_id=video_id)
                return {"success": True, "platform": "douyin", "data": resp, "aweme_id": video_id}
            else:
                resp = client.douyin_app_v3.fetch_one_video_by_share_url(share_url=url)
                return {"success": True, "platform": "douyin", "data": resp}

        # ── TikTok ────────────────────────────────────────────
        elif platform == "tiktok":
            # 优先直接 ID 调用（无需 redirect），fallback 分享链接
            video_id = extract_tiktok_video_id(url)
            if video_id:
                try:
                    resp = client.tiktok_app_v3.fetch_one_video_by_share_url_v2(share_url=url)
                except Exception:
                    resp = client.tiktok_app_v3.fetch_one_video(aweme_id=video_id)
                return {"success": True, "platform": "tiktok", "data": resp, "aweme_id": video_id}
            else:
                resp = client.tiktok_app_v3.fetch_one_video_by_share_url_v2(share_url=url)
                return {"success": True, "platform": "tiktok", "data": resp}

        # ── 小红书 ────────────────────────────────────────────
        elif platform == "xiaohongshu":
            note_id = extract_xiaohongshu_note_id(url)
            if not note_id:
                return {"success": False, "error": f"无法从小红书链接提取 note_id: {url}"}

            # 优先 TikHub API（有权限时）
            try:
                resp = client.xiaohongshu_app_v2.get_video_note_detail(
                    note_id=note_id, share_text=url
                )
                return {"success": True, "platform": "xiaohongshu", "data": resp, "note_id": note_id}
            except Exception as e:
                err_msg = str(e)
                if "402" in err_msg or "403" in err_msg or "400" in err_msg:
                    # API 无权限 → 有 cookie 则 fallback 到 HTML 解析
                    pass  # 继续 fallthrough
                else:
                    return {"success": False, "error": f"小红书 API 调用失败: {e}"}

            # Fallback: 用户提供了 Cookie，用 HTML 方式解析
            if xhs_cookie:
                from services.xhs_cookie_client import fetch_xhs_note_info
                xhs_result = fetch_xhs_note_info(url, xhs_cookie)
                if xhs_result.get("success"):
                    return {
                        "success": True,
                        "platform": "xiaohongshu",
                        "data": {"xhs_note": xhs_result},   # 兼容 extract 接口
                        "note_id": note_id,
                        "xhs_note_info": xhs_result,
                    }
                else:
                    return {"success": False, "error": xhs_result.get("error", "Cookie 方式获取失败")}

            return {
                "success": False,
                "error": "小红书 API 无权限。请提供登录 Cookie 尝试，或升级 TikHub API Key",
            }

        # ── YouTube ───────────────────────────────────────────
        elif platform == "youtube":
            video_id = extract_youtube_video_id(url)
            if not video_id:
                return {"success": False, "error": f"无法从 YouTube 链接提取 video_id: {url}"}
            # 优先 v2（v1/v3 可能 402）
            try:
                resp = client.youtube_web.get_video_info_v2(video_id=video_id)
            except Exception:
                resp = client.youtube_web.get_video_info(video_id=video_id)
            return {"success": True, "platform": "youtube", "data": resp, "video_id": video_id}

        else:
            return {"success": False, "error": f"暂不支持平台: {platform}"}

    except Exception as e:
        return {"success": False, "error": f"TikHub API 调用失败: {e}"}


# ============================================================
# 快速元数据查询（仅查 API，不下载不 ASR）
# ============================================================

def extract_metadata_from_response(result: dict) -> dict:
    """
    从 fetch_video_by_link 返回的原始 result 中提取标准化元数据。
    各平台数据结构差异大，统一在此归一化。
    返回字段：video_id, platform, title, author, author_avatar, cover_url,
              share_url, stats{play,like,comment,collect,share}, duration
    """
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "查询失败")}

    platform = result.get("platform", "")
    data = result.get("data") or {}
    aweme = data.get("aweme_detail") or data   # 抖音/TT 结构
    xhs = result.get("xhs_note_info") or {}     # 小红书结构

    # ── 封面 ──────────────────────────────────────────────
    cover_url = None
    if platform in ("douyin", "tiktok"):
        raw = (aweme.get("video") or {}).get("cover") or {}
        urls = raw.get("url_list") or []
        cover_url = urls[0] if urls else None
    elif platform == "xiaohongshu":
        raw = xhs.get("cover") or {}
        cover_url = raw.get("urlDefault") if isinstance(raw, dict) else (raw or None)

    # ── 作者 ─────────────────────────────────────────────
    author = None
    author_avatar = None
    if platform in ("douyin", "tiktok"):
        author = aweme.get("author") or {}
        author = author.get("nickname") if isinstance(author, dict) else None
        av_raw = ((aweme.get("author") or {}).get("avatar_thumb") or {}).get("url_list") or []
        author_avatar = av_raw[0] if av_raw else None
    elif platform == "xiaohongshu":
        user = xhs.get("user") or {}
        author = user.get("nickName") or user.get("nickname")
        author_avatar = user.get("avatar")

    # ── 统计数据 ────────────────────────────────────────
    stats = {"play_count": 0, "like_count": 0, "comment_count": 0, "collect_count": 0, "share_count": 0}
    if platform in ("douyin", "tiktok"):
        s = aweme.get("statistics") or {}
        if isinstance(s, dict):
            stats = {
                "play_count": s.get("play_count", 0),
                "like_count": s.get("digg_count", 0),
                "comment_count": s.get("comment_count", 0),
                "collect_count": s.get("collect_count", 0),
                "share_count": s.get("share_count", 0),
            }
    elif platform == "xiaohongshu":
        ii = xhs.get("interactInfo") or {}
        if isinstance(ii, dict):
            def _ni(v): return int(v) if (isinstance(v, str) and v.isdigit()) else 0
            stats = {
                "like_count":    _ni(ii.get("likedCount")),
                "comment_count": _ni(ii.get("commentCount")),
                "collect_count": _ni(ii.get("collectedCount")),
                "share_count":  _ni(ii.get("sharedCount")),
            }

    # ── 标题 ────────────────────────────────────────────
    title = ""
    if platform in ("douyin", "tiktok"):
        title = aweme.get("desc") or ""
    elif platform == "xiaohongshu":
        title = xhs.get("displayTitle") or xhs.get("title") or ""

    # ── 时长 ────────────────────────────────────────────
    duration = None
    if platform in ("douyin", "tiktok"):
        raw_dur = (aweme.get("video") or {}).get("duration")
        if raw_dur:
            duration = int(raw_dur) // 1000 if raw_dur > 1000 else int(raw_dur)
    elif platform == "xiaohongshu":
        duration = xhs.get("duration")

    # ── ID & 分享链接 ────────────────────────────────────
    vid = result.get("aweme_id") or result.get("note_id") or result.get("video_id") or ""
    share_url = (aweme.get("share_url") if aweme else None) or xhs.get("share_url") or result.get("original_url") or ""

    return {
        "success": True,
        "video_id": str(vid),
        "platform": platform,
        "title": title,
        "author": author,
        "author_avatar": author_avatar,
        "cover_url": cover_url,
        "share_url": share_url,
        "stats": stats,
        "duration": duration,
    }


# ============================================================
# 单链接完整解析流程（fetch + download + ASR）
# ============================================================
def _build_error_result(url: str, error: str) -> dict:
    return {
        "platform": "unknown",
        "original_url": url,
        "aweme_id": None,
        "video_url": None,
        "local_path": None,
        "segments": [],
        "full_text": "",
        "punctuated_text": "",
        "original_desc": "",
        "title": None,
        "author": None,
        "download_status": "failed",
        "error": error,
    }


def parse_single_link(
    url: str,
    platform: str = "auto",
    upload_folder: str = None,
    model=None,
    add_punctuation_fn=None,
    download_video_fn=None,
    xhs_cookie: str = None,
) -> dict:
    """
    解析单个分享链接，返回标准化结果字典。
    """
    from app import (
        add_punctuation as _ap,
        download_video as _dv,
        model as _model,
        UPLOAD_FOLDER as _default_folder,
    )

    if upload_folder is None:
        upload_folder = _default_folder
    if add_punctuation_fn is None:
        add_punctuation_fn = _ap
    if download_video_fn is None:
        download_video_fn = _dv
    if model is None:
        model = _model

    result = fetch_video_by_link(url, platform, xhs_cookie=xhs_cookie)

    if not result["success"]:
        return _build_error_result(url, result["error"])

    detected_platform = result.get("platform", platform)
    api_data = result["data"]

    # XHS Cookie 方式：xhs_note_info 字段携带解析结果，直接取 video_url
    xhs_note_info = result.get("xhs_note_info")
    if xhs_note_info and detected_platform == "xiaohongshu":
        note_video_url = xhs_note_info.get("video_url")
        if xhs_note_info.get("type") == "normal" and not note_video_url:
            return _build_error_result(url, "该笔记为纯图文，无视频内容可下载")
        video_url = note_video_url
        aweme_id = result.get("note_id") or hashlib.md5(url.encode()).hexdigest()[:16]
    else:
        extractor = VIDEO_URL_EXTRACTORS.get(detected_platform)
        if not extractor:
            return _build_error_result(url, f"平台 {detected_platform} 暂不支持视频 URL 提取")
        video_url = extractor(api_data)
        aweme_id = (
            result.get("aweme_id")
            or result.get("note_id")
            or result.get("video_id")
            or (extract_douyin_aweme_id(api_data) if detected_platform == "douyin" else None)
        )
        if not aweme_id:
            aweme_id = hashlib.md5(url.encode()).hexdigest()[:16]

    if not video_url:
        return _build_error_result(url, "从 API 响应中未能提取到视频 URL")

    ext = "mp4"
    video_filename = f"tikhub_{detected_platform}_{aweme_id}.{ext}"
    video_path = os.path.join(upload_folder, video_filename)

    # 下载或使用缓存
    if os.path.exists(video_path):
        download_status = "cached"
    else:
        try:
            download_video_fn(video_url, video_path)
            download_status = "success"
        except Exception as e:
            return _build_error_result(url, f"视频下载失败: {e}")

    # ASR：language=None 让 Whisper 自动检测音频语言（英文视频出英文，中文视频出中文）
    try:
        asr_result = model.transcribe(video_path, language=None, task="transcribe")
        detected_lang = asr_result.get("language", "unknown")
        segments = [
            {
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "text": seg["text"].strip(),
            }
            for seg in asr_result["segments"]
        ]
        full_text = asr_result["text"].strip()
        punctuated_text = add_punctuation_fn(full_text)

        return {
            "platform": detected_platform,
            "original_url": url,
            "aweme_id": aweme_id,
            "video_url": f"/video/{video_filename}",
            "local_path": video_path,
            "segments": segments,
            "full_text": full_text,
            "punctuated_text": punctuated_text,
            "detected_language": detected_lang,
            "original_desc": "",
            "title": None,
            "author": None,
            "download_status": download_status,
            "error": None,
        }
    except Exception as e:
        return _build_error_result(url, f"ASR 转写失败: {e}")
