from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlmodel import SQLModel, Field
from typing import Optional, Dict, Any
import json

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, Relationship

# ================================================
# SQLModel table definitions
# ================================================


class User(SQLModel, table=True):
    """
    User account model for authentication and resource ownership.

    Each user owns datasets and vocabularies. Deleting a user cascades
    to delete all their owned resources.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    disabled: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = Field(default=None)

    # Relationships to owned resources
    datasets: list["Dataset"] = Relationship(back_populates="user")
    vocabularies: list["Vocabulary"] = Relationship(back_populates="user")
    refresh_tokens: list["RefreshToken"] = Relationship(back_populates="user")


class RefreshToken(SQLModel, table=True):
    """
    Refresh token model for JWT token refresh flow.

    Refresh tokens allow users to obtain new access tokens without
    re-authenticating. Tokens can be revoked for logout functionality.
    """

    __tablename__ = "refresh_token"

    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", nullable=False)
    expires_at: datetime
    revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationship back to User
    user: Optional["User"] = Relationship(back_populates="refresh_tokens")


class ProcessingStatus(str, Enum):
    """Enum for processing status, used in Vocabulary and Dataset."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"
    DELETED = "DELETED"


class Dataset(SQLModel, table=True):
    """
    Dataset model representing a collection of records.

    Datasets are owned by users and contain records (source terms).
    Deleting a dataset cascades to delete all its records.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    uploaded: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # TODO: need to specify a structure for the labels
    labels: List[str] = Field(sa_column=Column(JSON))
    date_label: Optional[str] = Field(default=None, nullable=True)
    status: ProcessingStatus = Field(default=ProcessingStatus.PROCESSING, index=True)
    error_message: Optional[str] = None

    # Relationship to User (owner)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE", nullable=False)
    user: Optional["User"] = Relationship(back_populates="datasets")

    # Relationship to Records (one-to-many)
    records: list["Record"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    clusters: list["Cluster"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Record(SQLModel, table=True):
    """
    Record model representing a text entry within a dataset.

    Records contain the raw text data and can have multiple extracted
    source terms. Deleting a record cascades to delete all its source terms.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: str
    seq_number: Optional[str] = Field(default=None)
    visit_date: datetime = Field(default=None)
    text: str
    uploaded: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed: bool = Field(default=False)

    # Relationship back to Dataset (many-to-one)
    dataset_id: int = Field(
        foreign_key="dataset.id", ondelete="CASCADE", nullable=False
    )
    dataset: Optional["Dataset"] = Relationship(back_populates="records")

    # Relationship to SourceTerms (one-to-many)
    source_terms: list["SourceTerm"] = Relationship(
        back_populates="record",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    sentence_segments: list["SentenceSegment"] = Relationship(
        back_populates="record",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class SentenceSegment(SQLModel, table=True):
    """Normalized spans representing sentences or line segments within a record."""

    __tablename__ = "sentence_segment"

    id: Optional[int] = Field(default=None, primary_key=True)
    record_id: int = Field(
        foreign_key="record.id", ondelete="CASCADE", nullable=False, index=True
    )
    sequence_index: int = Field(default=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    record: Optional["Record"] = Relationship(back_populates="sentence_segments")
    source_terms: list["SourceTerm"] = Relationship(back_populates="sentence_segment")


class SourceTerm(SQLModel, table=True):
    """
    Source term model representing an extracted term from a record.

    Source terms can be mapped to vocabulary concepts and can have alternative
    terms (self-referencing relationship). Deleting a source term cascades to
    delete all its concept mappings.

    NEW:? check once more
    SourceTerm can now belong to a persistent Cluster (cluster of similar terms).
    This allows stable clustering (no need to rerun HDBSCAN every time)
     and incremental assignment of new terms to existing clusters. (if it is correct :)
    """

    __tablename__ = "source_term"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Term text, "ACL rupture"
    value: str

    # Entity label, category: "Diagnosis", "Procedure"
    label: str

    # Optional character offsets inside the original text
    start_position: Optional[int] = Field(default=None)
    end_position: Optional[int] = Field(default=None)
    score: Optional[float] = Field(default=None)
    automatically_extracted: bool = Field(default=False)

    # Relationship back to Record (many-to-one)
    record_id: int = Field(foreign_key="record.id", ondelete="CASCADE", nullable=False)
    record: Optional["Record"] = Relationship(back_populates="source_terms")

    sentence_segment_id: Optional[int] = Field(
        default=None,
        foreign_key="sentence_segment.id",
        nullable=True,
        ondelete="SET NULL",
    )
    sentence_segment: Optional["SentenceSegment"] = Relationship(
        back_populates="source_terms"
    )

    linked_date_term_id: Optional[int] = Field(
        default=None,
        foreign_key="source_term.id",
        nullable=True,
        ondelete="SET NULL",
    )
    linked_visit_date: Optional[datetime] = Field(default=None)
    manual_linked_visit_date: bool = Field(default=False)

    cluster_id: Optional[int] = Field(
        default=None,
        foreign_key="cluster.id",  # refers to Cluster table
        ondelete="SET NULL",
        nullable=True,
    )

    # Relationship to the Cluster this term belongs to
    cluster: Optional["Cluster"] = Relationship(back_populates="source_terms")


class Cluster(SQLModel, table=True):
    """
    Cluster model representing a cluster of similar source terms.

    A cluster belongs to one dataset and one entity label (e.g. 'Diagnosis').
    Deleting a cluster cascades to delete all its mappings, but not the source terms.
    """

    __tablename__ = "cluster"

    id: Optional[int] = Field(default=None, primary_key=True)

    # label/category: Diagnosis, Procedure, BodyPart...
    label: str

    # human-readable cluster name (default = first term in cluster)
    title: str

    # whether the cluster has been reviewed (clustering step complete)
    reviewed: bool = Field(default=False)

    # dataset this cluster belongs to
    dataset_id: int = Field(foreign_key="dataset.id", nullable=False, index=True)
    dataset: Optional["Dataset"] = Relationship(back_populates="clusters")

    # list of terms that belong to this cluster
    source_terms: list["SourceTerm"] = Relationship(back_populates="cluster")

    # Relationship to SourceToConceptMap (one-to-many)
    mapping: list["SourceToConceptMap"] = Relationship(
        back_populates="cluster",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ClusterMergeSuggestion(SQLModel, table=True):
    """
    Suggestion for merging two clusters.
    """

    __tablename__ = "cluster_merge_suggestion"

    id: Optional[int] = Field(default=None, primary_key=True)

    dataset_id: int = Field(foreign_key="dataset.id", nullable=False, index=True)
    label: str = Field(index=True)

    cluster_a_id: int = Field(foreign_key="cluster.id", nullable=False, index=True)
    cluster_b_id: int = Field(foreign_key="cluster.id", nullable=False, index=True)

    score: float = Field(default=0.0)  # similarity score (e.g. cosine)
    method: str = Field(default="centroid")  # "centroid" or "spelling"

    status: str = Field(default="pending", index=True)  # pending/accepted/rejected

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = Field(default=None)

    reviewed_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")


class ExtractionJob(SQLModel, table=True):
    """
    Tracks progress for dataset-wide extraction runs.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    dataset_id: int = Field(
        foreign_key="dataset.id", ondelete="CASCADE", nullable=False, index=True
    )

    total: int = Field(default=0)
    completed: int = Field(default=0)
    status: str = Field(
        default="pending", index=True
    )  # pending|running|completed|failed
    error_message: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Vocabulary(SQLModel, table=True):
    """
    Vocabulary model representing a standardized terminology system.

    Vocabularies are owned by users and contain concepts that can be mapped
    to source terms. Deleting a vocabulary cascades to delete all its concepts.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    uploaded: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ProcessingStatus = Field(default=ProcessingStatus.PROCESSING, index=True)
    error_message: Optional[str] = None

    # Relationship to User (owner)
    user_id: int = Field(
        foreign_key="user.id", ondelete="CASCADE", nullable=False, index=True
    )
    user: Optional["User"] = Relationship(back_populates="vocabularies")

    # Relationship to Concepts (one-to-many)
    concepts: list["Concept"] = Relationship(
        back_populates="vocabulary",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Concept(SQLModel, table=True):
    """
    Concept model representing a standardized term within a vocabulary.

    Concepts belong to vocabularies and can be mapped to source terms.
    Deleting a concept cascades to delete all its source term mappings.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    vocab_term_id: str
    vocab_term_name: str
    domain_id: str
    concept_class_id: str
    standard_concept: Optional[str]
    concept_code: Optional[str]
    valid_start_date: datetime
    valid_end_date: datetime
    invalid_reason: Optional[str]

    # Relationship back to Vocabulary (many-to-one)
    vocabulary_id: int = Field(
        foreign_key="vocabulary.id", ondelete="CASCADE", nullable=False, index=True
    )
    vocabulary: Optional["Vocabulary"] = Relationship(back_populates="concepts")

    # Relationship to SourceToConceptMap (one-to-many)
    mapping: list["SourceToConceptMap"] = Relationship(
        back_populates="concept",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class SourceToConceptMap(SQLModel, table=True):
    """
    Junction table mapping source terms to vocabulary concepts.

    This many-to-many relationship table connects source terms extracted
    from records to standardized concepts in vocabularies. Mappings are
    automatically deleted when either the source term or concept is deleted.
    """

    __tablename__ = "source_to_concept_map"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Relationship back to Cluster (many-to-one)
    cluster_id: int = Field(
        foreign_key="cluster.id", ondelete="CASCADE", nullable=False, index=True
    )
    cluster: Optional["Cluster"] = Relationship(back_populates="mapping")

    # Relationship back to Concept (many-to-one)
    concept_id: int = Field(
        foreign_key="concept.id", ondelete="CASCADE", nullable=False, index=True
    )
    concept: Optional["Concept"] = Relationship(back_populates="mapping")

    # Mapping status and metadata
    status: str = Field(
        default="pending", index=True
    )  # 'pending', 'approved', 'rejected'
    comment: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TrainingMetric(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    run_id: int
    epoch: int

    loss: float
    precision: float
    recall: float
    f1: float


class TrainingRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    dataset_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TrainingEvaluation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    run_id: int = Field(foreign_key="trainingrun.id")

    precision: float
    recall: float
    f1: float

    per_label: dict = Field(sa_column=Column(JSON))

    per_label: dict = Field(sa_column=Column(JSON))

class ModelArtifact(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    run_id: int
    dataset_id: int

    model_path: str
    f1_score: float
    precision: float
    recall: float

    created_at: datetime = Field(default_factory=datetime.utcnow)


