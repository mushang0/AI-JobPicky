import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CaretDown, CheckCircle, Clock, Coins, ListChecks, MagnifyingGlass, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { createIdempotencyKey } from "../../shared/api/idempotency";
import { jobsApi } from "../../shared/api/jobs";
import { profileApi } from "../../shared/api/profile";
import { creditsApi, recommendationsApi } from "../../shared/api/recommendations";
import type { CreditSummary, ProfileView, RecommendationCardView, RecommendationFeedback, RecommendationResultView, RecommendationTaskView } from "../../shared/api/types";
import { formatDate, formatRecommendationStatus, formatRecommendationStep } from "../../shared/formatting";
import { currentPath, restoreListScroll } from "../../shared/navigation";
import { RecommendationCard } from "./RecommendationCard";

export function AllRecommendationsPage() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<RecommendationCardView[]>([]);
  const [credits, setCredits] = useState<CreditSummary | null>(null);
  const [recommendationTotal, setRecommendationTotal] = useState<number | null>(null);
  const [companyCount, setCompanyCount] = useState<number | null>(null);
  const [sort, setSort] = useState<"recommended_at_desc" | "match_score_desc">(searchParams.get("sort") === "recommended_at_desc" ? "recommended_at_desc" : "match_score_desc");
  const [page, setPage] = useState(Number(searchParams.get("page") ?? "1"));
  const [totalPages, setTotalPages] = useState(1);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "no-profile" | "no-runs" | "running" | "no-match" | "failed" | "empty" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [creditError, setCreditError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const listPath = currentPath(location.pathname, location.search);

  useEffect(() => {
    let active = true;
    setState("loading");
    setCreditError(null);
    setRecommendationTotal(null);
    setCompanyCount(null);
    void fetchRecommendationCompanyCount(sort).then((count) => {
      if (active) setCompanyCount(count);
    }).catch(() => undefined);
    Promise.all([
      recommendationsApi.list({ page, page_size: 10, sort }),
      recommendationsApi.runs({ page: 1, page_size: 20 }),
      profileApi.current().catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") return null;
        throw error;
      }),
      creditsApi.summary().catch((error: unknown) => {
        if (active) setCreditError(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "积分加载失败，请稍后重试。");
        return null;
      }),
    ]).then(([response, runsResponse, currentProfile, creditResponse]) => {
      if (!active) return;
      setItems(response.items);
      setCredits(creditResponse);
      setRecommendationTotal(response.total);
      setTotalPages(Math.max(1, Math.ceil(response.total / response.page_size)));
      if (response.total > 0) {
        setState("ready");
        return;
      }
      if (!currentProfile) {
        setState("no-profile");
        return;
      }
      const activeRun = runsResponse.items.find((run) => run.status === "PENDING" || run.status === "RUNNING");
      setActiveRunId(activeRun?.run_id ?? null);
      if (activeRun) {
        setState("running");
        return;
      }
      const latestRun = runsResponse.items[0];
      if (!latestRun) {
        setState("no-runs");
      } else if (latestRun.status === "FAILED") {
        setState("failed");
      } else if (latestRun.status === "SUCCEEDED") {
        setState("no-match");
      } else {
        setState("empty");
      }
    }).catch((error: unknown) => {
      if (!active) return;
      setState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐岗位加载失败，请稍后重试。");
    });
    return () => { active = false; };
  }, [page, sort, retryKey]);

  useEffect(() => {
    if (state !== "loading") restoreListScroll(listPath);
  }, [listPath, state]);

  function changeSort(value: "recommended_at_desc" | "match_score_desc") {
    setSort(value);
    setPage(1);
    setSearchParams({ sort: value, page: "1" });
  }

  async function updateFeedback(item: RecommendationCardView, feedback: RecommendationFeedback) {
    try {
      const response = await recommendationsApi.feedback(item.recommendation_id, feedback);
      setItems((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, feedback: response.feedback } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "反馈保存失败，请稍后重试。");
    }
  }

  async function toggleSaved(item: RecommendationCardView) {
    try {
      const response = item.is_saved ? await jobsApi.unsave(item.job.id) : await jobsApi.save(item.job.id);
      setItems((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, is_saved: response.is_saved } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "收藏状态保存失败，请稍后重试。");
    }
  }

  async function removeRecommendation(item: RecommendationCardView) {
    try {
      await recommendationsApi.remove(item.recommendation_id);
      setItems((current) => current.filter((entry) => entry.recommendation_id !== item.recommendation_id));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "删除推荐失败，请稍后重试。");
    }
  }

  return (
    <div className="recommendations-page">
      <section className="page-intro recommendations-intro">
        <div><div className="eyebrow"><Sparkle size={16} />推荐岗位</div><h1>推荐岗位</h1><p>查看匹配岗位、推荐理由和投递信息。</p></div>
        <div className="recommendations-summary" aria-label="推荐岗位汇总"><strong>{recommendationTotal ?? "—"}</strong><span>个岗位</span><i aria-hidden="true">·</i><strong>{companyCount ?? "—"}</strong><span>家公司</span></div>
      </section>
      <section className="recommendation-toolbar"><div className="credit-summary"><Coins size={20} /><span>当前积分</span><strong>{credits?.balance ?? "..."}</strong><small>单次推荐 {credits?.recommendation_cost ?? "..."}</small></div><label className="sort-field"><span>排序</span><span className="sort-select-wrap"><select value={sort} onChange={(event) => changeSort(event.target.value as typeof sort)}><option value="recommended_at_desc">最新推荐</option><option value="match_score_desc">匹配度最高</option></select><CaretDown className="sort-select-arrow" size={15} aria-hidden="true" /></span></label></section>
      {errorMessage && <p className="form-error inline-page-error" role="alert">{errorMessage}</p>}
      {creditError && <p className="form-error inline-page-error" role="alert">{creditError}</p>}
      {state === "loading" && <RecommendationSkeleton />}
      {state === "error" && <StatePanel title="推荐岗位加载失败" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}
      {state === "no-profile" && <StatePanel title="先填写求职画像" description="先填写目标岗位，才能开始推荐。" actionLabel="填写求职画像" onAction={() => undefined} link="/profile" />}
      {state === "no-runs" && <StatePanel title="还没有推荐记录" description="开始一次推荐后，结果会显示在这里。" actionLabel="开始推荐" onAction={() => undefined} link="/recommendation-runs/new" />}
      {state === "running" && <StatePanel title="正在生成推荐" description="推荐完成后，结果会显示在这里。" actionLabel="查看当前任务" onAction={() => undefined} link={activeRunId ? `/recommendation-runs/${activeRunId}` : "/recommendation-runs"} />}
      {state === "no-match" && <StatePanel title="没有匹配岗位" description="调整求职画像或补充本次要求后再试。" actionLabel="再次推荐" onAction={() => undefined} link="/recommendation-runs/new" />}
      {state === "failed" && <StatePanel title="推荐失败" description="查看任务详情了解原因，或重新开始。" actionLabel="重新开始" onAction={() => undefined} link="/recommendation-runs/new" />}
      {state === "ready" && <><section className="recommendation-grid" aria-label="推荐岗位列表">{items.map((item) => <RecommendationCard key={item.recommendation_id} item={item} returnTo={listPath} onFeedback={(feedback) => void updateFeedback(item, feedback)} onToggleSaved={() => void toggleSaved(item)} onDelete={() => void removeRecommendation(item)} />)}</section><Pagination page={page} totalPages={totalPages} onChange={(next) => { setPage(next); setSearchParams({ sort, page: String(next) }); }} /></>}
    </div>
  );
}

async function fetchRecommendationCompanyCount(sort: "recommended_at_desc" | "match_score_desc"): Promise<number> {
  const pageSize = 50;
  const firstPage = await recommendationsApi.list({ page: 1, page_size: pageSize, sort });
  const pageCount = Math.ceil(firstPage.total / firstPage.page_size);
  const remainingPages = await Promise.all(
    Array.from({ length: Math.max(0, pageCount - 1) }, (_, index) =>
      recommendationsApi.list({ page: index + 2, page_size: pageSize, sort }),
    ),
  );
  return countRecommendationCompanies([firstPage, ...remainingPages].flatMap((page) => page.items));
}

function countRecommendationCompanies(items: RecommendationCardView[]): number {
  return new Set(
    items
      .map((item) => item.job.company_name.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase())
      .filter(Boolean),
  ).size;
}

export function RecommendationRunsPage() {
  const [runs, setRuns] = useState<RecommendationTaskView[]>([]);
  const [hasProfile, setHasProfile] = useState<boolean | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([
      recommendationsApi.runs(),
      profileApi.current().catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") return null;
        throw error;
      }),
    ]).then(([response, currentProfile]) => {
      if (!active) return;
      setRuns(response.items);
      setHasProfile(currentProfile !== null);
      setState("ready");
    }).catch((error: unknown) => {
      if (active) {
        setState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐记录加载失败，请稍后重试。");
      }
    });
    return () => { active = false; };
  }, [retryKey]);

  return <div className="recommendation-runs-page"><section className="page-intro recommendations-intro"><div><div className="eyebrow"><ListChecks size={16} />推荐记录</div><h1>推荐记录</h1><p>创建新的推荐，或查看之前的结果。</p></div></section>{state === "loading" && <RecommendationSkeleton />}{state === "error" && <StatePanel title="推荐记录加载失败" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}{state === "ready" && <><StartRecommendationCard hasProfile={hasProfile === true} /><section className="run-history"><div className="section-heading run-history-heading"><div><span>历史记录</span><h2>之前的推荐</h2></div><span>{runs.length} 次</span></div><section className="run-list" aria-label="推荐记录列表">{runs.length ? runs.map((run) => <RunRow key={run.run_id} run={run} />) : <div className="run-list-empty"><span>还没有推荐记录</span><p>开始一次推荐后，结果会显示在这里。</p></div>}</section></section></>}</div>;
}

export function NewRecommendationPage() {
  const navigate = useNavigate();
  const [credits, setCredits] = useState<CreditSummary | null>(null);
  const [creditsError, setCreditsError] = useState<string | null>(null);
  const [profileState, setProfileState] = useState<"loading" | "present" | "missing" | "error">("loading");
  const [profileError, setProfileError] = useState<string | null>(null);
  const [extraRequest, setExtraRequest] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const keyRef = useRef<string | null>(null);
  useEffect(() => {
    Promise.all([
      creditsApi.summary().then((response) => {
        setCredits(response);
        setCreditsError(null);
      }).catch((error: unknown) => {
        setCredits(null);
        setCreditsError(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "积分加载失败，请稍后重试。");
      }),
      profileApi.current().then(() => {
        setProfileState("present");
        setProfileError(null);
      }).catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") {
          setProfileState("missing");
          return;
        }
        setProfileState("error");
        setProfileError(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "求职画像加载失败，请稍后重试。");
      }),
    ]).catch(() => undefined);
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profileState !== "present") return;
    const key = keyRef.current ?? createIdempotencyKey("recommendation");
    keyRef.current = key;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const accepted = await recommendationsApi.create({ extra_request: extraRequest.trim() || null }, key);
      navigate(`/recommendation-runs/${accepted.run_id}`);
    } catch (error: unknown) {
        setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐创建失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="new-recommendation-page">
      <Link className="back-link" to="/recommendation-runs"><ArrowLeft size={16} /><span>返回推荐记录</span></Link>
      <section className="new-recommendation-panel">
        <div className="new-recommendation-heading">
          <div>
            <div className="eyebrow">新建推荐</div>
            <h1>开始推荐</h1>
            <p>按你的求职画像筛选岗位，补充要求只作用于本次推荐。</p>
          </div>
          <div className="recommendation-flow" aria-label="推荐流程">
            <span className="recommendation-flow-label">推荐流程</span>
            <div><span className="recommendation-flow-step">01</span><span>读取求职画像</span></div>
            <div><span className="recommendation-flow-step">02</span><span>筛选岗位</span></div>
            <div><span className="recommendation-flow-step">03</span><span>生成结果</span></div>
          </div>
        </div>
        <div className="new-recommendation-form-column">
          <div className="recommendation-cost"><Coins size={19} /><span>本次消耗</span><strong>{credits?.recommendation_cost ?? "..."}</strong><small>当前余额 {credits?.balance ?? "..."}</small></div>
          <form className="new-recommendation-form" onSubmit={handleSubmit}>
            <label className="field-group"><span>本次补充要求 <em>可选</em></span><textarea value={extraRequest} placeholder="例如：本次优先推荐 Python 后端岗位" maxLength={1000} onChange={(event) => { setExtraRequest(event.target.value); keyRef.current = null; }} /><small>最多 1000 个字符，只影响本次推荐。</small></label>
            {creditsError && <p className="form-error" role="alert">{creditsError}</p>}
            {profileError && <p className="form-error" role="alert">{profileError}</p>}
            {profileState === "missing" && <div className="profile-required-panel"><strong>先填写求职画像</strong><p>先填写目标岗位，才能开始推荐。</p><Link className="inline-action" to="/profile">填写求职画像<ArrowRight size={16} /></Link></div>}
            {errorMessage && <p className="form-error" role="alert">{errorMessage}</p>}
            <button className="button button-primary" type="submit" disabled={isSubmitting || profileState !== "present"}><Sparkle size={18} />{isSubmitting ? "准备中" : "开始推荐"}</button>
          </form>
        </div>
      </section>
    </div>
  );
}

export function RecommendationRunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const location = useLocation();
  const [task, setTask] = useState<RecommendationTaskView | null>(null);
  const [results, setResults] = useState<RecommendationResultView[]>([]);
  const [profileHighlights, setProfileHighlights] = useState<string[]>([]);
  const [totalJobs, setTotalJobs] = useState<number | null>(null);
  const [resultCompanyCount, setResultCompanyCount] = useState<number | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const runPath = currentPath(location.pathname, location.search);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    let timer: number | undefined;
    let resultsLoaded = false;
    setTotalJobs(null);
    setResultCompanyCount(null);
    setProfileHighlights([]);

    void profileApi.current().then((profile) => {
      if (!active) return;
      setProfileHighlights(buildProfileHighlights(profile));
    }).catch(() => undefined);

    void jobsApi.list({ page: 1, page_size: 1 }).then((response) => {
      if (active) setTotalJobs(response.pool_total);
    }).catch(() => {
      if (active) setTotalJobs(null);
    });

    const poll = async () => {
      try {
        const nextTask = await recommendationsApi.status(runId);
        if (!active) return;
        setTask(nextTask);
        setState("ready");
        if (["SUCCEEDED", "FAILED"].includes(nextTask.status)) {
          if (!resultsLoaded) {
            resultsLoaded = true;
            const resultResponse = await recommendationsApi.results(runId, { page: 1, page_size: 50 });
            if (active) {
              setResults(resultResponse.items);
              setResultCompanyCount(countRecommendationCompanies(resultResponse.items));
            }
          }
          if (timer) window.clearInterval(timer);
        }
      } catch (error: unknown) {
        if (!active) return;
        setState("error");
        setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐状态加载失败，请稍后重试。");
        if (timer) window.clearInterval(timer);
      }
    };

    void poll();
    timer = window.setInterval(() => void poll(), 2000);
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [runId]);

  useEffect(() => {
    if (state === "ready") restoreListScroll(runPath);
  }, [runPath, state]);

  async function updateFeedback(item: RecommendationResultView, feedback: RecommendationFeedback) {
    try {
      const response = await recommendationsApi.feedback(item.recommendation_id, feedback);
      setResults((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, feedback: response.feedback } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "反馈保存失败，请稍后重试。");
    }
  }

  async function toggleSaved(item: RecommendationResultView) {
    try {
      const response = item.is_saved ? await jobsApi.unsave(item.job.id) : await jobsApi.save(item.job.id);
      setResults((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, is_saved: response.is_saved } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "收藏状态保存失败，请稍后重试。");
    }
  }

  async function removeRecommendation(item: RecommendationResultView) {
    try {
      await recommendationsApi.remove(item.recommendation_id);
      setResults((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, is_deleted: true, deleted_at: new Date().toISOString() } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "删除推荐失败，请稍后重试。");
    }
  }

  const displayedProgress = useDisplayedProgress(task);
  const activity = useRunActivity(task?.current_step, task?.status === "PENDING" || task?.status === "RUNNING");
  if (state === "loading") return <RecommendationSkeleton />;
  if (state === "error" || !task) return <StatePanel title="推荐详情加载失败" description={errorMessage ?? "请稍后重试。"} actionLabel="返回推荐记录" onAction={() => undefined} link="/recommendation-runs" />;
  const running = task.status === "PENDING" || task.status === "RUNNING";
  return (
    <div className="run-detail-page">
      <Link className="back-link" to="/recommendation-runs">返回推荐记录</Link>
      <section className="run-detail-header">
        <div>
          <div className="eyebrow"><Clock size={16} />推荐任务</div>
          <h1>{formatRunTitle(task.status)}</h1>
          <p>创建于 {formatDate(task.created_at)}</p>
        </div>
      </section>
      {errorMessage && <p className="form-error inline-page-error" role="alert">{errorMessage}</p>}
      {task.status === "SUCCEEDED" ? <section className="run-complete-panel" aria-label="推荐完成摘要">
        <div className="run-complete-main">
          <span className="run-complete-label">本次推荐</span>
          <div className="run-complete-count"><strong>{task.counts.recommended}</strong><span>个岗位已推荐</span></div>
          <p>{totalJobs !== null ? `从 ${totalJobs} 个岗位中筛选` : "已完成岗位筛选"}</p>
        </div>
        <div className="run-complete-meta">
          <div className="run-complete-company-count"><strong>{resultCompanyCount ?? "—"}</strong><span>家公司已推荐</span></div>
          <div><span>完成时间</span><strong>{formatDate(task.finished_at ?? task.created_at)}</strong></div>
        </div>
      </section> : <section className="run-progress-panel">
        <div className="run-progress-copy"><div><span>当前步骤</span><strong>{formatRecommendationStep(task.current_step)}</strong></div><strong>{displayedProgress}%</strong></div>
        <div className="run-progress-track" role="progressbar" aria-label="推荐进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={displayedProgress}><span className="run-progress-fill" style={{ transform: `scaleX(${displayedProgress / 100})` }} /></div>
        {running && <>
          <div className="run-progress-hint">进度会随任务阶段完成更新。</div>
          <div className="run-search-visual">
            <div className="run-search-header"><span>正在处理推荐任务</span></div>
            <div className="run-search-pills">{(profileHighlights.length ? profileHighlights : ["综合条件"]).slice(0, 6).map((highlight) => <span key={highlight}>{highlight}</span>)}</div>
            <div className="run-activity" role="status" aria-live="polite"><MagnifyingGlass size={16} /><span>{activity}</span></div>
          </div>
        </>}
        <div className="run-counts"><span>从 {totalJobs ?? "..."} 个岗位中筛选</span><span>已推荐 {task.counts.recommended}</span></div>
      </section>}
      {task.status === "FAILED" && <section className="run-failure-panel" role="alert"><WarningCircle size={21} /><div><strong>推荐失败</strong><p>{task.error?.message ?? "服务不可用，请稍后重试。"}</p>{task.credits.refunded && <span>本次积分已退回</span>}<Link className="inline-action" to="/recommendation-runs/new">重新开始<ArrowRight size={16} /></Link></div></section>}
      {task.status === "SUCCEEDED" && <section className="run-result-section"><div className="section-heading"><div><h2>推荐结果</h2><p>按匹配度查看岗位，点击岗位名称查看详情。</p></div></div>{results.length ? <div className="recommendation-grid">{results.map((item) => <RecommendationCard key={item.recommendation_id} item={item} returnTo={runPath} onFeedback={(feedback) => void updateFeedback(item, feedback)} onToggleSaved={() => void toggleSaved(item)} onDelete={() => void removeRecommendation(item)} />)}</div> : <div className="inline-empty"><CheckCircle size={24} /><strong>没有匹配岗位</strong><p>调整求职画像或补充本次要求后再试。</p><div className="inline-empty-actions"><Link className="button button-secondary" to="/profile">修改画像</Link><Link className="button button-primary" to="/recommendation-runs/new">再次推荐</Link></div></div>}</section>}
    </div>
  );
}

function RunRow({ run }: { run: RecommendationTaskView }) {
  return <Link className="run-row" to={`/recommendation-runs/${run.run_id}`}><div className="run-row-icon"><ListChecks size={20} /></div><div className="run-row-main"><strong>{formatRecommendationStatus(run.status)}</strong><span>{formatDate(run.created_at)} 创建 · {formatRecommendationStep(run.current_step)}</span></div><div className="run-row-count"><strong>{run.counts.recommended}</strong><span>个推荐</span></div><ArrowRight size={19} /></Link>;
}

function StartRecommendationCard({ hasProfile }: { hasProfile: boolean }) {
  return <section className="run-start-card"><div className="run-start-card-copy"><span className="profile-empty-kicker">开始推荐</span><h2>{hasProfile ? "创建新的推荐" : "先填写求职画像"}</h2><p>{hasProfile ? "根据当前求职画像生成推荐。" : "先填写目标岗位，才能开始推荐。"}</p></div><Link className="button button-primary" to={hasProfile ? "/recommendation-runs/new" : "/profile"}>{hasProfile ? "开始推荐" : "填写求职画像"}<ArrowRight size={17} /></Link></section>;
}

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return <nav className="pagination" aria-label="推荐分页"><button className="icon-button" type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}>‹</button><span>第 {page} / {totalPages} 页</span><button className="icon-button" type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>›</button></nav>;
}

function RecommendationSkeleton() {
  return <section className="recommendation-grid" aria-busy="true" aria-label="正在加载推荐"><div className="recommendation-skeleton"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div><div className="recommendation-skeleton"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div></section>;
}

function StatePanel({ title, description, actionLabel, onAction, link }: { title: string; description: string; actionLabel: string; onAction: () => void; link?: string }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p>{link ? <Link className="button button-primary" to={link}>{actionLabel}</Link> : <button className="button button-primary" type="button" onClick={onAction}>{actionLabel}</button>}</section>;
}

function useDisplayedProgress(task: RecommendationTaskView | null) {
  const [displayedProgress, setDisplayedProgress] = useState(0);
  const targetProgressRef = useRef(0);
  const isRunning = task?.status === "PENDING" || task?.status === "RUNNING";

  useEffect(() => {
    targetProgressRef.current = 0;
    setDisplayedProgress(0);
  }, [task?.run_id]);

  useEffect(() => {
    if (!task) return;
    targetProgressRef.current = Math.max(targetProgressRef.current, task.progress_percent);
  }, [task?.progress_percent]);

  useEffect(() => {
    if (!task) {
      targetProgressRef.current = 0;
      setDisplayedProgress(0);
      return;
    }
    if (!isRunning) {
      const finalProgress = task.status === "SUCCEEDED" ? 100 : task.progress_percent;
      targetProgressRef.current = finalProgress;
      setDisplayedProgress(finalProgress);
      return;
    }

    const tick = () => {
      targetProgressRef.current = Math.max(targetProgressRef.current, task.progress_percent);
      setDisplayedProgress((current) => {
        const gap = targetProgressRef.current - current;
        if (gap <= 0.05) return current;
        return Math.min(targetProgressRef.current, current + Math.min(0.7, Math.max(0.08, gap * 0.2)));
      });
    };

    tick();
    const timer = window.setInterval(tick, 220);
    return () => window.clearInterval(timer);
  }, [isRunning, task?.run_id, task?.status]);

  return Math.max(0, Math.min(100, Math.round(displayedProgress)));
}

function formatRunTitle(status: RecommendationTaskView["status"]): string {
  if (status === "SUCCEEDED") return "推荐完成";
  if (status === "FAILED") return "推荐失败";
  return "正在生成推荐";
}

const RUN_ACTIVITY: Record<Exclude<RecommendationTaskView["current_step"], null>, string[]> = {
  PENDING: ["正在准备推荐任务", "正在整理推荐条件"],
  PROFILE: ["正在读取求职画像", "正在整理推荐条件"],
  FILTER: ["正在应用筛选条件", "正在准备岗位池"],
  RETRIEVE: ["正在筛选开放岗位", "正在检索相关岗位"],
  EVALUATE: ["正在比较岗位要求", "正在评估匹配条件"],
  SAVE: ["正在整理推荐结果", "正在保存匹配岗位"],
  COMPLETE: ["正在完成推荐任务"],
};

function useRunActivity(step: RecommendationTaskView["current_step"] | undefined, running: boolean): string {
  const messages = step && RUN_ACTIVITY[step] ? RUN_ACTIVITY[step] : ["正在处理推荐任务"];
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    if (!running || messages.length <= 1) return;
    const timer = window.setInterval(() => setIndex((current) => (current + 1) % messages.length), 2200);
    return () => window.clearInterval(timer);
  }, [running, step, messages.length]);

  return messages[index % messages.length];
}

function buildProfileHighlights(profile: ProfileView): string[] {
  const experienceKeywords = (profile.experience_summary ?? "")
    .split(/[，。；、,.;\s/]+/)
    .map((value) => value.trim())
    .filter((value) => value.length >= 2 && value.length <= 18)
    .slice(0, 5)
    .map((value) => `经历 ${value}`);
  const values = [
    "综合条件",
    ...profile.target_roles.map((value) => `方向 ${value}`),
    ...profile.target_locations.map((value) => `地点 ${value}`),
    ...profile.recruitment_types,
    ...profile.skills,
    profile.education,
    profile.graduation_year ? `${profile.graduation_year} 届` : null,
    ...experienceKeywords,
  ];
  return [...new Set(values.filter((value): value is string => Boolean(value)))].slice(0, 14);
}
