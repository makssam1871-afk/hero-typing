from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime, timedelta
from typing import Dict, Optional

SQLALCHEMY_DATABASE_URL = "sqlite:///./typing_hero.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    achievements = Column(JSON, default=list)
    error_keys = Column(JSON, default=dict)

class TrainingSession(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    mode = Column(String)
    lang = Column(String)
    wpm = Column(Float)
    cpm = Column(Float)
    accuracy = Column(Float)
    errors = Column(Integer)
    score = Column(Integer)
    duration = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

class AuthRequest(BaseModel):
    email: str
    username: Optional[str] = "Герой"
    password: str

class SessionCreate(BaseModel):
    user_id: int
    mode: str
    lang: str
    wpm: float
    cpm: float
    accuracy: float
    errors: int
    score: int
    duration: int
    session_error_keys: Dict[str, int]
    new_achievements: list[str]

app = FastAPI(title="Печать героя API")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if db.query(User).count() == 0:
        demo_users = [
            User(email="neo@matrix.io", username="Neo_One", password="123", xp=4800, level=5, achievements=["first_blood", "speed_200", "combo_50", "genius_300"]),
            User(email="linus@kernel.org", username="Torvalds_C", password="123", xp=3200, level=4, achievements=["first_blood", "speed_200", "no_errors"]),
            User(email="guido@python.org", username="Python_Master", password="123", xp=1950, level=2, achievements=["first_blood"]),
        ]
        db.add_all(demo_users)
        db.commit()
        now = datetime.utcnow()
        sessions = [
            TrainingSession(user_id=1, mode="code", lang="en", wpm=92, cpm=460, accuracy=99.2, errors=1, score=2800, duration=45, created_at=now - timedelta(hours=1)),
            TrainingSession(user_id=2, mode="sentences", lang="ru", wpm=74, cpm=370, accuracy=97.8, errors=4, score=1900, duration=60, created_at=now - timedelta(days=2)),
            TrainingSession(user_id=3, mode="words", lang="en", wpm=61, cpm=305, accuracy=95.0, errors=7, score=1200, duration=30, created_at=now - timedelta(days=10)),
        ]
        db.add_all(sessions)
        db.commit()
    db.close()

@app.get("/")
def root():
    return FileResponse("static/index.html")

@app.post("/api/auth")
def authenticate(req: AuthRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        user = User(
            email=req.email,
            username=req.username or req.email.split("@")[0],
            password=req.password,
            xp=0, level=1, achievements=[], error_keys={}
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.password != req.password:
        raise HTTPException(status_code=400, detail="Неверный пароль")
    return {"id": user.id, "email": user.email, "username": user.username, "xp": user.xp, "level": user.level, "achievements": user.achievements, "error_keys": user.error_keys}

@app.post("/api/session")
def save_session(data: SessionCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    new_s = TrainingSession(
        user_id=user.id, mode=data.mode, lang=data.lang, wpm=data.wpm, cpm=data.cpm,
        accuracy=data.accuracy, errors=data.errors, score=data.score, duration=data.duration
    )
    db.add(new_s)

    user.xp += data.score
    user.level = 1 + (user.xp // 1000)

    curr_err = dict(user.error_keys) if user.error_keys else {}
    for k, v in data.session_error_keys.items():
        curr_err[k] = curr_err.get(k, 0) + v
    user.error_keys = curr_err

    curr_ach = list(user.achievements) if user.achievements else []
    for a in data.new_achievements:
        if a not in curr_ach:
            curr_ach.append(a)
    user.achievements = curr_ach

    db.commit()
    db.refresh(user)
    return {"xp": user.xp, "level": user.level, "achievements": user.achievements, "error_keys": user.error_keys}

@app.get("/api/stats/{user_id}")
def get_stats(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    sessions = db.query(TrainingSession).filter(TrainingSession.user_id == user_id).order_by(TrainingSession.created_at.asc()).all()
    return {
        "user": {"username": user.username, "xp": user.xp, "level": user.level, "achievements": user.achievements, "error_keys": user.error_keys},
        "total_sessions": len(sessions),
        "total_time": sum(s.duration for s in sessions),
        "avg_wpm": round(sum(s.wpm for s in sessions) / len(sessions), 1) if sessions else 0,
        "avg_acc": round(sum(s.accuracy for s in sessions) / len(sessions), 1) if sessions else 0,
        "history": [{"date": s.created_at.strftime("%H:%M (%d.%m)"), "wpm": round(s.wpm, 1), "cpm": round(s.cpm, 1), "accuracy": round(s.accuracy, 1)} for s in sessions[-15:]]
    }

@app.get("/api/leaderboard")
def get_leaderboard(period: str = "all", db: Session = Depends(get_db)):
    query = db.query(TrainingSession, User).join(User, TrainingSession.user_id == User.id)
    now = datetime.utcnow()
    if period == "today":
        query = query.filter(TrainingSession.created_at >= now - timedelta(days=1))
    elif period == "week":
        query = query.filter(TrainingSession.created_at >= now - timedelta(days=7))

    records = query.all()
    board = {}
    for s, u in records:
        if u.username not in board:
            board[u.username] = {"username": u.username, "max_wpm": s.wpm, "max_cpm": s.cpm, "avg_acc": [s.accuracy], "xp": u.xp, "level": u.level}
        else:
            board[u.username]["max_wpm"] = max(board[u.username]["max_wpm"], s.wpm)
            board[u.username]["max_cpm"] = max(board[u.username]["max_cpm"], s.cpm)
            board[u.username]["avg_acc"].append(s.accuracy)

    result = [
        {"username": k, "wpm": round(v["max_wpm"], 1), "cpm": round(v["max_cpm"], 0), "accuracy": round(sum(v["avg_acc"])/len(v["avg_acc"]), 1), "xp": v["xp"], "level": v["level"]}
        for k, v in board.items()
    ]
    return {
        "by_speed": sorted(result, key=lambda x: x["wpm"], reverse=True)[:10],
        "by_accuracy": sorted(result, key=lambda x: x["accuracy"], reverse=True)[:10],
        "by_xp": sorted(result, key=lambda x: x["xp"], reverse=True)[:10]
    }
