import { request } from "./client";
import type { PageResponse, SavedJobListQuery, SavedJobView } from "./types";

export const savedJobsApi = {
  list(query: SavedJobListQuery = {}): Promise<PageResponse<SavedJobView>> {
    const params = new URLSearchParams({
      page: String(query.page ?? 1),
      page_size: String(query.page_size ?? 10),
    });
    return request<PageResponse<SavedJobView>>(`/api/v1/user/saved-jobs?${params.toString()}`);
  },
};
