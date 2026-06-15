// ================================================
// User types
// ================================================

export interface User {
  id: number;
  username: string;
  disabled: boolean;
  created_at: string;
  last_login: string | null;
}

export interface UserRegister {
  username: string;
  password: string;
}

export interface Token {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserStats {
  dataset_count: number;
  vocabulary_count: number;
}

// ================================================
// Pagination types
// ================================================

export interface PaginationMetadata {
  total: number;
  limit: number;
  offset: number;
  page: number;
  total_pages: number;
}

// ================================================
// Processing status type
// ================================================

export type ProcessingStatus = "PENDING" | "PROCESSING" | "DONE" | "FAILED" | "DELETED";

// ================================================
// Dataset types
// ================================================

export interface LabelRelation {
  from_label: string;
  to_label: string;
}

export interface Dataset {
  id: number;
  name: string;
  uploaded: string;
  last_modified: string;
  labels: string[];
  label_relations: LabelRelation[];
  date_label: string | null;
  record_count: number;
  status: ProcessingStatus;
  error_message: string | null;
}

export interface DatasetCreate {
  name: string;
  labels: string;
  label_relations?: string;
  file: File;
  date_label?: string;
}

export interface DatasetOutput {
  dataset: Dataset;
}

export interface DatasetUploadResponse {
  status: string;
  message: string;
}

export interface DatasetsOutput {
  datasets: Dataset[];
  pagination: PaginationMetadata;
}

// ================================================
// Record types
// ================================================

export interface Record {
  id: number;
  patient_id: string;
  seq_number: string | null;
  date: string | null;
  text: string;
  uploaded: string;
  dataset_id: number;
  reviewed: boolean;
  source_term_count: number;
}

export interface RecordCreate {
  text: string;
}

export interface RecordOutput {
  record: Record;
}

export interface RecordsOutput {
  records: Record[];
  pagination: PaginationMetadata;
}

// ================================================
// Source Term types
// ================================================

export interface SourceTermLink {
  id: number;
  from_term_id: number;
  to_term_id: number;
  from_term_value: string;
  to_term_value: string;
  from_term_label: string;
  to_term_label: string;
}

export interface SourceTerm {
  id: number;
  value: string;
  label: string;
  start_position: number | null;
  end_position: number | null;
  record_id: number;
  linked_visit_date?: string | null;
  manual_linked_visit_date?: boolean | null;
  linked_date_term_id?: number | null;
  links?: SourceTermLink[];
}

export interface SourceTermCreate {
  value: string;
  label: string;
  start_position?: number;
  end_position?: number;
}

export interface SourceTermUpdate {
  label?: string;
  linked_visit_date?: string | null;
}

export interface SourceTermOutput {
  source_term: SourceTerm;
}

export interface SourceTermsOutput {
  source_terms: SourceTerm[];
  pagination: PaginationMetadata;
}

// ================================================
// Dataset Stats types
// ================================================

export interface DatasetStats {
  total_records: number;
  processed_count: number;
  pending_review_count: number;
  extracted_terms_count: number;
}

export interface ClusteringStats {
  total_clusters: number;
  clustered_terms: number;
  unclustered_terms: number;
}

export interface MappingStats {
  total_clusters: number;
  mapped_clusters: number;
  unmapped_clusters: number;
}

// ================================================
// Extraction job types
// ================================================

export interface ExtractionJobStartResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

export interface ExtractionJobStatusResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  completed: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string | null;
}

export interface DatasetOverview {
  dataset: Dataset;
  stats: DatasetStats;
  clustering_stats: ClusteringStats;
  mapping_stats: MappingStats;
}

export interface DatasetOverviewOutput {
  dataset: Dataset;
  stats: DatasetStats;
  clustering_stats: ClusteringStats;
  mapping_stats: MappingStats;
}

// ================================================
// Vocabulary types
// ================================================

export interface Vocabulary {
  id: number;
  name: string;
  uploaded: string;
  concept_count: number;
  status: ProcessingStatus;
  error_message: string | null;
}

export interface VocabularyCreate {
  name: string;
  file: File;
}

export interface VocabularyOutput {
  vocabulary: Vocabulary;
}

export interface VocabularyUploadResponse {
  status: string;
  message: string;
}

export interface VocabulariesOutput {
  vocabularies: Vocabulary[];
  pagination: PaginationMetadata;
}

// ================================================
// Concept types
// ================================================

export interface Concept {
  id: number;
  vocab_term_id: string;
  vocab_term_name: string;
  vocabulary_id: number;
  domain_id: string;
  concept_class_id: string;
  standard_concept: string | null;
  concept_code: string | null;
  valid_start_date: string;
  valid_end_date: string;
  invalid_reason: string | null;
}

export interface ConceptCreate {
  vocab_term_id: string;
  vocab_term_name: string;
  domain_id: string;
  concept_class_id: string;
  standard_concept?: string;
  concept_code?: string;
  valid_start_date: string; // YYYYMMDD format
  valid_end_date: string; // YYYYMMDD format
  invalid_reason?: string;
}

export interface ConceptOutput {
  concept: Concept;
}

export interface ConceptsOutput {
  concepts: Concept[];
  pagination: PaginationMetadata;
}

// ================================================
// Generic response types
// ================================================

export interface MessageOutput {
  message: string;
}

export interface ApiError {
  detail: string;
}

// ================================================
// Clustering types
// ================================================

export interface ClusteredTerm {
  term_id: number;
  text: string;
  frequency: number;
  n_records: number;
  record_ids: number[];
}

export interface ClusterData {
  id: number;
  dataset_id: number;
  title: string;
  label: string;
  terms: ClusteredTerm[];
  total_terms: number;
  total_occurrences: number;
  unique_records: number;
  label_color?: string;
}

export interface ClustersOutput {
  clusters: ClusterData[];
  unclustered_terms: ClusteredTerm[];
  total_terms: number;
  labels: string[];
  label_reviewed: boolean;
}

export interface ClusterCreateRequest {
  label: string;
  title: string;
}

export interface ClusterMergeRequest {
  cluster_ids: number[];
  new_title: string;
}

// ================================================
// Mapping types
// ================================================

export interface ClusterMapping {
  cluster_id: number;
  cluster_title: string;
  cluster_label: string;
  cluster_term_count: number;
  cluster_total_occurrences: number;
  concept_id: number | null;
  concept_term_id: string | null;
  concept_term_name: string | null;
  concept_code: string | null;
  concept_domain: string | null;
  concept_class: string | null;
  vocabulary_id: number | null;
  vocabulary_name: string | null;
  status: "unmapped" | "pending" | "approved" | "rejected";
  comment: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ClusterMappingsOutput {
  mappings: ClusterMapping[];
  total_clusters: number;
  mapped_count: number;
  unmapped_count: number;
  approved_count: number;
}

export interface ConceptDetail extends Concept {
  domain_id: string;
  concept_class_id: string;
  standard_concept: string | null;
  concept_code: string | null;
  valid_start_date: string;
  valid_end_date: string;
  invalid_reason: string | null;
}

export interface ConceptSearchResult {
  concept: ConceptDetail;
  score: number;
  vocabulary_name: string;
}

export interface ConceptSearchResults {
  results: ConceptSearchResult[];
  total: number;
  pagination?: PaginationMetadata;
}

export interface ConceptHierarchy {
  concept: ConceptDetail;
  parents: ConceptDetail[];
  children: ConceptDetail[];
  related_concepts: ConceptDetail[];
}

export interface AutoMapRequest {
  vocabulary_ids: number[];
  use_cluster_terms?: boolean;
  domain_id?: string;
  concept_class_id?: string;
  standard_concept?: string;
  search_type?: "vector" | "hybrid";
}

export interface MapClusterRequest {
  concept_id: number;
  status?: "pending" | "approved" | "rejected";
  comment?: string;
}

export interface AutoMapAllRequest {
  vocabulary_ids: number[];
  label?: string;
  use_cluster_terms?: boolean;
  search_type?: "vector" | "hybrid";
}

export interface AutoMapAllResponse {
  mapped_count: number;
  failed_count: number;
  total_clusters: number;
}

export interface ConceptSearchParams {
  query: string;
  vocabulary_ids: number[];
  domain_id?: string;
  concept_class_id?: string;
  standard_concept?: string;
  search_type?: "vector" | "hybrid";
  limit?: number;
  offset?: number;
  sort_by?: "relevance" | "name" | "domain";
  sort_order?: "asc" | "desc";
}

// ================================================
// Filter types
// ================================================

export interface DistinctValuesOutput {
  values: string[];
}
