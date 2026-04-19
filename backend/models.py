from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    setting: Mapped["Setting"] = relationship(back_populates="user", uselist=False)
    reports: Mapped[list["Report"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    articles: Mapped[list["Article"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    categories: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    schedule_cron: Mapped[str | None] = mapped_column(String(100))
    channels: Mapped[str] = mapped_column(Text, nullable=False)  # JSON dict
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="setting")


class Report(Base):
    """Per-category report: one radio script + 3 articles."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    radio_script: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="reports")
    articles: Mapped[list["Article"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="Article.id",
    )


class Article(Base):
    """Individual news article with LLM-generated 3-line summary."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="articles")
    report: Mapped[Report] = relationship(back_populates="articles")


class SendLog(Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Shared across all channel rows produced by a single dispatch_user_reports() call
    # so that the archive view can GROUP BY dispatch_id. UUID4 hex (32 chars).
    dispatch_id: Mapped[str] = mapped_column(String(36), nullable=False, default="", index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text)
    # Recipient snapshot at send time: email address / slack webhook URL / "web".
    recipient: Mapped[str | None] = mapped_column(String(500))
    # JSON array of Report.id included in this batch (e.g. "[12,13,14,15,16,17]").
    report_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
