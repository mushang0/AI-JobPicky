import { ApiError, clearAccessToken, getAccessToken, request, setAuthFailureHandler } from "./client";

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("API client authentication retry", () => {
  afterEach(() => {
    clearAccessToken();
    setAuthFailureHandler(null);
    vi.restoreAllMocks();
  });

  it("refreshes once and retries the original request", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(401, { code: "AUTHENTICATION_REQUIRED", message: "请登录后继续。" }))
      .mockResolvedValueOnce(response(200, { access_token: "fresh-token", token_type: "Bearer", expires_in: 900 }))
      .mockResolvedValueOnce(response(200, { ok: true }));

    await expect(request<{ ok: boolean }>("/api/v1/user/credits")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "include" });
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("stops after a failed refresh instead of looping", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(401, { code: "AUTHENTICATION_REQUIRED", message: "请登录后继续。" }))
      .mockResolvedValueOnce(response(401, { code: "SESSION_EXPIRED", message: "登录会话已过期，请重新登录。" }));

    await expect(request("/api/v1/user/credits")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBeNull();
  });

  it("clears the session when the one retry also returns 401", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(401, { code: "AUTHENTICATION_REQUIRED", message: "请登录后继续。" }))
      .mockResolvedValueOnce(response(200, { access_token: "fresh-token", token_type: "Bearer", expires_in: 900 }))
      .mockResolvedValueOnce(response(401, { code: "SESSION_EXPIRED", message: "登录会话已过期，请重新登录。" }));
    const failureHandler = vi.fn();

    setAuthFailureHandler(failureHandler);
    await expect(request("/api/v1/user/credits")).rejects.toBeInstanceOf(ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getAccessToken()).toBeNull();
    expect(failureHandler).toHaveBeenCalledOnce();
  });
});
