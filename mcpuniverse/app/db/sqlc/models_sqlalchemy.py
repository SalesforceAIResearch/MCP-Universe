import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean,
    DateTime, Text, ForeignKey, Float
)
from sqlalchemy.orm import relationship
from mcpuniverse.app.db.database import Base


# SQLAlchemy Models
class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    permission = Column(String, default="default")
    is_email_verified = Column(Boolean, default=False)
    password_changed_at = Column(DateTime, default=datetime.datetime.now)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)


class Benchmark(Base):
    __tablename__ = "benchmark"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)


class Project(Base):
    __tablename__ = "project"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    configuration = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)


class Task(Base):
    __tablename__ = "task"

    id = Column(Integer, primary_key=True)
    benchmark_id = Column(Integer, ForeignKey('benchmark.id'), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String)
    question = Column(Text)
    data = Column(Text)
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)

    benchmark = relationship("Benchmark")


class ReleasedBenchmark(Base):
    __tablename__ = "released_benchmark"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    tag = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)


class ReleasedProject(Base):
    __tablename__ = "released_project"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    tag = Column(String, nullable=False)
    description = Column(Text)
    configuration = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.now)


class ReleasedTask(Base):
    __tablename__ = "released_task"

    id = Column(Integer, primary_key=True)
    benchmark_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    tag = Column(String, nullable=False)
    category = Column(String)
    question = Column(Text)
    data = Column(Text)
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.now)


class BenchmarkJob(Base):
    __tablename__ = "benchmark_job"

    id = Column(Integer, primary_key=True)
    job_id = Column(String, nullable=False)
    owner_id = Column(Integer, nullable=False)
    benchmark_id = Column(Integer, nullable=False)
    project_id = Column(Integer, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    results = Column(String, default="")
    score = Column(Float, default=0)
    celery_id = Column(String, default="")
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
