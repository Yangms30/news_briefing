from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- User ----------
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    created_at: datetime


# ---------- Setting ----------
class SettingPayload(BaseModel):
    categories: list[str]
    schedule_cron: str | None = None
    channels: dict[str, Any]  # {web: true, slack: "url", email: "addr"}


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    categories: list[str]
    schedule_cron: str | None
    channels: dict[str, Any]
    updated_at: datetime


# ---------- Article / Report ----------
class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    report_id: int
    category: str
    title: str
    summary: str
    link: str
    source: str | None
    published_at: datetime | None
    created_at: datetime


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    category: str
    radio_script: str | None
    created_at: datetime
    articles: list[ArticleOut]


class ReportGenerateResponse(BaseModel):
    user_id: int
    generated: int
    reports: list[ReportOut]


# ---------- Send ----------
class SendResult(BaseModel):
    channel: str
    status: str
    error_msg: str | None = None


class SendResponse(BaseModel):
    user_id: int
    results: list[SendResult]


# ---------- Dispatch Archive ----------
class DispatchChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel: str
    status: str
    error_msg: str | None
    recipient: str | None
    sent_at: datetime


class DispatchSummary(BaseModel):
    dispatch_id: str
    sent_at: datetime
    channels: list[DispatchChannelOut]
    report_count: int
    categories: list[str]


class DispatchDetail(BaseModel):
    dispatch_id: str
    sent_at: datetime
    channels: list[DispatchChannelOut]
    reports: list[ReportOut]
