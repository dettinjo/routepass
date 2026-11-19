from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from routepass.timeutil import utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class Activity(Base):
    """One real-world activity, deduplicated across providers.

    Every provider record (Strava activity, Komoot tour) links to exactly one Activity.
    All analysis runs over this table, so an activity recorded on both platforms counts once.
    """

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, naive
    start_local: Mapped[datetime | None] = mapped_column(DateTime)  # wall clock where recorded
    timezone: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sport: Mapped[str] = mapped_column(String(40), index=True)  # Strava sport_type vocabulary
    family: Mapped[str] = mapped_column(String(20), index=True)  # ride | run | walk | winter | water | other

    distance_m: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[float | None] = mapped_column(Float)
    elapsed_time_s: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    elevation_max_m: Mapped[float | None] = mapped_column(Float)
    avg_speed_ms: Mapped[float | None] = mapped_column(Float)
    max_speed_ms: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    avg_power: Mapped[float | None] = mapped_column(Float)
    normalized_power: Mapped[float | None] = mapped_column(Float)
    max_power: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    avg_temp: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    work_kj: Mapped[float | None] = mapped_column(Float)
    load: Mapped[float | None] = mapped_column(Float)  # TSS (power) or hrTSS / estimated
    load_method: Mapped[str | None] = mapped_column(String(20))
    intensity: Mapped[float | None] = mapped_column(Float)

    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lng: Mapped[float | None] = mapped_column(Float)
    end_lat: Mapped[float | None] = mapped_column(Float)
    end_lng: Mapped[float | None] = mapped_column(Float)
    polyline: Mapped[str | None] = mapped_column(Text)  # Google encoded, simplified

    trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    commute: Mapped[bool] = mapped_column(Boolean, default=False)
    device: Mapped[str | None] = mapped_column(String(120))
    gear: Mapped[str | None] = mapped_column(String(120))

    has_track: Mapped[bool] = mapped_column(Boolean, default=False)
    track_provider: Mapped[str | None] = mapped_column(String(20))
    sync_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # never sync this one

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sources: Mapped[list[ProviderActivity]] = relationship(back_populates="activity")


class ProviderActivity(Base):
    __tablename__ = "provider_activities"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # strava | komoot
    external_id: Mapped[str] = mapped_column(String(40))
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(300), default="")
    sport: Mapped[str] = mapped_column(String(40))  # provider-native sport key
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    distance_m: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    # Set when RoutePass itself created this record by syncing from the other provider.
    created_by_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when the user linked/unlinked this record by hand; auto-matching leaves it alone.
    match_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    track_status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|done|none|error
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    activity: Mapped[Activity | None] = relationship(back_populates="sources")


class Track(Base):
    """Full-resolution recording (compressed) plus derived detail for one activity."""

    __tablename__ = "tracks"

    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(20))
    data: Mapped[bytes] = mapped_column(LargeBinary)  # zlib(json) of normalized channels
    points: Mapped[bytes | None] = mapped_column(LargeBinary)  # zlib(columnar json) chart series
    detail: Mapped[dict] = mapped_column(JSON, default=dict)  # zones, splits, climbs, decoupling
    channels: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Effort(Base):
    """Best efforts per activity — power curve points and fastest distances.

    kind = power (key = seconds, value = watts) | time (key = metres, value = seconds)
         | climb (key = 0, value = metres of the largest continuous climb)
    """

    __tablename__ = "efforts"
    __table_args__ = (Index("ix_efforts_kind_key", "kind", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    key: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)


class SyncRule(Base):
    __tablename__ = "sync_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(20))  # strava_to_komoot | komoot_to_strava
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower runs first
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    actions: Mapped[dict] = mapped_column(JSON, default=dict)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_jobs_status_next", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    source_provider: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(40))
    target_provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|done|failed|skipped
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("sync_rules.id", ondelete="SET NULL"))
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # name, sport, description, flags to apply
    reason: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    target_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20))  # schedule | manual | api | mcp
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running|ok|partial|error
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[list] = mapped_column(JSON, default=list)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TrainingPlan(Base):
    """Multi-sport adaptive training plan (trail run, road run, cycling, triathlon, duathlon, base)."""

    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|completed|archived
    plan_type: Mapped[str] = mapped_column(String(24), default="trail_run")
    start_date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (Monday of week 1)
    event_date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    goal_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    schedule_prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    coach_summary: Mapped[str] = mapped_column(Text, default="")
    last_adapted_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    weeks: Mapped[list[TrainingWeek]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="TrainingWeek.week_index"
    )
    sessions: Mapped[list[TrainingSession]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="TrainingSession.scheduled_date"
    )
    adaptations: Mapped[list[PlanAdaptation]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanAdaptation.created_at.desc()"
    )


class TrainingWeek(Base):
    __tablename__ = "training_weeks"
    __table_args__ = (UniqueConstraint("plan_id", "week_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    week_index: Mapped[int] = mapped_column(Integer)  # 1-based
    start_date: Mapped[str] = mapped_column(String(10))  # Monday ISO YYYY-MM-DD
    phase: Mapped[str] = mapped_column(String(20), default="base")  # base|build|peak|taper|race_week|recovery
    target_tss: Mapped[float] = mapped_column(Float, default=0.0)
    target_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    target_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    target_elev_m: Mapped[float] = mapped_column(Float, default=0.0)
    discipline_split: Mapped[dict] = mapped_column(JSON, default=dict)
    coach_focus: Mapped[str] = mapped_column(Text, default="")

    plan: Mapped[TrainingPlan] = relationship(back_populates="weeks")
    sessions: Mapped[list[TrainingSession]] = relationship(
        back_populates="week", cascade="all, delete-orphan", order_by="TrainingSession.scheduled_date"
    )


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (Index("ix_training_sessions_plan_date", "plan_id", "scheduled_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("training_weeks.id", ondelete="CASCADE"), index=True)
    scheduled_date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    scheduled_slot: Mapped[str] = mapped_column(String(16), default="flexible")  # morning|midday|afternoon|evening|flexible
    scheduled_start: Mapped[str | None] = mapped_column(String(32))  # ISO datetime when placed on calendar
    scheduled_end: Mapped[str | None] = mapped_column(String(32))
    sport: Mapped[str] = mapped_column(String(20), default="run")  # run|trail_run|bike|swim|strength|brick|rest
    session_type: Mapped[str] = mapped_column(String(20), default="easy")  # easy|long|tempo|intervals|hills|brick|recovery|race
    priority: Mapped[str] = mapped_column(String(12), default="supporting")  # key|supporting|optional
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    workout_steps: Mapped[list] = mapped_column(JSON, default=list)
    target_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    target_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    target_elev_m: Mapped[float] = mapped_column(Float, default=0.0)
    target_tss: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|completed|partial|missed|moved|skipped
    matched_activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL"), index=True
    )
    compliance_score: Mapped[float | None] = mapped_column(Float)
    gcal_event_id: Mapped[str | None] = mapped_column(String(160))
    adaptation_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    plan: Mapped[TrainingPlan] = relationship(back_populates="sessions")
    week: Mapped[TrainingWeek] = relationship(back_populates="sessions")


class PlanAdaptation(Base):
    __tablename__ = "plan_adaptations"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    model_used: Mapped[str] = mapped_column(String(64), default="deterministic")
    summary: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[list] = mapped_column(JSON, default=list)

    plan: Mapped[TrainingPlan] = relationship(back_populates="adaptations")


class AIUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    feature: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(600), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


