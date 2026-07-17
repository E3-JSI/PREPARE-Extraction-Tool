import re
from math import ceil
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models_db import Record, Concept, SourceTerm, Cluster, ProcessingStatus


# ================================================
# Label relation models
# ================================================


class LabelRelation(BaseModel):
    """A directed 'has value' relation between two label types in a dataset."""

    from_label: str
    to_label: str


# ================================================
# Source term link models
# ================================================


class SourceTermLinkCreate(BaseModel):
    """Request body for creating a link between two source terms."""

    from_term_id: int
    to_term_id: int


class SourceTermLinkResponse(BaseModel):
    """Response model for a source term link, embedding both term values for display."""

    id: int
    from_term_id: int
    to_term_id: int
    from_term_value: str
    to_term_value: str
    from_term_label: str
    to_term_label: str


# ================================================
# Generic response models
# ================================================


class MessageOutput(BaseModel):
    """Generic message response for simple API responses."""

    message: str


class ExtractionJobStartResponse(BaseModel):
    """Response when a dataset extraction job is queued."""

    job_id: int
    dataset_id: int
    total: int
    status: str


class ExtractionJobStatusResponse(BaseModel):
    """Progress snapshot for a dataset extraction job."""

    job_id: int
    dataset_id: int
    total: int
    completed: int
    status: str
    error_message: Optional[str] = None


class ClusterJobStartResponse(BaseModel):
    """Response when a dataset "cluster all labels" job is queued."""

    job_id: int
    dataset_id: int
    total: int
    status: str


class ClusterJobStatusResponse(BaseModel):
    """Progress snapshot for a dataset cluster-all job (progress unit = labels)."""

    job_id: int
    dataset_id: int
    total: int
    completed: int
    status: str
    clustered_labels: List[str] = []
    skipped_labels: List[str] = []
    error_message: Optional[str] = None


class LiveEvalStartRequest(BaseModel):
    """Request body to start a user-triggered live evaluation run."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: int
    dataset_id: int


class LiveEvalJobStartResponse(BaseModel):
    """Response when a live-eval job is queued (or completed immediately)."""

    model_config = ConfigDict(protected_namespaces=())

    job_id: int
    dataset_id: int
    model_id: int
    total: int
    status: str
    # Set when the job short-circuits (e.g. no held-out reviewed records).
    message: Optional[str] = None


class LiveEvalJobStatusResponse(BaseModel):
    """Progress snapshot for a live-eval job, with metrics once computed."""

    model_config = ConfigDict(protected_namespaces=())

    job_id: int
    dataset_id: int
    model_id: int
    total: int
    completed: int
    status: str
    error_message: Optional[str] = None
    # Computed metrics: per-label exact/relaxed/overlap P/R/F1 + macro aggregate,
    # held-out count, and a message for the empty-set case. Null until computed.
    metrics: Optional[Dict[str, Any]] = None


# ================================================
# Pagination models
# ================================================


class PaginationMetadata(BaseModel):
    """Metadata for paginated responses."""

    total: int
    limit: int
    offset: int
    page: int
    total_pages: int


class PaginationParams:
    """Dependency for pagination query parameters."""

    def __init__(
        self,
        limit: int = Query(50, ge=1, description="Number of items per page"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
        page: Optional[int] = Query(
            None, ge=1, description="Page number (overrides offset)"
        ),
    ):
        # Calculate offset from page if provided
        if page is not None:
            self.offset = (page - 1) * limit
            self.page = page
        else:
            self.offset = offset
            self.page = (offset // limit) + 1 if limit > 0 else 1

        self.limit = limit


def create_pagination_metadata(
    total: int, limit: int, offset: int
) -> PaginationMetadata:
    """Helper function to create pagination metadata."""
    current_page = (offset // limit) + 1 if limit > 0 else 1
    total_pages = ceil(total / limit) if limit > 0 else 0

    return PaginationMetadata(
        total=total,
        limit=limit,
        offset=offset,
        page=current_page,
        total_pages=total_pages,
    )


# ================================================
# User models
# ================================================


class UserModel(BaseModel):
    """Base user model for internal use."""

    username: str
    disabled: bool = False


class UserRegister(BaseModel):
    """Model for user registration with validation."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username contains only alphanumeric characters and underscores."""
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username must contain only letters, numbers, and underscores"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password meets complexity requirements."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")

        # Check for at least one uppercase, one lowercase, and one digit
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")

        return v


class UserResponse(BaseModel):
    """Model for user API responses (excludes sensitive data)."""

    id: int
    username: str
    disabled: bool
    created_at: datetime
    last_login: Optional[datetime] = None


class UserStatsResponse(BaseModel):
    """Model for user statistics response."""

    dataset_count: int
    vocabulary_count: int


# ================================================
# Dataset models
# ================================================


class DatasetCreate(BaseModel):
    """Model for creating a new dataset with optional records."""

    name: str
    labels: List[str] = Field(default_factory=list)
    label_relations: List[LabelRelation] = Field(default_factory=list)
    date_label: Optional[str] = None
    records: List["RecordCreate"] = Field(default_factory=list)


class DatasetUploadResponse(BaseModel):
    status: ProcessingStatus
    message: str


class DatasetResponse(BaseModel):
    """Model for dataset API responses with metadata."""

    id: int
    name: str
    uploaded: datetime
    last_modified: datetime
    labels: List[str]
    label_relations: List[LabelRelation] = Field(default_factory=list)
    date_label: Optional[str] = None
    status: ProcessingStatus
    error_message: Optional[str] = None
    record_count: int


class DatasetOutput(BaseModel):
    """Wrapper for single dataset response."""

    dataset: DatasetResponse


class DatasetsOutput(BaseModel):
    """Wrapper for paginated list of datasets."""

    datasets: List[DatasetResponse]
    pagination: PaginationMetadata


class DatasetStatisticsResponse(BaseModel):
    """Model for dataset statistics."""

    total_records: int
    processed_count: int
    pending_review_count: int
    extracted_terms_count: int


class ClusteringStatsResponse(BaseModel):
    """Model for clustering statistics."""

    total_clusters: int
    clustered_terms: int
    unclustered_terms: int


class MappingStatsResponse(BaseModel):
    """Model for concept mapping statistics."""

    total_clusters: int
    mapped_clusters: int
    unmapped_clusters: int


class DatasetOverviewResponse(BaseModel):
    """Model for comprehensive dataset overview with all statistics."""

    dataset: DatasetResponse
    stats: DatasetStatisticsResponse
    clustering_stats: ClusteringStatsResponse
    mapping_stats: MappingStatsResponse


# ================================================
# Record models
# ================================================


class RecordCreate(BaseModel):
    """Model for creating a new record (source term)."""

    patient_id: str
    seq_number: Optional[str] = None
    visit_date: Optional[datetime] = None
    text: str


class RecordResponse(BaseModel):
    """Model for record API responses with metadata."""

    id: int
    patient_id: str
    seq_number: Optional[str] = None
    visit_date: Optional[datetime] = None
    text: str
    uploaded: datetime
    dataset_id: int
    reviewed: bool
    source_term_count: int = 0


class RecordOutput(BaseModel):
    """Wrapper for single record response."""

    record: Record


class RecordsOutput(BaseModel):
    """Wrapper for paginated list of records."""

    records: List[RecordResponse]
    pagination: PaginationMetadata


# ================================================
# Vocabulary models
# ================================================


class VocabularyCreate(BaseModel):
    """Model for creating a new vocabulary with concepts."""

    name: str
    concepts: List["ConceptCreate"] = Field(default_factory=list)


class VocabularyUploadResponse(BaseModel):
    status: ProcessingStatus
    message: str


class VocabularyResponse(BaseModel):
    """Model for vocabulary API responses with metadata."""

    id: int
    name: str
    uploaded: datetime
    concept_count: Optional[int] = None
    status: ProcessingStatus
    error_message: Optional[str] = None


class VocabularyOutput(BaseModel):
    """Wrapper for single vocabulary response."""

    vocabulary: VocabularyResponse


class ProcessingVocabularyStats(BaseModel):
    """Model for tracking vocabulary progress during processing."""

    processing_vocabularies: int
    total_concepts: int


class VocabulariesOutput(BaseModel):
    """Wrapper for paginated list of vocabularies."""

    vocabularies: List[VocabularyResponse]
    pagination: PaginationMetadata


# ================================================
# Concept models
# ================================================


class ConceptCreate(BaseModel):
    """Model for creating a new concept within a vocabulary."""

    vocab_term_id: str
    vocab_term_name: str
    domain_id: str
    concept_class_id: str
    standard_concept: Optional[str] = None
    concept_code: Optional[str] = None
    valid_start_date: datetime
    valid_end_date: datetime
    invalid_reason: Optional[str] = None


class ConceptOutput(BaseModel):
    """Wrapper for single concept response."""

    concept: Concept


class ConceptsOutput(BaseModel):
    """Wrapper for paginated list of concepts."""

    concepts: List[Concept]
    pagination: PaginationMetadata


# ================================================
# Source term models
# ================================================


class SourceTermCreate(BaseModel):
    """Model for creating a source term."""

    value: str
    label: str
    start_position: Optional[int] = None
    end_position: Optional[int] = None


class SourceTermUpdate(BaseModel):
    """Model for updating a source term."""

    label: Optional[str] = None
    linked_visit_date: Optional[datetime] = None


class SourceTermResponse(BaseModel):
    """Source term with its entity links included for display."""

    id: int
    value: str
    label: str
    start_position: Optional[int] = None
    end_position: Optional[int] = None
    score: Optional[float] = None
    automatically_extracted: bool = False
    record_id: int
    linked_visit_date: Optional[datetime] = None
    manual_linked_visit_date: bool = False
    linked_date_term_id: Optional[int] = None
    cluster_id: Optional[int] = None
    links: List[SourceTermLinkResponse] = Field(default_factory=list)


class SourceTermOutput(BaseModel):
    """Wrapper for single source term response."""

    source_term: SourceTerm


class SourceTermsOutput(BaseModel):
    """Wrapper for paginated list of source terms (with entity links embedded)."""

    source_terms: List[SourceTermResponse]
    pagination: PaginationMetadata


# ================================================
# Clustering response models
# ================================================


class ClusterCreate(BaseModel):
    """Create new empty cluster manually"""

    label: str
    title: str


class ClusterMerge(BaseModel):
    """Merge multiple clusters"""

    cluster_ids: List[int] = Field(min_length=2)
    new_title: str


class ClusterReviewLabelRequest(BaseModel):
    """Request body for bulk review/unreview by label."""

    label: str


class ClustersOutput(BaseModel):
    clusters: List[Cluster]


class ClusterOutput(BaseModel):
    cluster: Cluster


class ClusteredTerm(BaseModel):
    term_id: int
    text: str
    frequency: int
    n_records: int
    record_ids: List[int]


class ClusterResponse(BaseModel):
    id: int
    dataset_id: int
    label: str
    title: str
    total_terms: int
    total_occurrences: int
    unique_records: int
    terms: List[ClusteredTerm]


class ClustersStatisticsOutput(BaseModel):
    clusters: List[ClusterResponse]
    unclustered_terms: List[ClusteredTerm]
    total_number_terms: int
    labels: List[str]
    label_reviewed: bool = False


class ClusterShort(BaseModel):
    id: int
    title: str
    label: str
    dataset_id: int


class MergeSuggestionResponse(BaseModel):
    id: int
    dataset_id: int
    label: str
    method: str
    score: float
    status: str
    created_at: datetime

    cluster_a: ClusterShort
    cluster_b: ClusterShort


class MergeSuggestionsOutput(BaseModel):
    suggestions: List[MergeSuggestionResponse]


# ================================================
# Mapping models
# ================================================


class TermToClusterMapping(BaseModel):
    """Mapping of a source term to a cluster"""

    term_id: int
    cluster_id: int


class BatchTermToClusterMapping(BaseModel):
    """Bulk term to cluster mappings"""

    mappings: List[TermToClusterMapping]


class MapRequest(BaseModel):
    """Request model for mapping source terms to vocabularies."""

    vocabulary_ids: List[int]


# ================================================
# Cluster to Concept Mapping models
# ================================================


class ConceptSearchRequest(BaseModel):
    """Request model for searching concepts"""

    query: str
    vocabulary_ids: List[int]
    domain_id: Optional[str] = None
    concept_class_id: Optional[str] = None
    standard_concept: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


class ConceptSearchResult(BaseModel):
    """Search result with concept and match score"""

    concept: Concept
    score: float
    vocabulary_name: str


class ConceptSearchResults(BaseModel):
    """List of concept search results with pagination"""

    results: List[ConceptSearchResult]
    total: int
    pagination: Optional[PaginationMetadata] = None


class ClusterMappingResponse(BaseModel):
    """Response model for cluster mapping information"""

    cluster_id: int
    cluster_title: str
    cluster_label: str
    cluster_term_count: int
    cluster_total_occurrences: int
    concept_id: Optional[int] = None
    concept_term_id: Optional[str] = None
    concept_term_name: Optional[str] = None
    concept_code: Optional[str] = None
    concept_domain: Optional[str] = None
    concept_class: Optional[str] = None
    vocabulary_id: Optional[int] = None
    vocabulary_name: Optional[str] = None
    status: str = "unmapped"  # 'unmapped', 'pending', 'approved', 'rejected'
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ClusterMappingsOutput(BaseModel):
    """Output model for list of cluster mappings"""

    mappings: List[ClusterMappingResponse]
    total_clusters: int
    mapped_count: int
    unmapped_count: int
    approved_count: int


class AutoMapRequest(BaseModel):
    """Request model for auto-mapping clusters"""

    vocabulary_ids: List[int]
    use_cluster_terms: bool = True
    domain_id: Optional[str] = None
    concept_class_id: Optional[str] = None
    standard_concept: Optional[str] = None
    search_type: str = "hybrid"  # "vector" or "hybrid"


class MapClusterRequest(BaseModel):
    """Request model for manually mapping a cluster to a concept"""

    concept_id: int
    status: str = "pending"  # 'pending', 'approved', 'rejected'
    comment: Optional[str] = None


class AutoMapAllRequest(BaseModel):
    """Request model for bulk auto-mapping"""

    vocabulary_ids: List[int]
    label: Optional[str] = None
    use_cluster_terms: bool = True
    search_type: str = "vector"  # "vector" or "hybrid"


class MappingJobStartResponse(BaseModel):
    """Response when an auto-map-all job is queued."""

    job_id: int
    dataset_id: int
    total: int
    status: str


class MappingJobStatusResponse(BaseModel):
    """Progress snapshot for an auto-map-all job."""

    job_id: int
    dataset_id: int
    total: int
    completed: int
    mapped_count: int
    failed_count: int
    status: str
    error_message: Optional[str] = None


class ConceptHierarchy(BaseModel):
    """Concept with its hierarchical relationships"""

    concept: Concept
    parents: List[Concept] = Field(default_factory=list)
    children: List[Concept] = Field(default_factory=list)
    related_concepts: List[Concept] = Field(default_factory=list)


class MappingExportRequest(BaseModel):
    """Request model for exporting mappings"""

    status_filter: Optional[str] = (
        None  # 'approved', 'pending', 'rejected', None for all
    )


class DistinctValuesOutput(BaseModel):
    """Response model for distinct filter values (domains, concept classes)."""

    values: List[str]


# ================================================
# Training / monitoring schemas
# ================================================


class GLiNERTrainingRequest(BaseModel):
    """Request body to start a GLiNER training run.

    Multiple datasets can be selected for training, and (optionally) a separate
    set of datasets for evaluation. The legacy single ``dataset_id`` field is
    still accepted for backward compatibility and folded into ``dataset_ids``.

    Constraints (enforced as 422 on invalid input): at least one training
    dataset, at least one label, a validation split in [0, 1), and
    hyperparameters in valid ranges (epochs >= 1, learning rate > 0, batch >= 1).
    """

    # Legacy single-dataset field; folded into ``dataset_ids`` if provided.
    dataset_id: Optional[int] = None
    dataset_ids: List[int] = Field(default_factory=list)
    eval_dataset_ids: List[int] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list, min_length=1)
    base_model: str = "urchade/gliner_small-v2.1"
    val_ratio: float = Field(default=0.1, ge=0, lt=1)
    # Hyperparameters (defaults match the bioner trainer's current values).
    num_epochs: int = Field(default=4, ge=1)
    learning_rate: float = Field(default=5e-6, gt=0)
    train_batch_size: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def _resolve_dataset_ids(self) -> "GLiNERTrainingRequest":
        """Fold the legacy ``dataset_id`` into ``dataset_ids`` and require >= 1.

        Duplicate ids are removed while preserving order; the first id becomes
        the run's primary training dataset.
        """
        ids = list(self.dataset_ids)
        if self.dataset_id is not None and self.dataset_id not in ids:
            ids.insert(0, self.dataset_id)
        # de-duplicate, preserve order
        seen: set = set()
        self.dataset_ids = [i for i in ids if not (i in seen or seen.add(i))]
        if not self.dataset_ids:
            raise ValueError("at least one training dataset is required")
        # eval datasets that are also training datasets are redundant; drop them
        train_set = set(self.dataset_ids)
        eval_seen: set = set()
        self.eval_dataset_ids = [
            i
            for i in self.eval_dataset_ids
            if i not in train_set and not (i in eval_seen or eval_seen.add(i))
        ]
        return self


class TrainingStartResponse(BaseModel):
    run_id: int


class TrainingRunSummary(BaseModel):
    """A training run with the metadata needed to compare/manage runs."""

    model_config = ConfigDict(protected_namespaces=())

    run_id: int
    status: str
    name: Optional[str] = None
    base_model: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    val_ratio: Optional[float] = None
    created_at: Optional[datetime] = None
    error_message: Optional[str] = None
    # Path to the trained model artifact (from the linked Model), if any.
    path: Optional[str] = None
    # Id of the linked trained Model, used to select it for extraction (if any).
    model_id: Optional[int] = None
    # Overall macro-F1 across labels, computed from the run's evaluation (if available).
    score: Optional[float] = None
    preferred: bool = False


class TrainingRunUpdate(BaseModel):
    """Partial update for a training run (rename / designate as preferred)."""

    name: Optional[str] = None
    preferred: Optional[bool] = None


class TrainingRunsOutput(BaseModel):
    """Paginated list of training runs for a dataset."""

    runs: List[TrainingRunSummary]
    pagination: PaginationMetadata


class RunEvaluationResponse(BaseModel):
    run_id: int
    per_label: Dict[str, Dict[str, Any]]


class ErrorSpan(BaseModel):
    """A gold or predicted span within an example error's context text."""

    text: str
    start: int
    end: int
    label: str


class ErrorExample(BaseModel):
    """One concrete per-label error: a context snippet with a gold and/or predicted span.

    A false negative carries a ``gold`` span (missed) with no ``predicted``; a
    false positive carries a ``predicted`` span (wrong) with no ``gold``.
    """

    text: str
    gold: Optional[ErrorSpan] = None
    predicted: Optional[ErrorSpan] = None


class LabelErrorAnalysis(BaseModel):
    """Per-label confusion summary plus a bounded sample of example errors."""

    precision: Optional[float] = None
    recall: Optional[float] = None
    fp: Optional[int] = None
    fn: Optional[int] = None
    examples: List[ErrorExample] = Field(default_factory=list)


class RunErrorAnalysisResponse(BaseModel):
    """Per-label error analysis for a run; ``available`` is False for older runs."""

    run_id: int
    available: bool
    per_label: Dict[str, LabelErrorAnalysis] = Field(default_factory=dict)


class TrainingMetricPoint(BaseModel):
    epoch: int
    loss: Optional[float] = None
    step: Optional[int] = None
    eval_loss: Optional[float] = None


class ActiveTrainingRunResponse(BaseModel):
    """The in-flight training run, returned so the Monitor page can rehydrate
    live progress after navigation or a full page reload (null when none)."""

    run_id: int
    dataset_ids: List[int] = Field(default_factory=list)
    status: str
    # Set when the run was just reconciled as dead (trainer vanished).
    error_message: Optional[str] = None
    total_steps: Optional[int] = None
    current_step: Optional[int] = None
    num_epochs: Optional[int] = None
    current_epoch: Optional[int] = None
    metrics: List[TrainingMetricPoint] = Field(default_factory=list)
    # Derived pre-training phase for the Monitor stepper (one of "loading",
    # "baseline", "init", "training"), or None when no run is in flight. Lets the
    # stepper rehydrate mid-gap, before the first training step emits a metric.
    phase: Optional[str] = None


class FullStatsRequest(BaseModel):
    """Request body for aggregated stats across multiple datasets."""

    dataset_ids: List[int] = Field(default_factory=list, min_length=1)


class FullStatsResponse(BaseModel):
    # Totals over the whole dataset(s).
    totalRecords: int
    totalTerms: int
    labelDistribution: Dict[str, int]
    # Reviewed, training-eligible subset (what actually trains/evaluates).
    reviewedRecords: int
    reviewedTerms: int
    reviewedLabelDistribution: Dict[str, int]


# ================================================
# NER model selection schemas
# ================================================


class ModelSummary(BaseModel):
    """A trained NER model that can be selected for extraction."""

    id: int
    name: str
    version: str
    base_model: Optional[str] = None
    path: Optional[str] = None
    dataset_id: Optional[int] = None
    created_at: Optional[datetime] = None
    # Overall macro-F1 across labels, if the model has been evaluated.
    score: Optional[float] = None
    run_id: Optional[int] = None  # links a model to its training run
    is_active: bool = False  # is this the global active model?
    # Provenance: "trained" | "discovered" | "baseline" (null on legacy rows).
    source: Optional[str] = None
    # Backing engine: "gliner" | "huggingface" (null for anchors).
    engine: Optional[str] = None


class ModelsOutput(BaseModel):
    """List of trained models available for selection."""

    models: List[ModelSummary]


class DiscoveredModelSummary(ModelSummary):
    """A model row enriched with live bioner scan info for the rescan view."""

    # From the on-disk scan: a LoRA/PEFT adapter needs a base model, so it is not
    # directly selectable as the active extraction model.
    is_adapter: bool = False
    # True when this model can be activated in the running bioner process:
    # its engine matches the launch engine and it is not an adapter.
    activatable: bool = True


class DefaultModelInfo(BaseModel):
    """bioner's launch default model (what /ner runs when nothing is selected)."""

    name: str
    engine: Optional[str] = None


class RescanModelsResponse(BaseModel):
    """Reconciled model list plus live bioner engine/default context."""

    models: List[DiscoveredModelSummary]
    current_engine: Optional[str] = None
    default_model: Optional[DefaultModelInfo] = None


class ModelDetailResponse(BaseModel):
    """Detail for one trained model (per-model view; no cross-model comparison)."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: int
    run_id: Optional[int] = None
    base_model: Optional[str] = None
    train_dataset_ids: List[int] = []
    eval_dataset_ids: List[int] = []
    train_stats: Optional[dict] = None
    labels: List[str] = []
    per_label_trained: Dict[str, Dict[str, Any]] = {}
    per_label_baseline: Dict[str, Dict[str, Any]] = {}


class ActiveModelResponse(BaseModel):
    """The globally selected extraction model (null = bioner default)."""

    active_model: Optional[ModelSummary] = None


class SetActiveModelRequest(BaseModel):
    """Set (``model_id``) or clear (``null``) the global active extraction model."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: Optional[int] = None
