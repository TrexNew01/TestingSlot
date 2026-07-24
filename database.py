"""
ស្រទាប់ផ្ទុកទិន្នន័យជាអចិន្ត្រៃយ៍ (persistent storage) សម្រាប់ Slot Game
=========================================================================
ជំនួស dictionary ក្នុង memory (USER_BALANCES, USER_STREAK, ...) ដោយ SQLite
តាមរយៈ SQLAlchemy ដូច្នេះទិន្នន័យអ្នកលេងមិនបាត់បង់ពេល restart server ទៀតទេ។

ចំណាំសំខាន់:
- SQLite សមរម្យសម្រាប់ traffic តូច/មធ្យម (single-file, write-lock លើឯកសារ)។
  ប្រសិនបើប្រព័ន្ធរីកធំ (concurrent writers ច្រើន) គួរប្តូរទៅ PostgreSQL
  ដោយគ្រាន់តែប្តូរ DATABASE_URL, មិនចាំបាច់កែ model ឬ endpoint ទាល់តែសោះ។
- session ត្រូវបានបើក/បិទក្នុងមួយ "unit of work" (មួយ request) តាមរយៈ
  get_session() ដែលជា context manager (auto-commit/rollback)។
- ការសរសេរ SQLAlchemy ជា synchronous (មិនមែន async ORM ទេ) ព្រោះ SQLite
  ជា local file, លឿនល្មម។ វានៅតែត្រូវការពារ race condition តាមរយៈ
  per-user asyncio.Lock នៅក្នុង main.py (មិនមែនពឹងលើ DB lock ទាំងស្រុងទេ),
  ព្រោះ logic ជាច្រើនជំហាន (អាន -> គណនា -> សរសេរ) ត្រូវការ atomic ជា block។
"""
import json
import os
from contextlib import contextmanager
from datetime import date

from sqlalchemy import (
    Column, Date, Float, Integer, String, Text, UniqueConstraint, create_engine
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./slot_game.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class UserAccount(Base):
    """សមតុល្យ + streak + ថ្ងៃចុងក្រោយដែលបានទទួល daily bonus ក្នុងមួយ user។"""
    __tablename__ = "user_accounts"

    user_id = Column(Integer, primary_key=True)
    balance = Column(Float, nullable=False, default=0.0)
    streak = Column(Integer, nullable=False, default=0)
    last_login_bonus_date = Column(Date, nullable=True)


class SpinStat(Base):
    """ចំនួន spin ក្នុងថ្ងៃបច្ចុប្បន្ន ក្នុងមួយ user (សម្រាប់ responsible-play limit)។"""
    __tablename__ = "spin_stats"

    user_id = Column(Integer, primary_key=True)
    stat_date = Column(Date, nullable=False)
    daily_count = Column(Integer, nullable=False, default=0)


class BonusState(Base):
    """ស្ថានភាព Free Spins / Pick-a-box កំពុងដំណើរការ ក្នុងមួយ user។"""
    __tablename__ = "bonus_states"

    user_id = Column(Integer, primary_key=True)
    free_spins_remaining = Column(Integer, nullable=False, default=0)
    free_spin_multiplier = Column(Float, nullable=False, default=1.0)
    base_bet = Column(Float, nullable=False, default=0.0)
    # 🌟 ផ្ទុកជា JSON string ព្រោះមានរចនាសម្ព័ន្ធ nested (values/revealed list)
    pending_pick_box_json = Column(Text, nullable=True)

    def get_pending_pick_box(self):
        if not self.pending_pick_box_json:
            return None
        return json.loads(self.pending_pick_box_json)

    def set_pending_pick_box(self, value: dict | None):
        self.pending_pick_box_json = json.dumps(value) if value is not None else None


class UserBadge(Base):
    """Badge ដែល user បានដោះស្រាយរួច (one row per badge unlocked)។"""
    __tablename__ = "user_badges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    badge_id = Column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)


class LeaderboardEntry(Base):
    """ការឈ្នះធំបំផុតប្រចាំថ្ងៃរបស់ user (reset ដោយប្រៀបធៀប entry_date != today)។"""
    __tablename__ = "leaderboard_entries"

    user_id = Column(Integer, primary_key=True)
    entry_date = Column(Date, nullable=False)
    name = Column(String(64), nullable=False, default="Player")
    best_win = Column(Float, nullable=False, default=0.0)
    multiplier = Column(Float, nullable=False, default=0.0)


def init_db():
    """បង្កើត table ទាំងអស់ (no-op បើមានរួច)។ ហៅនៅ startup event។"""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    """Context manager មួយ request/unit-of-work: commit ស្វ័យប្រវត្តិពេលចេញដោយជោគជ័យ,
    rollback ពេលមាន exception។ ត្រូវប្រើនៅក្នុង per-user asyncio.Lock ជានិច្ច
    ដើម្បីជៀសវាង race condition នៃ logic ច្រើនជំហាន (មិនមែន SQLite transaction
    តែឯងគ្រប់គ្រាន់ទេ ព្រោះមាន business logic កាត់ / បូក balance ចន្លោះ read-write)។
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()