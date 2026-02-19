"""Theater and screen data models with SQLAlchemy ORM + SQLite."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
    delete,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

logger = logging.getLogger(__name__)

DB_PATH = Path("data/theaters.db")
SEED_PATH = Path("seed/theaters.db")
LEGACY_JSON_PATH = Path("data/theaters.json")


# ---------------------------------------------------------------------------
# Screen type constants
# ---------------------------------------------------------------------------

SCREEN_TYPE_NORMAL = "normal"
SCREEN_TYPE_IMAX = "imax"
SCREEN_TYPE_4DX = "4dx"
SCREEN_TYPE_SCREENX = "screenx"
SCREEN_TYPE_DOLBY_ATMOS = "dolby_atmos"
SCREEN_TYPE_DOLBY_CINEMA = "dolby_cinema"
SCREEN_TYPE_SUPERPLEX = "superplex"
SCREEN_TYPE_CHARLOTTE = "charlotte"
SCREEN_TYPE_COMFORT = "comfort"
SCREEN_TYPE_BOUTIQUE = "boutique"
SCREEN_TYPE_RECLINER = "recliner"
SCREEN_TYPE_PREMIUM = "premium"

SPECIAL_TYPES: set[str] = {
    SCREEN_TYPE_IMAX,
    SCREEN_TYPE_4DX,
    SCREEN_TYPE_SCREENX,
    SCREEN_TYPE_DOLBY_ATMOS,
    SCREEN_TYPE_DOLBY_CINEMA,
    SCREEN_TYPE_SUPERPLEX,
    SCREEN_TYPE_CHARLOTTE,
    SCREEN_TYPE_BOUTIQUE,
    SCREEN_TYPE_PREMIUM,
}

# CGV tcscnsGradNm (screen grade name) → type
CGV_GRADE_NAME_MAP: dict[str, str] = {
    "아이맥스": SCREEN_TYPE_IMAX,
    "IMAX": SCREEN_TYPE_IMAX,
    "4DX": SCREEN_TYPE_4DX,
    "SCREENX": SCREEN_TYPE_SCREENX,
    "DOLBY ATMOS": SCREEN_TYPE_DOLBY_ATMOS,
    "돌비 애트모스": SCREEN_TYPE_DOLBY_ATMOS,
}

# CGV rcmGradList gradCd → type
CGV_GRAD_CD_MAP: dict[str, str] = {
    "02": SCREEN_TYPE_4DX,
    "03": SCREEN_TYPE_IMAX,
    "04": SCREEN_TYPE_SCREENX,
    "07": SCREEN_TYPE_DOLBY_ATMOS,
}

# Lotte ScreenDivisionCode → type
LOTTE_SCREEN_TYPE_MAP: dict[str, str] = {
    "100": SCREEN_TYPE_NORMAL,
    "300": SCREEN_TYPE_CHARLOTTE,
    "301": SCREEN_TYPE_CHARLOTTE,  # 샤롯데 프라이빗
    "901": SCREEN_TYPE_PREMIUM,    # 광음시네마
    "902": SCREEN_TYPE_PREMIUM,    # 광음LED
    "940": SCREEN_TYPE_SUPERPLEX,
    "960": SCREEN_TYPE_NORMAL,     # 씨네패밀리
    "980": SCREEN_TYPE_PREMIUM,    # 수퍼LED(일반)
    "986": SCREEN_TYPE_RECLINER,
    "988": SCREEN_TYPE_RECLINER,   # 수퍼LED(리클)
}

# MegaBox theabKindCd → type
MEGABOX_SCREEN_TYPE_MAP: dict[str, str] = {
    "NOR": SCREEN_TYPE_NORMAL,
    "CFT": SCREEN_TYPE_COMFORT,
    "DBC": SCREEN_TYPE_DOLBY_CINEMA,
    "DVA": SCREEN_TYPE_DOLBY_CINEMA,  # Dolby Vision+Atmos
    "LUMINEON": SCREEN_TYPE_PREMIUM,  # MEGA LED
    "MKB": SCREEN_TYPE_PREMIUM,       # 만경관
    "MX": SCREEN_TYPE_DOLBY_ATMOS,
    "MX4D": SCREEN_TYPE_4DX,          # MX4D motion seats
    "RCL": SCREEN_TYPE_RECLINER,
    "TBQ": SCREEN_TYPE_BOUTIQUE,      # 부티크
    "TBS": SCREEN_TYPE_BOUTIQUE,      # 부티크 스위트
}


# ---------------------------------------------------------------------------
# SQLAlchemy base + models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Theater(Base):
    """A cinema theater belonging to a chain."""

    __tablename__ = "theaters"

    chain: Mapped[str] = mapped_column(String, primary_key=True)
    theater_code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, default="")
    address: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float] = mapped_column(Float, default=0.0)
    longitude: Mapped[float] = mapped_column(Float, default=0.0)

    screens: Mapped[list[Screen]] = relationship(
        back_populates="theater",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def key(self) -> str:
        """Unique key across all chains."""
        return f"{self.chain}:{self.theater_code}"

    def __repr__(self) -> str:
        return f"<Theater {self.chain}:{self.theater_code} {self.name}>"


class Screen(Base):
    """A single screen (hall) within a theater."""

    __tablename__ = "screens"

    chain: Mapped[str] = mapped_column(String, primary_key=True)
    theater_code: Mapped[str] = mapped_column(String, primary_key=True)
    screen_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    screen_type: Mapped[str] = mapped_column(String, default="normal")
    seat_count: Mapped[int] = mapped_column(Integer, default=0)
    is_special: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chain", "theater_code"],
            ["theaters.chain", "theaters.theater_code"],
            ondelete="CASCADE",
        ),
    )

    theater: Mapped[Theater] = relationship(back_populates="screens")

    def __repr__(self) -> str:
        return f"<Screen {self.chain}:{self.theater_code}:{self.screen_id} {self.name}>"


class NowPlaying(Base):
    """Movie showtime at a specific theater (populated during daily sync)."""

    __tablename__ = "now_playing"

    chain: Mapped[str] = mapped_column(String, primary_key=True)
    theater_code: Mapped[str] = mapped_column(String, primary_key=True)
    movie_name: Mapped[str] = mapped_column(String, primary_key=True)
    screen_name: Mapped[str] = mapped_column(String, primary_key=True)
    start_time: Mapped[str] = mapped_column(String, primary_key=True)  # "HH:MM"
    screen_type: Mapped[str] = mapped_column(String, default="normal")
    synced_at: Mapped[str] = mapped_column(String, default="")


class SyncMeta(Base):
    """Key-value metadata (e.g. last_sync_at)."""

    __tablename__ = "sync_meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Database manager
# ---------------------------------------------------------------------------


class TheaterDatabase:
    """Theater database with SQLAlchemy ORM + SQLite.

    The public API is kept compatible with callers (sync.py, app.py,
    screen_alert.py).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- read API ----------------------------------------------------------

    @property
    def theaters(self) -> list[Theater]:
        """Return all theaters (with screens eagerly loaded)."""
        stmt = select(Theater).order_by(Theater.chain, Theater.name)
        return list(self._session.scalars(stmt))

    def get(self, chain: str, theater_code: str) -> Theater | None:
        return self._session.get(Theater, (chain, theater_code))

    def get_by_chain(self, chain: str) -> list[Theater]:
        stmt = (
            select(Theater)
            .where(Theater.chain == chain)
            .order_by(Theater.name)
        )
        return list(self._session.scalars(stmt))

    def get_regions(self) -> list[str]:
        """Return all distinct regions, ordered."""
        stmt = (
            select(Theater.region)
            .where(Theater.region != "")
            .distinct()
            .order_by(Theater.region)
        )
        return list(self._session.scalars(stmt))

    def get_by_region(self, region: str) -> list[Theater]:
        """Return all theaters in a given region, sorted by name."""
        stmt = (
            select(Theater)
            .where(Theater.region == region)
            .order_by(Theater.name)
        )
        return list(self._session.scalars(stmt))

    # -- now_playing API ---------------------------------------------------

    def get_now_playing_movies(self) -> set[str]:
        """Return set of all distinct movie names currently playing."""
        stmt = select(NowPlaying.movie_name).distinct()
        return set(self._session.scalars(stmt))

    def find_theaters_playing(self, movie_name: str) -> list[NowPlaying]:
        """Find all now_playing entries for a given movie name."""
        stmt = select(NowPlaying).where(NowPlaying.movie_name == movie_name)
        return list(self._session.scalars(stmt))

    def replace_now_playing(self, entries: list[NowPlaying]) -> None:
        """Replace all now_playing data atomically."""
        self._session.execute(delete(NowPlaying))
        self._session.flush()
        for entry in entries:
            self._session.merge(entry)
        self._session.commit()

    # -- write API ---------------------------------------------------------

    def update_chain(self, chain: str, theaters: list[Theater]) -> None:
        """Replace all theaters for a given chain. Partial-update safe."""
        self._session.execute(
            delete(Screen).where(Screen.chain == chain)
        )
        self._session.execute(
            delete(Theater).where(Theater.chain == chain)
        )
        self._session.flush()

        for t in theaters:
            # Ensure FK columns on child screens are populated
            for s in t.screens:
                s.chain = t.chain
                s.theater_code = t.theater_code
            self._session.merge(t)

        self._session.commit()

    # -- meta --------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._session.get(SyncMeta, key)
        return row.value if row else None

    def set_meta(self, key: str, value: str) -> None:
        obj = self._session.get(SyncMeta, key)
        if obj:
            obj.value = value
        else:
            self._session.add(SyncMeta(key=key, value=value))
        self._session.commit()

    @property
    def last_sync_at(self) -> str:
        return self.get_meta("last_sync_at") or ""

    @last_sync_at.setter
    def last_sync_at(self, value: str) -> None:
        self.set_meta("last_sync_at", value)

    # -- lifecycle ---------------------------------------------------------

    def save(self) -> None:
        """Commit pending changes (kept for API compat)."""
        self._session.commit()

    def close(self) -> None:
        self._session.close()

    # -- factory -----------------------------------------------------------

    @classmethod
    def load(cls) -> TheaterDatabase:
        """Open (or create) the SQLite database.

        Priority:
        1. No data/theaters.db → copy seed if available, otherwise empty
        2. Existing data/theaters.db + newer seed → merge theater data
           from seed (preserves user settings like watched_screens)
        3. Legacy theaters.json → one-time migration
        """
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        if not DB_PATH.exists():
            if SEED_PATH.exists():
                shutil.copy2(SEED_PATH, DB_PATH)
                logger.info("Initialised theaters.db from seed data")

        engine = create_engine(
            f"sqlite:///{DB_PATH}",
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # Enable WAL and foreign keys on every connection
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)

        # Migrate: add 'region' column if missing (SQLAlchemy create_all
        # does not alter existing tables)
        with engine.connect() as conn:
            try:
                conn.execute(select(Theater.region).limit(1))
            except Exception:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE theaters ADD COLUMN region VARCHAR DEFAULT ''"
                    )
                )
                conn.commit()
                logger.info("Migrated theaters table: added region column")

        session = sessionmaker(bind=engine)()

        db = cls(session)

        # Migrate legacy JSON if needed
        if LEGACY_JSON_PATH.exists():
            count = session.scalar(
                select(Theater.chain).limit(1)
            )
            if count is None:
                db._migrate_from_json()
            try:
                LEGACY_JSON_PATH.unlink()
                logger.info("Removed legacy theaters.json")
            except OSError:
                pass

        # Merge from seed if seed is newer
        db._merge_from_seed_if_newer()

        return db

    def _merge_from_seed_if_newer(self) -> None:
        """Merge theater data from seed DB if its sync timestamp is newer,
        or if the local DB is missing region data that the seed has.

        This runs on every startup. If the Docker image ships a newer seed
        (via ``data/seed/theaters.db``), the theater/screen rows are replaced
        while user-side data (settings JSON files) is untouched.
        """
        if not SEED_PATH.exists():
            return

        local_sync = self.get_meta("last_sync_at") or ""
        seed_sync = self._read_seed_sync_at()
        if not seed_sync:
            return

        # Check if local DB is missing region data that seed has
        local_has_regions = self._session.scalar(
            select(Theater.chain).where(Theater.region != "").limit(1)
        ) is not None
        seed_has_regions = self._seed_has_regions()

        needs_merge = False
        if local_sync < seed_sync:
            needs_merge = True
            logger.info(
                "Seed DB is newer (seed=%s, local=%s) — merging theater data",
                seed_sync[:19], local_sync[:19] if local_sync else "none",
            )
        elif not local_has_regions and seed_has_regions:
            needs_merge = True
            logger.info(
                "Local DB missing region data but seed has it — merging",
            )

        if not needs_merge:
            return

        import sqlite3

        seed_conn = sqlite3.connect(str(SEED_PATH))
        seed_conn.row_factory = sqlite3.Row
        try:
            # Read all theaters from seed
            seed_theaters = seed_conn.execute(
                "SELECT chain, theater_code, name, region, address, "
                "latitude, longitude FROM theaters"
            ).fetchall()
            seed_screens = seed_conn.execute(
                "SELECT chain, theater_code, screen_id, name, "
                "screen_type, seat_count, is_special FROM screens"
            ).fetchall()
            # now_playing may not exist in older seeds
            try:
                seed_now_playing = seed_conn.execute(
                    "SELECT chain, theater_code, movie_name, "
                    "screen_name, start_time, screen_type, synced_at "
                    "FROM now_playing"
                ).fetchall()
            except Exception:
                seed_now_playing = []
        finally:
            seed_conn.close()

        # Group screens by (chain, theater_code)
        screen_map: dict[tuple[str, str], list[dict]] = {}
        for row in seed_screens:
            key = (row["chain"], row["theater_code"])
            screen_map.setdefault(key, []).append(dict(row))

        # Replace all theater + screen data
        self._session.execute(delete(Screen))
        self._session.execute(delete(Theater))
        self._session.flush()

        count = 0
        for row in seed_theaters:
            t = Theater(
                chain=row["chain"],
                theater_code=row["theater_code"],
                name=row["name"],
                region=row["region"] or "",
                address=row["address"] or "",
                latitude=float(row["latitude"] or 0),
                longitude=float(row["longitude"] or 0),
            )
            key = (row["chain"], row["theater_code"])
            for s in screen_map.get(key, []):
                t.screens.append(Screen(
                    chain=row["chain"],
                    theater_code=row["theater_code"],
                    screen_id=s["screen_id"],
                    name=s["name"],
                    screen_type=s["screen_type"] or "normal",
                    seat_count=int(s["seat_count"] or 0),
                    is_special=bool(s["is_special"]),
                ))
            self._session.add(t)
            count += 1

        # Merge now_playing data from seed
        if seed_now_playing:
            self._session.execute(delete(NowPlaying))
            self._session.flush()
            for row in seed_now_playing:
                self._session.add(NowPlaying(
                    chain=row["chain"],
                    theater_code=row["theater_code"],
                    movie_name=row["movie_name"],
                    screen_name=row["screen_name"] or "",
                    start_time=row["start_time"] or "",
                    screen_type=row["screen_type"] or "normal",
                    synced_at=row["synced_at"] or "",
                ))
            logger.info(
                "Merged %d now_playing entries from seed DB",
                len(seed_now_playing),
            )

        self.set_meta("last_sync_at", seed_sync)
        self._session.commit()
        logger.info("Merged %d theaters from seed DB", count)

    @staticmethod
    def _read_seed_sync_at() -> str:
        """Read last_sync_at from the seed database."""
        import sqlite3

        try:
            conn = sqlite3.connect(str(SEED_PATH))
            row = conn.execute(
                "SELECT value FROM sync_meta WHERE key = 'last_sync_at'"
            ).fetchone()
            conn.close()
            return row[0] if row else ""
        except Exception:
            return ""

    @staticmethod
    def _seed_has_regions() -> bool:
        """Check if the seed database has any theaters with region data."""
        import sqlite3

        try:
            conn = sqlite3.connect(str(SEED_PATH))
            row = conn.execute(
                "SELECT 1 FROM theaters WHERE region != '' LIMIT 1"
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            return False

    def _migrate_from_json(self) -> None:
        """One-time migration from theaters.json to SQLite."""
        try:
            raw = json.loads(LEGACY_JSON_PATH.read_text(encoding="utf-8"))
            count = 0
            for t_data in raw.get("theaters", []):
                screens_data = t_data.pop("screens", [])
                theater = Theater(**t_data)
                for s_data in screens_data:
                    theater.screens.append(Screen(
                        chain=theater.chain,
                        theater_code=theater.theater_code,
                        **s_data,
                    ))
                self._session.add(theater)
                count += 1

            self._session.add(SyncMeta(
                key="last_sync_at",
                value=datetime.now(timezone.utc).isoformat(),
            ))
            self._session.commit()
            logger.info("Migrated %d theaters from JSON to SQLite", count)
        except Exception:
            self._session.rollback()
            logger.exception("Failed to migrate theaters.json")
