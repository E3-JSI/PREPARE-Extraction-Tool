import re
from math import ceil
from datetime import datetime
from typing import List, Optional

from fastapi import Query
from pydantic import BaseModel, Field, field_validator
from app.models_db import Record, Concept, SourceTerm, Cluster, ProcessingStatus


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



class TrainingRequest(BaseModel):
    dataset_id: int
    labels: list[str]


class GLiNERTrainingRequest(BaseModel):
    dataset_id: int
    labels: list[str]
    base_model: str          # path to GLiNER model, e.g. "/model/gliner/gliner_large-v2"
    num_epochs: int = 4
    learning_rate: float = 5e-6
    train_batch_size: int = 8
    val_ratio: float = 0.2
    device: str = "cpu"      # "cpu" by default; pass "cuda" to use GPU

class ExtractionJobStatusResponse(BaseModel):
    """Progress snapshot for a dataset extraction job."""

    job_id: int
    dataset_id: int
    total: int
    completed: int
    status: str
    error_message: Optional[str] = None


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




class SourceTermOutput(BaseModel):
    """Wrapper for single source term response."""

    source_term: SourceTerm


class SourceTermsOutput(BaseModel):
    """Wrapper for paginated list of source terms."""

    source_terms: List[SourceTerm]
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


class AutoMapAllResponse(BaseModel):
    """Response for bulk auto-mapping operation"""

    mapped_count: int
    failed_count: int
    total_clusters: int


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
