import { request } from "./client";
import type { ProfileImportResponse, ProfileSaveRequest, ProfileView } from "./types";

export const profileApi = {
  current(): Promise<ProfileView> {
    return request<ProfileView>("/api/v1/user/profiles/current");
  },

  save(input: ProfileSaveRequest, idempotencyKey: string): Promise<ProfileView> {
    return request<ProfileView>("/api/v1/user/profiles/current", {
      method: "PUT",
      body: input,
      idempotencyKey,
    });
  },

  importResume(file: File): Promise<ProfileImportResponse> {
    const body = new FormData();
    body.append("file", file);
    return request<ProfileImportResponse>("/api/v1/user/profile-imports", {
      method: "POST",
      body,
    });
  },
};
