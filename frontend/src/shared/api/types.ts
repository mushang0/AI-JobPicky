export type IsoDate = string;

export type ApiErrorCode =
  | "AUTHENTICATION_REQUIRED"
  | "SESSION_EXPIRED"
  | "ACCOUNT_DISABLED"
  | "INVALID_CREDENTIALS"
  | "EMAIL_ALREADY_REGISTERED"
  | "TOO_MANY_ATTEMPTS"
  | "INSUFFICIENT_CREDITS"
  | "PROFILE_NOT_FOUND"
  | "PROFILE_VERSION_CONFLICT"
  | "IDEMPOTENCY_CONFLICT"
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "FORBIDDEN"
  | "CONFLICT"
  | "DEPENDENCY_UNAVAILABLE"
  | "RECOMMENDATION_FAILED"
  | "INTERNAL_ERROR"
  | string;

export interface ApiErrorBody {
  code: ApiErrorCode;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
  run_id?: string | null;
}

export interface SourceRef {
  id: string;
  name: string;
}

export interface JobListItem {
  id: string;
  title: string;
  company_name: string;
  company_nature: string | null;
  locations: string[];
  source: SourceRef;
  recruitment_type: string | null;
  education_requirement: string | null;
  graduation_years: number[];
  salary_min: number | null;
  salary_max: number | null;
  salary_months: number | null;
  description_preview: string | null;
  published_at: IsoDate | null;
  last_confirmed_at: IsoDate;
  is_saved: boolean | null;
}

export interface JobDetailView extends JobListItem {
  description: string | null;
  detail_url: string | null;
  apply_url: string | null;
  status: "OPEN" | "CLOSED" | "UNKNOWN";
  deadline_at: IsoDate | null;
  first_seen_at: IsoDate;
  updated_at: IsoDate;
}

export interface JobsPageResponse {
  items: JobListItem[];
  total: number;
  page: number;
  page_size: number;
  pool_total: number;
}

export interface JobFilterOptions {
  cities: string[];
  company_natures: string[];
  sources: SourceRef[];
  recruitment_types: string[];
  educations: string[];
  graduation_years: number[];
  limits: {
    visible_pool_limit: number;
    default_page_size: number;
    public_page_size_max: number;
    authenticated_page_size_max: number;
  };
}

export interface JobQuery {
  page?: number;
  page_size?: number;
  q?: string;
  city?: string[];
  company_nature?: string[];
  source_id?: string[];
  recruitment_type?: string[];
  education?: string[];
  graduation_year?: number[];
  salary_min?: number | null;
  salary_max?: number | null;
}

export interface AuthUserView {
  id: string;
  email: string;
  role: "USER" | "ADMIN";
  created_at: IsoDate;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
}

export interface LoginResponse extends AccessTokenResponse {
  user: AuthUserView;
}

export interface CredentialsRequest {
  email: string;
  password: string;
}

export interface CreditSummary {
  balance: number;
  recommendation_cost: number;
}

export interface ProfileView {
  id: string;
  version: number;
  target_roles: string[];
  target_locations: string[];
  recruitment_types: string[];
  skills: string[];
  education: string | null;
  graduation_year: number | null;
  expected_salary_min: number | null;
  experience_summary: string | null;
  excluded_roles: string[];
  extra_request: string | null;
  warnings: string[];
  created_at: IsoDate;
}

export interface ProfileSaveRequest {
  base_version: number | null;
  target_roles: string[];
  target_locations: string[];
  recruitment_types: string[];
  skills: string[];
  education: string | null;
  graduation_year: number | null;
  expected_salary_min: number | null;
  experience_summary: string | null;
  excluded_roles: string[];
  extra_request: string | null;
}

export type RecommendationFeedback = "LIKE" | "DISLIKE" | null;

export interface RecommendationCardView {
  recommendation_id: string;
  run_id: string;
  recommended_at: IsoDate;
  job: Pick<
    JobListItem,
    "id" | "title" | "company_name" | "company_nature" | "locations"
  > & { first_seen_at: IsoDate };
  assessment: {
    match_score: number;
    reason: string;
    matched_strengths: string[];
    gaps: string[];
    evidence: string[];
  };
  is_saved: boolean;
  feedback: RecommendationFeedback;
}

export interface RecommendationResultView extends RecommendationCardView {
  is_deleted: boolean;
  deleted_at: IsoDate | null;
}

export interface CreditUsage {
  cost: number;
  refunded: boolean;
  net_spent: number;
}

export type RecommendationStep =
  | "PENDING"
  | "PROFILE"
  | "FILTER"
  | "RETRIEVE"
  | "EVALUATE"
  | "SAVE"
  | "COMPLETE";

export type RecommendationRunStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED";

export interface RecommendationTaskView {
  run_id: string;
  status: RecommendationRunStatus;
  current_step: RecommendationStep | null;
  progress_percent: number;
  created_at: IsoDate;
  started_at: IsoDate | null;
  finished_at: IsoDate | null;
  counts: { evaluated: number; recommended: number };
  credits: CreditUsage;
  error: string | null;
}

export interface RecommendationRunAccepted {
  run_id: string;
  status: "PENDING";
  credits_charged: number;
  balance_after: number;
}

export interface RecommendationRunCreateRequest {
  extra_request: string | null;
}

export interface RecommendationFeedbackResponse {
  recommendation_id: string;
  feedback: RecommendationFeedback;
}

export interface RecommendationListQuery {
  page?: number;
  page_size?: number;
  sort?: "recommended_at_desc" | "match_score_desc";
}

export interface RecommendationRunListQuery {
  page?: number;
  page_size?: number;
}

export interface RecommendationResultQuery {
  page?: number;
  page_size?: number;
}

export interface SavedJobListQuery {
  page?: number;
  page_size?: number;
}

export interface SavedJobState {
  job_id: string;
  is_saved: boolean;
}

export interface SavedJobView {
  saved_at: IsoDate;
  job: JobListItem & { status: "OPEN" | "CLOSED" | "UNKNOWN" };
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
