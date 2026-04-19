import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import Base, SessionLocal, engine
import models  # noqa: F401  ensure models are registered with Base
from models import Setting, User
from routers import dispatches, reports, send, settings as settings_router, users

# Scheduler is disabled for the demo window (prevents unbudgeted LLM spend).
# Re-enable by uncommenting the import and lifespan calls below.
# from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

DEMO_USER_ID = 1
DEMO_USER_NAME = "시연용 사용자"
DEMO_USER_EMAIL = "demo@briefbot.local"
DEMO_CATEGORIES = ["정치", "경제", "사회", "국제", "스포츠", "IT/과학"]
DEMO_SCHEDULE_CRON = "0 8 * * *"
DEMO_CHANNELS = {"web": True, "email": DEMO_USER_EMAIL}


def _ensure_demo_user() -> None:
    """Idempotent demo user + settings seeding.
    Login is disabled: the frontend always uses user_id=DEMO_USER_ID (=1),
    so we force that row to exist with the demo profile on every boot.
    """
    db = SessionLocal()
    try:
        # Remove any stray user that also claims the demo email under a different id
        # (would otherwise violate the UNIQUE(email) constraint below).
        stray = (
            db.query(User)
            .filter(User.email == DEMO_USER_EMAIL, User.id != DEMO_USER_ID)
            .first()
        )
        if stray:
            db.query(Setting).filter(Setting.user_id == stray.id).delete()
            db.delete(stray)
            db.flush()

        user = db.query(User).filter(User.id == DEMO_USER_ID).first()
        transitioning = user is not None and user.email != DEMO_USER_EMAIL
        if user:
            user.name = DEMO_USER_NAME
            user.email = DEMO_USER_EMAIL
        else:
            user = User(id=DEMO_USER_ID, name=DEMO_USER_NAME, email=DEMO_USER_EMAIL)
            db.add(user)
        db.commit()

        setting = db.query(Setting).filter(Setting.user_id == DEMO_USER_ID).first()
        cats_json = json.dumps(DEMO_CATEGORIES, ensure_ascii=False)
        chans_json = json.dumps(DEMO_CHANNELS, ensure_ascii=False)
        if not setting:
            db.add(Setting(
                user_id=DEMO_USER_ID,
                categories=cats_json,
                schedule_cron=DEMO_SCHEDULE_CRON,
                channels=chans_json,
            ))
            db.commit()
        elif transitioning:
            # user_id=1 row belonged to a different account — refresh settings to demo defaults too.
            setting.categories = cats_json
            setting.schedule_cron = DEMO_SCHEDULE_CRON
            setting.channels = chans_json
            db.commit()
        logger.info("demo user ready: id=%s email=%s", DEMO_USER_ID, DEMO_USER_EMAIL)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_demo_user()
    # start_scheduler()
    try:
        yield
    finally:
        # stop_scheduler()
        pass


app = FastAPI(title="BriefBot API", version="0.2.0", lifespan=lifespan)

cfg = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(send.router, prefix="/api/send", tags=["send"])
app.include_router(dispatches.router, prefix="/api/dispatches", tags=["dispatches"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
