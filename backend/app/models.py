from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class Project(db.Model):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    targets = relationship(
        "TargetApplication", back_populates="project", cascade="all, delete-orphan"
    )


class TargetApplication(db.Model):
    __tablename__ = "target_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="targets")
    campaigns = relationship(
        "TestCampaign", back_populates="target", cascade="all, delete-orphan"
    )


class TestCampaign(db.Model):
    __tablename__ = "test_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_application_id: Mapped[int] = mapped_column(
        ForeignKey("target_applications.id", ondelete="CASCADE"), nullable=False
    )
    objective: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="created")
    # created | exploring | explored | generating | scenarios_ready |
    # executing | completed | failed
    task_stage: Mapped[str | None] = mapped_column(String(50))
    task_message: Mapped[str | None] = mapped_column(Text)
    task_progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    configuration_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    target = relationship("TargetApplication", back_populates="campaigns")
    pages = relationship(
        "ExplorationPage", back_populates="campaign", cascade="all, delete-orphan"
    )
    scenarios = relationship(
        "TestScenario", back_populates="campaign", cascade="all, delete-orphan"
    )


class ExplorationPage(db.Model):
    __tablename__ = "exploration_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("test_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    discovered_elements: Mapped[list] = mapped_column(JSON, default=list)
    exploration_status: Mapped[str] = mapped_column(String(30), default="visited")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    console_errors: Mapped[list] = mapped_column(JSON, default=list)
    failed_requests: Mapped[list] = mapped_column(JSON, default=list)
    visited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    campaign = relationship("TestCampaign", back_populates="pages")


class TestScenario(db.Model):
    __tablename__ = "test_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("test_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    preconditions: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | approved | modified | disabled | deleted
    kind: Mapped[str] = mapped_column(String(20), default="positive")
    source: Mapped[str] = mapped_column(String(20), default="observed")
    # observed | hypothesis
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    campaign = relationship("TestCampaign", back_populates="scenarios")
    steps = relationship(
        "TestStep",
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="TestStep.step_order",
    )
    result = relationship(
        "TestResult", back_populates="scenario", uselist=False, cascade="all, delete-orphan"
    )


class TestStep(db.Model):
    __tablename__ = "test_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("test_scenarios.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_observation: Mapped[str | None] = mapped_column(Text)

    scenario = relationship("TestScenario", back_populates="steps")


class TestResult(db.Model):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("test_scenarios.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="SKIPPED")
    actual_result: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    step_outcomes: Mapped[list] = mapped_column(JSON, default=list)
    analysis: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    scenario = relationship("TestScenario", back_populates="result")
    evidences = relationship(
        "Evidence", back_populates="result", cascade="all, delete-orphan"
    )


class Evidence(db.Model):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_result_id: Mapped[int] = mapped_column(
        ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # screenshot | log | trace | network | video
    file_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_metadata: Mapped[dict] = mapped_column(JSON, default=dict, name="metadata")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    result = relationship("TestResult", back_populates="evidences")
