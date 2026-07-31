import { recommendationsApi } from "./recommendations";

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("recommendation API helpers", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the documented idempotency key when creating a run", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response(202, { run_id: "run-123", status: "PENDING", credits_charged: 100, balance_after: 9900 }),
    );

    await expect(recommendationsApi.create({ extra_request: null }, "recommendation-key")).resolves.toMatchObject({ run_id: "run-123" });
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("Idempotency-Key")).toBe("recommendation-key");
  });

  it("uses the confirmed sort and pagination parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response(200, { items: [], total: 0, page: 2, page_size: 10 }),
    );

    await recommendationsApi.list({ page: 2, page_size: 10, sort: "match_score_desc" });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/user/recommendations?page=2&page_size=10&sort=match_score_desc");
  });
});
