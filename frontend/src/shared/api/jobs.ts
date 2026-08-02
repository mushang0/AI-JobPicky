import { request } from "./client";
import type { JobDetailView, JobFilterOptions, JobQuery, JobsPageResponse, SavedJobState } from "./types";

function appendValues(params: URLSearchParams, key: string, values: string[] | undefined): void {
  values?.forEach((value) => params.append(key, value));
}

export function buildJobsQuery(query: JobQuery = {}): string {
  const params = new URLSearchParams();
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.page_size ?? 30));

  const normalizedQuery = query.q?.trim();
  if (normalizedQuery) params.set("q", normalizedQuery);

  appendValues(params, "city", query.city);
  appendValues(params, "company_nature", query.company_nature);
  appendValues(params, "source_id", query.source_id);
  appendValues(params, "recruitment_type", query.recruitment_type);
  appendValues(params, "education", query.education);
  query.graduation_year?.forEach((year) => params.append("graduation_year", String(year)));

  if (query.salary_min !== undefined && query.salary_min !== null) {
    params.set("salary_min", String(query.salary_min));
  }
  if (query.salary_max !== undefined && query.salary_max !== null) {
    params.set("salary_max", String(query.salary_max));
  }
  if (query.published_within_days !== undefined && query.published_within_days !== null) {
    params.set("published_within_days", String(query.published_within_days));
  }
  if (query.published_at_unknown) params.set("published_at_unknown", "true");

  return params.toString();
}

export const jobsApi = {
  list(query: JobQuery = {}): Promise<JobsPageResponse> {
    return request<JobsPageResponse>(`/api/v1/jobs?${buildJobsQuery(query)}`);
  },

  filterOptions(): Promise<JobFilterOptions> {
    return request<JobFilterOptions>("/api/v1/jobs/filter-options");
  },

  detail(jobId: string): Promise<JobDetailView> {
    return request<JobDetailView>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
  },

  save(jobId: string): Promise<SavedJobState> {
    return request<SavedJobState>(`/api/v1/user/saved-jobs/${encodeURIComponent(jobId)}`, { method: "PUT" });
  },

  unsave(jobId: string): Promise<SavedJobState> {
    return request<SavedJobState>(`/api/v1/user/saved-jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
  },
};
