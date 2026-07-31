import { request } from "./client";
import type { ProfileSaveRequest, ProfileView } from "./types";

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
};
