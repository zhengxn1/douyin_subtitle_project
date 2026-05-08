"""
数据模型定义（Pydantic Schemas）
用于请求/响应验证和类型标注
"""

from pydantic import BaseModel, Field
from typing import Literal


class LinkParseRequest(BaseModel):
    links: list[str] = Field(..., description="分享链接列表，每行一个")
    platform: Literal["douyin", "tiktok", "xiaohongshu", "youtube", "auto"] = Field(
        default="auto", description="指定平台，auto 表示自动识别"
    )
    # 小红书专用：用户在浏览器登录后粘贴的 Cookie
    xhs_cookie: str | None = Field(
        default=None,
        description="小红书 Cookie（可选，提供后可解析需要登录才能访问的笔记）",
    )


class VideoParseResult(BaseModel):
    """单个视频解析结果"""

    platform: str = Field(..., description="平台名称")
    original_url: str = Field(..., description="原始分享链接")
    aweme_id: str | None = Field(default=None, description="平台视频 ID")
    video_url: str | None = Field(default=None, description="Flask 内部访问路径")
    local_path: str | None = Field(default=None, description="本地存储绝对路径")
    segments: list[dict] = Field(default_factory=list, description="字幕分段")
    full_text: str = Field(default="", description="完整转录文本")
    punctuated_text: str = Field(default="", description="加标点后的完整文本")
    original_desc: str = Field(default="", description="平台原始描述/标题")
    title: str | None = Field(default=None, description="提取的标题")
    author: str | None = Field(default=None, description="作者/UP主昵称")
    download_status: Literal["success", "cached", "failed"] = Field(
        default="failed", description="下载状态"
    )
    error: str | None = Field(default=None, description="错误信息")


class LinkParseResponse(BaseModel):
    """批量链接解析响应"""

    results: list[VideoParseResult]
    total: int
    success_count: int
    failed_count: int


class PlatformInfo(BaseModel):
    id: str
    name: str
    icon: str


class PlatformListResponse(BaseModel):
    platforms: list[PlatformInfo]


# ============================================================
# 搜索 & 详情页模型
# ============================================================

class VideoStats(BaseModel):
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    share_count: int = 0


class CommentItem(BaseModel):
    id: str
    user: str
    avatar: str | None = None
    content: str
    like_count: int = 0
    timestamp: str | None = None


class SearchResult(BaseModel):
    """搜索结果卡片（轻量，不含字幕）"""
    video_id: str
    platform: str
    title: str
    author: str | None = None
    author_avatar: str | None = None
    cover_url: str | None = None
    video_url: str | None = None  # 列表中为 None，详情才解析
    share_url: str
    stats: VideoStats = Field(default_factory=VideoStats)
    duration: int | None = None       # 秒
    duration_formatted: str | None = None  # "02:30"


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, description="搜索关键词")
    platform: Literal["douyin", "xiaohongshu", "auto"] = Field(default="auto")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class SearchResponse(BaseModel):
    success: bool
    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    error: str | None = None


class VideoDetailRequest(BaseModel):
    video_id: str
    platform: str = "douyin"
    share_url: str | None = None
    run_asr: bool = Field(
        default=False,
        description="是否触发 ASR 字幕生成（耗时 60-80 秒），默认 False 仅返回元数据"
    )


class VideoDetailResponse(BaseModel):
    """视频详情（含字幕、互动数据、评论）"""
    success: bool
    video_id: str
    platform: str
    title: str = ""
    author: str | None = None
    author_avatar: str | None = None
    cover_url: str | None = None
    video_url: str | None = None
    share_url: str = ""
    stats: VideoStats = Field(default_factory=VideoStats)
    duration: int | None = None
    duration_formatted: str | None = None
    segments: list[dict] = Field(default_factory=list)
    full_text: str = ""
    punctuated_text: str = ""
    original_desc: str = ""
    comments: list[CommentItem] = Field(default_factory=list)
    comments_total: int = 0
    comments_has_more: bool = False
    download_status: Literal["success", "cached", "failed"] = "failed"
    asr_done: bool = False
    error: str | None = None


class CommentsRequest(BaseModel):
    video_id: str
    platform: str = "douyin"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class CommentsResponse(BaseModel):
    success: bool
    comments: list[CommentItem] = Field(default_factory=list)
    total: int = 0
    has_more: bool = False
    error: str | None = None
