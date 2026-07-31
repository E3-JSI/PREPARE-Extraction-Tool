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

export interface ClusterJobStartResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

export interface ClusterJobStatusResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  completed: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  clustered_labels: string[];
  skipped_labels: string[];
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

export interface MappingJobStartResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
}

export interface MappingJobStatusResponse {
  job_id: string;
  dataset_id: number;
  total: number;
  completed: number;
  mapped_count: number;
  failed_count: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string | null;
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

// ================================================
// Monitoring / training types
// ================================================

/** Minimal dataset shape used by the monitoring dashboard. */
export interface MonitorDataset {
  id: number;
  name: string;
}

/** A training run with the metadata needed to compare/manage runs. */
export interface MonitorRun {
  run_id: number;
  status?: string;
  name?: string | null;
  base_model?: string | null;
  labels?: string[];
  val_ratio?: number | null;
  created_at?: string | null;
  error_message?: string | null;
  /** Path to the trained model artifact, if any. */
  path?: string | null;
  /** Id of the linked trained model, used to select it for extraction (if any). */
  model_id?: number | null;
  /** Overall macro-F1 across labels, if evaluation is available. */
  score?: number | null;
  /** Whether this run is the dataset's designated preferred/best run. */
  preferred?: boolean;
}

/** A trained NER model available for selection in extraction. */
export interface ModelSummary {
  id: number;
  name: string;
  version: string;
  base_model?: string | null;
  path?: string | null;
  dataset_id?: number | null;
  created_at?: string | null;
  /** Overall macro-F1 across labels, if the model has been evaluated. */
  score?: number | null;
  run_id?: number | null;
  is_active?: boolean;
  /** Provenance: "trained" | "discovered" | "baseline". */
  source?: string | null;
  /** Backing engine: "gliner" | "huggingface". */
  engine?: string | null;
}

/** A model enriched with live bioner scan info (from the rescan endpoint). */
export interface DiscoveredModelSummary extends ModelSummary {
  /** A LoRA/PEFT adapter — needs a base model, not directly selectable. */
  is_adapter: boolean;
  /** Can this model be activated in the running bioner process
   *  (engine matches the launch engine and it is not an adapter)? */
  activatable: boolean;
}

/** bioner's launch default model (what /ner runs when nothing is selected). */
export interface DefaultModelInfo {
  name: string;
  engine?: string | null;
}

/** Reconciled model list plus live bioner engine/default context. */
export interface RescanModelsResponse {
  models: DiscoveredModelSummary[];
  current_engine?: string | null;
  default_model?: DefaultModelInfo | null;
}

/** List of trained models available for selection. */
export interface ModelsOutput {
  models: ModelSummary[];
}

/** The global active extraction model (null active_model = bioner default). */
export interface ActiveModelResponse {
  active_model?: ModelSummary | null;
}

/** Paginated list of training runs for a dataset. */
export interface RunsOutput {
  runs: MonitorRun[];
  pagination: PaginationMetadata;
}

/** Partial update for a training run (rename / designate as preferred). */
export interface RunUpdate {
  name?: string | null;
  preferred?: boolean;
}

/** Per-label evaluation metrics returned by the bioner backend. */
export interface PerLabelMetrics {
  exact_f1?: number;
  relaxed_f1?: number;
  f1?: number;
  precision: number;
  recall: number;
}

/** Evaluation response for a single run. */
export interface EvaluationResponse {
  run_id: number;
  /** Display name for the entry; the default-model baseline uses "Base model".
   * Falls back to `Run #<run_id>` when absent. */
  name?: string;
  /** True for the default-model baseline entry (run_id 0, not a real run). */
  is_baseline?: boolean;
  per_label: { [label: string]: PerLabelMetrics };
}

/** A gold or predicted span inside an example error's context text. */
export interface ErrorSpan {
  text: string;
  start: number;
  end: number;
  label: string;
}

/** One concrete per-label error. A missed gold span has `gold` set and
 * `predicted` null; a wrong prediction has `predicted` set and `gold` null. */
export interface ErrorExample {
  text: string;
  gold: ErrorSpan | null;
  predicted: ErrorSpan | null;
}

/** Per-label confusion summary plus a bounded sample of example errors. */
export interface LabelErrorAnalysis {
  precision?: number | null;
  recall?: number | null;
  fp?: number | null;
  fn?: number | null;
  examples: ErrorExample[];
}

/** Per-label error analysis for a run. `available` is false for older runs
 * trained before error analysis was recorded. */
export interface RunErrorAnalysis {
  run_id: number;
  available: boolean;
  per_label: { [label: string]: LabelErrorAnalysis };
}

/** A single training metric point streamed over the websocket.
 *  `loss` is null on eval-only rows (which carry `eval_loss` instead). */
export interface TrainingMetric {
  epoch: number;
  loss: number | null;
  step?: number | null;
  eval_loss?: number | null;
}

/** The in-flight training run, used to rehydrate live Monitor progress after
 *  navigating away and back or after a full page reload. Null when idle. */
export interface ActiveTrainingRun {
  run_id: number;
  dataset_ids: number[];
  status: string;
  /** Why the run failed — set when the backend just reconciled it as dead. */
  error_message?: string | null;
  total_steps?: number | null;
  current_step?: number | null;
  num_epochs?: number | null;
  current_epoch?: number | null;
  metrics: TrainingMetric[];
  /** Derived pre-training phase ("loading" | "baseline" | "init" | "training"),
   *  used to rehydrate the phase stepper mid-gap. Null when no run is in flight. */
  phase?: string | null;
}

/** Per-model detail: training datasets, snapshot stats, base-vs-trained eval. */
export interface ModelDetailResponse {
  model_id: number;
  run_id?: number | null;
  base_model?: string | null;
  train_dataset_ids: number[];
  eval_dataset_ids: number[];
  train_stats?: {
    record_count?: number;
    term_count?: number;
    label_distribution?: { [label: string]: number };
    // Reviewed subset that actually trained (absent on older snapshots).
    reviewed_record_count?: number;
    reviewed_term_count?: number;
    reviewed_label_distribution?: { [label: string]: number };
    total_steps?: number;
    val_ratio?: number;
  } | null;
  labels: string[];
  per_label_trained: { [label: string]: { [metric: string]: number } };
  per_label_baseline: { [label: string]: { [metric: string]: number } };
}

/** Precision/recall/F1 for one match mode (exact/relaxed/overlap). */
export interface LiveEvalScore {
  precision: number;
  recall: number;
  f1: number;
}

/** Computed live-eval metrics: per-label + macro aggregate across match modes. */
export interface LiveEvalMetrics {
  labels: string[];
  match_types: string[];
  per_label: { [label: string]: { [matchType: string]: LiveEvalScore } };
  aggregate: { [matchType: string]: LiveEvalScore };
  aggregate_method?: string;
  gold_entity_count?: number;
  pred_entity_count?: number;
  heldout_count: number;
  /** Set when the held-out set is empty (nothing to score). */
  message?: string;
}

/** Response when a live-eval job is queued (or short-circuits immediately). */
export interface LiveEvalJobStartResponse {
  job_id: number;
  dataset_id: number;
  model_id: number;
  total: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  message?: string | null;
}

/** Progress snapshot for a live-eval job, with metrics once complete. */
export interface LiveEvalJobStatusResponse {
  job_id: number;
  dataset_id: number;
  model_id: number;
  total: number;
  completed: number;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string | null;
  metrics?: LiveEvalMetrics | null;
}

/** Dataset statistics used by the monitoring dashboard. */
export interface MonitorDatasetStats {
  // Totals over the whole dataset(s).
  totalRecords: number;
  totalTerms: number;
  labelDistribution: { [label: string]: number };
  // Reviewed, training-eligible subset (only reviewed records train/evaluate).
  reviewedRecords: number;
  reviewedTerms: number;
  reviewedLabelDistribution: { [label: string]: number };
}
