import { http, HttpResponse, type JsonBodyType } from "msw";
import { jobDetails, jobFilterOptions, jobFixtures, mockProfile, mockProfileImport, mockUser, recommendationFixtures } from "./fixtures";
import type {
  CreditSummary,
  JobListItem,
  JobsPageResponse,
  ProfileSaveRequest,
  ProfileView,
  RecommendationFeedback,
  RecommendationTaskView,
} from "../shared/api/types";

type MockScenario = NonNullable<ImportMetaEnv["VITE_MOCK_SCENARIO"]>;

const scenario = (): MockScenario => import.meta.env.VITE_MOCK_SCENARIO ?? "normal";
const isAuthenticated = (request: Request): boolean =>
  Boolean(request.headers.get("Authorization")) || import.meta.env.VITE_MOCK_AUTH === "authenticated";
const savedJobIds = new Set(["job-102"]);

function errorResponse(code: string, message: string, status: number) {
  return HttpResponse.json(
    {
      code,
      message,
      details: {},
      request_id: "mock-request",
      run_id: null,
    },
    { status },
  );
}

function shouldRequireAuth(url: URL, authenticated: boolean): boolean {
  const hasFilter = [
    "q",
    "city",
    "company_nature",
    "source_id",
    "recruitment_type",
    "education",
    "graduation_year",
    "salary_min",
    "salary_max",
    "published_within_days",
    "published_at_unknown",
  ].some((key) => url.searchParams.has(key));
  return !authenticated && (Number(url.searchParams.get("page") ?? "1") >= 2 || hasFilter);
}

function filterJobs(url: URL, authenticated: boolean): JobListItem[] {
  return jobFixtures
    .map((job) => ({ ...job, is_saved: authenticated ? savedJobIds.has(job.id) : null }))
    .filter((job) => {
      const q = url.searchParams.get("q")?.trim().toLowerCase();
      if (q) {
        const haystack = [job.title, job.company_name, ...job.locations, job.description_preview ?? ""]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }

      const matches = (key: string, value: string | null) => {
        const values = url.searchParams.getAll(key);
        return values.length === 0 || (value !== null && values.includes(value));
      };

      if (!url.searchParams.getAll("city").some((city) => job.locations.includes(city)) && url.searchParams.has("city")) {
        return false;
      }
      if (!matches("company_nature", job.company_nature)) return false;
      if (!matches("source_id", job.source.id)) return false;
      if (!matches("recruitment_type", job.recruitment_type)) return false;
      if (!matches("education", job.education_requirement)) return false;

      const graduationYears = url.searchParams.getAll("graduation_year").map(Number);
      if (graduationYears.length && !graduationYears.some((year) => job.graduation_years.includes(year))) return false;

      const salaryMin = Number(url.searchParams.get("salary_min"));
      const salaryMax = Number(url.searchParams.get("salary_max"));
      if (url.searchParams.has("salary_min") && job.salary_max !== null && job.salary_max < salaryMin) return false;
      if (url.searchParams.has("salary_max") && job.salary_min !== null && job.salary_min > salaryMax) return false;
      const publishedUnknown = url.searchParams.get("published_at_unknown") === "true";
      if (publishedUnknown && job.published_at !== null) return false;
      const withinDays = Number(url.searchParams.get("published_within_days"));
      if (url.searchParams.has("published_within_days") && Number.isFinite(withinDays) && job.published_at === null) return false;
      if (url.searchParams.has("published_within_days") && Number.isFinite(withinDays) && job.published_at !== null) {
        const cutoff = Date.now() - withinDays * 24 * 60 * 60 * 1000;
        if (new Date(job.published_at).getTime() < cutoff) return false;
      }
      return true;
    });
}

const recommendationRun: RecommendationTaskView = {
  run_id: "run-demo",
  status: "PENDING",
  current_step: "PENDING",
  progress_percent: 0,
  created_at: "2026-07-31T08:00:00Z",
  started_at: null,
  finished_at: null,
  counts: { evaluated: 0, recommended: 0 },
  credits: { cost: 100, refunded: false, net_spent: 100 },
  error: null,
};
let recommendationPolls = 0;
let currentProfile: ProfileView | null = null;
const recommendationFeedback = new Map<string, RecommendationFeedback>();
const deletedRecommendationIds = new Set<string>();
const idempotencyResults = new Map<string, { fingerprint: string; response: JsonBodyType; status: number }>();

async function readJson(request: Request): Promise<Record<string, unknown>> {
  return (await request.json()) as Record<string, unknown>;
}

function replayIdempotent(request: Request, fingerprint: string): HttpResponse<JsonBodyType> | null {
  const key = request.headers.get("Idempotency-Key");
  if (!key) return errorResponse("VALIDATION_ERROR", "幂等键不能为空。", 422);
  const previous = idempotencyResults.get(key);
  if (!previous) return null;
  if (previous.fingerprint !== fingerprint) return errorResponse("IDEMPOTENCY_CONFLICT", "该幂等键已被其他请求使用。", 409);
  return HttpResponse.json(previous.response, { status: previous.status });
}

function rememberIdempotent(request: Request, fingerprint: string, response: JsonBodyType, status: number): void {
  const key = request.headers.get("Idempotency-Key");
  if (key) idempotencyResults.set(key, { fingerprint, response, status });
}

function enrichRecommendation<T extends { recommendation_id: string; job: { id: string }; feedback: RecommendationFeedback; is_saved: boolean }>(item: T): T {
  return {
    ...item,
    is_saved: savedJobIds.has(item.job.id),
    feedback: recommendationFeedback.get(item.recommendation_id) ?? item.feedback,
  };
}

export const handlers = [
  http.get("*/api/v1/jobs/filter-options", () => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    return HttpResponse.json(jobFilterOptions);
  }),

  http.get("*/api/v1/jobs/:jobId", ({ params, request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    const job = jobDetails[String(params.jobId)];
    if (!job) return errorResponse("NOT_FOUND", "岗位不存在。", 404);
    return HttpResponse.json({ ...job, is_saved: isAuthenticated(request) ? savedJobIds.has(job.id) : null });
  }),

  http.get("*/api/v1/jobs", ({ request }) => {
    const currentScenario = scenario();
    if (currentScenario === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (currentScenario === "unauthorized") return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);

    const url = new URL(request.url);
    const authenticated = isAuthenticated(request);
    if (shouldRequireAuth(url, authenticated)) {
      return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续搜索、筛选或翻页。", 401);
    }

    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "30");
    const salaryMin = url.searchParams.get("salary_min");
    const salaryMax = url.searchParams.get("salary_max");
    if (currentScenario === "validation" || page < 1 || pageSize < 1 || pageSize > 100 || (salaryMin && salaryMax && Number(salaryMin) > Number(salaryMax))) {
      return errorResponse("VALIDATION_ERROR", "请求内容不符合要求。", 422);
    }

    const items = currentScenario === "empty" ? [] : filterJobs(url, authenticated);
    const offset = (page - 1) * pageSize;
    const response: JobsPageResponse = {
      items: items.slice(offset, offset + pageSize),
      total: items.length,
      page,
      page_size: pageSize,
      pool_total: jobFixtures.length,
    };
    return HttpResponse.json(response);
  }),

  http.post("*/api/v1/auth/refresh", () => {
    if (scenario() === "refresh-failure" || import.meta.env.VITE_MOCK_AUTH !== "authenticated") {
      return errorResponse("SESSION_EXPIRED", "登录会话已过期，请重新登录。", 401);
    }
    return HttpResponse.json({ access_token: "mock-access-token", token_type: "Bearer", expires_in: 900 });
  }),

  http.get("*/api/v1/auth/me", ({ request }) => {
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "登录状态已失效，请重新登录。", 401);
    return HttpResponse.json(mockUser);
  }),

  http.post("*/api/v1/auth/login", () => {
    if (scenario() === "validation") return errorResponse("VALIDATION_ERROR", "请求内容不符合要求。", 422);
    return HttpResponse.json({ access_token: "mock-access-token", token_type: "Bearer", expires_in: 900, user: mockUser });
  }),

  http.post("*/api/v1/auth/register", () => {
    if (scenario() === "conflict") return errorResponse("EMAIL_ALREADY_REGISTERED", "该邮箱已经注册。", 409);
    if (scenario() === "validation") return errorResponse("VALIDATION_ERROR", "请求内容不符合要求。", 422);
    return HttpResponse.json({ access_token: "mock-access-token", token_type: "Bearer", expires_in: 900, user: mockUser }, { status: 201 });
  }),

  http.post("*/api/v1/auth/logout", () => new HttpResponse(null, { status: 204 })),

  http.get("*/api/v1/user/credits", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    const credits: CreditSummary = { balance: 10000, recommendation_cost: 100 };
    return HttpResponse.json(credits);
  }),

  http.get("*/api/v1/user/profiles/current", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "empty") return errorResponse("PROFILE_NOT_FOUND", "还没有求职画像。", 404);
    return HttpResponse.json(currentProfile ?? mockProfile);
  }),

  http.post("*/api/v1/user/profile-imports", async ({ request }) => {
    if (scenario() === "server-error") return errorResponse("DEPENDENCY_UNAVAILABLE", "简历解析服务暂时不可用，请稍后重试。", 503);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "validation") return errorResponse("PROFILE_PARSE_FAILED", "求职画像处理失败，请检查输入后重试。", 422);
    const file = (await request.formData()).get("file");
    if (!(file instanceof File)) return errorResponse("VALIDATION_ERROR", "请选择简历文件。", 422);
    return HttpResponse.json(mockProfileImport);
  }),

  http.put("*/api/v1/user/profiles/current", async ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "conflict") return errorResponse("PROFILE_VERSION_CONFLICT", "画像已在其他页面更新，请刷新后重试。", 409);
    if (scenario() === "idempotency-conflict") return errorResponse("IDEMPOTENCY_CONFLICT", "该幂等键已被其他请求使用。", 409);
    if (scenario() === "validation") return errorResponse("VALIDATION_ERROR", "请求内容不符合要求。", 422);
    const input = (await readJson(request)) as unknown as ProfileSaveRequest;
    const fingerprint = JSON.stringify(input);
    const replay = replayIdempotent(request, fingerprint);
    if (replay) return replay;
    const existingProfile = currentProfile ?? (scenario() === "empty" ? null : mockProfile);
    const { base_version: _baseVersion, ...profileFields } = input;
    currentProfile = {
      ...(existingProfile ?? mockProfile),
      ...profileFields,
      version: (existingProfile?.version ?? 0) + 1,
      created_at: "2026-08-01T08:00:00Z",
    };
    const responseStatus = existingProfile ? 200 : 201;
    rememberIdempotent(request, fingerprint, currentProfile, responseStatus);
    return HttpResponse.json(currentProfile, { status: responseStatus });
  }),

  http.get("*/api/v1/user/recommendations", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    const items = scenario() === "empty" ? [] : recommendationFixtures.filter((item) => !deletedRecommendationIds.has(item.recommendation_id)).map(enrichRecommendation);
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 10 });
  }),

  http.get("*/api/v1/user/recommendation-runs", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    const items = scenario() === "empty" ? [] : [recommendationRun];
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 20 });
  }),

  http.post("*/api/v1/user/recommendation-runs", async ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "recommendation-failure") return errorResponse("RECOMMENDATION_FAILED", "推荐运行失败，积分已退回。", 500);
    if (scenario() === "idempotency-conflict") return errorResponse("IDEMPOTENCY_CONFLICT", "该幂等键已被其他请求使用。", 409);
    const input = await readJson(request);
    const fingerprint = JSON.stringify(input);
    const replay = replayIdempotent(request, fingerprint);
    if (replay) return replay;
    recommendationPolls = 0;
    const response = { run_id: "run-demo", status: "PENDING" as const, credits_charged: 100, balance_after: 9900 };
    rememberIdempotent(request, fingerprint, response, 202);
    return HttpResponse.json(response, { status: 202 });
  }),

  http.get("*/api/v1/user/recommendation-runs/:runId", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "recommendation-failure") {
      return HttpResponse.json({
        ...recommendationRun,
        status: "FAILED",
        current_step: "EVALUATE",
        progress_percent: 60,
        error: {
          code: "RECOMMENDATION_FAILED",
          message: "推荐运行失败，积分已退回。",
          details: {},
        },
        credits: { cost: 100, refunded: true, net_spent: 0 },
      });
    }
    const steps = ["PENDING", "PROFILE", "FILTER", "RETRIEVE", "EVALUATE", "SAVE", "COMPLETE"] as const;
    const progress = [0, 10, 25, 45, 60, 95, 100];
    const index = Math.min(recommendationPolls++, steps.length - 1);
    const complete = index === steps.length - 1;
    return HttpResponse.json({ ...recommendationRun, status: complete ? "SUCCEEDED" : index === 0 ? "PENDING" : "RUNNING", current_step: steps[index], progress_percent: progress[index], counts: { evaluated: complete ? 4 : index > 3 ? 2 : 0, recommended: complete ? 1 : 0 }, started_at: "2026-08-01T08:00:01Z", finished_at: complete ? "2026-08-01T08:00:20Z" : null });
  }),

  http.get("*/api/v1/user/recommendation-runs/:runId/results", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    const items = scenario() === "empty" ? [] : recommendationFixtures.map((item) => ({ ...enrichRecommendation(item), is_deleted: deletedRecommendationIds.has(item.recommendation_id), deleted_at: deletedRecommendationIds.has(item.recommendation_id) ? "2026-08-01T08:00:00Z" : null }));
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 10 });
  }),

  http.put("*/api/v1/user/recommendations/:recommendationId/feedback", async ({ params, request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    if (scenario() === "validation") return errorResponse("VALIDATION_ERROR", "请求内容不符合要求。", 422);
    const input = await readJson(request);
    const feedback = input.feedback as RecommendationFeedback;
    if (feedback !== null && feedback !== "LIKE" && feedback !== "DISLIKE") return errorResponse("VALIDATION_ERROR", "反馈内容不符合要求。", 422);
    const recommendationId = String(params.recommendationId);
    recommendationFeedback.set(recommendationId, feedback);
    return HttpResponse.json({ recommendation_id: recommendationId, feedback });
  }),

  http.delete("*/api/v1/user/recommendations/:recommendationId", ({ params, request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    deletedRecommendationIds.add(String(params.recommendationId));
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/api/v1/user/saved-jobs", ({ request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    const saved = jobFixtures.filter((job) => savedJobIds.has(job.id)).map((job) => ({ saved_at: "2026-07-30T08:00:00Z", job: { ...job, is_saved: true, status: job.id === "job-105" ? "CLOSED" as const : "OPEN" as const } }));
    return HttpResponse.json({ items: scenario() === "empty" ? [] : saved, total: scenario() === "empty" ? 0 : saved.length, page: 1, page_size: 10 });
  }),

  http.put("*/api/v1/user/saved-jobs/:jobId", ({ params, request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    savedJobIds.add(String(params.jobId));
    return HttpResponse.json({ job_id: String(params.jobId), is_saved: true });
  }),

  http.delete("*/api/v1/user/saved-jobs/:jobId", ({ params, request }) => {
    if (scenario() === "server-error") return errorResponse("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。", 500);
    if (!isAuthenticated(request)) return errorResponse("AUTHENTICATION_REQUIRED", "请登录后继续。", 401);
    savedJobIds.delete(String(params.jobId));
    return HttpResponse.json({ job_id: String(params.jobId), is_saved: false });
  }),
];
