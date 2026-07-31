import { useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle, Clock, Coins, ListChecks, Plus, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { createIdempotencyKey } from "../../shared/api/idempotency";
import { jobsApi } from "../../shared/api/jobs";
import { creditsApi, recommendationsApi } from "../../shared/api/recommendations";
import type { CreditSummary, RecommendationCardView, RecommendationFeedback, RecommendationResultView, RecommendationTaskView } from "../../shared/api/types";
import { formatDate, formatRecommendationStatus, formatRecommendationStep } from "../../shared/formatting";
import { RecommendationCard } from "./RecommendationCard";

export function AllRecommendationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<RecommendationCardView[]>([]);
  const [credits, setCredits] = useState<CreditSummary | null>(null);
  const [sort, setSort] = useState<"recommended_at_desc" | "match_score_desc">((searchParams.get("sort") as "recommended_at_desc" | "match_score_desc") || "recommended_at_desc");
  const [page, setPage] = useState(Number(searchParams.get("page") ?? "1"));
  const [totalPages, setTotalPages] = useState(1);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [creditError, setCreditError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    setState("loading");
    setCreditError(null);
    Promise.all([recommendationsApi.list({ page, page_size: 10, sort }), creditsApi.summary().catch((error: unknown) => {
      if (active) setCreditError(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "积分暂时无法加载，请稍后重试。");
      return null;
    })]).then(([response, creditResponse]) => {
      if (!active) return;
      setItems(response.items);
      setCredits(creditResponse);
      setTotalPages(Math.max(1, Math.ceil(response.total / response.page_size)));
      setState(response.items.length ? "ready" : "empty");
    }).catch((error: unknown) => {
      if (!active) return;
      setState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐列表暂时无法加载，请稍后重试。");
    });
    return () => { active = false; };
  }, [page, sort, retryKey]);

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
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "反馈暂时无法保存，请稍后重试。");
    }
  }

  async function toggleSaved(item: RecommendationCardView) {
    try {
      const response = item.is_saved ? await jobsApi.unsave(item.job.id) : await jobsApi.save(item.job.id);
      setItems((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, is_saved: response.is_saved } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "收藏状态暂时无法保存，请稍后重试。");
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
        <div><div className="eyebrow"><Sparkle size={16} />全部推荐</div><h1>推荐结果，留给你自己判断。</h1><p>每张卡片只展示推荐依据。岗位事实和投递入口统一从岗位详情查看。</p></div>
        <Link className="button button-primary" to="/recommendation-runs/new"><Plus size={18} />新建推荐</Link>
      </section>
      <section className="recommendation-toolbar"><div className="credit-summary"><Coins size={20} /><span>当前积分</span><strong>{credits?.balance ?? "..."}</strong><small>单次推荐 {credits?.recommendation_cost ?? "..."}</small></div><label className="sort-field"><span>排序</span><select value={sort} onChange={(event) => changeSort(event.target.value as typeof sort)}><option value="recommended_at_desc">最新推荐</option><option value="match_score_desc">匹配度最高</option></select></label></section>
      {errorMessage && <p className="form-error inline-page-error" role="alert">{errorMessage}</p>}
      {creditError && <p className="form-error inline-page-error" role="alert">{creditError}</p>}
      {state === "loading" && <RecommendationSkeleton />}
      {state === "error" && <StatePanel title="推荐列表暂时不可用" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}
      {state === "empty" && <StatePanel title="还没有推荐结果" description="先保存一份求职画像，再创建推荐任务。" actionLabel="去完善画像" onAction={() => undefined} link="/profile" />}
      {state === "ready" && <><section className="recommendation-grid" aria-label="全部推荐">{items.map((item) => <RecommendationCard key={item.recommendation_id} item={item} onFeedback={(feedback) => void updateFeedback(item, feedback)} onToggleSaved={() => void toggleSaved(item)} onDelete={() => void removeRecommendation(item)} />)}</section><Pagination page={page} totalPages={totalPages} onChange={(next) => { setPage(next); setSearchParams({ sort, page: String(next) }); }} /></>}
    </div>
  );
}

export function RecommendationRunsPage() {
  const [runs, setRuns] = useState<RecommendationTaskView[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    let active = true;
    recommendationsApi.runs().then((response) => { if (active) { setRuns(response.items); setState(response.items.length ? "ready" : "empty"); } }).catch((error: unknown) => { if (active) { setState("error"); setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐任务暂时无法加载，请稍后重试。"); } });
    return () => { active = false; };
  }, [retryKey]);

  return <div className="recommendation-runs-page"><section className="page-intro recommendations-intro"><div><div className="eyebrow"><ListChecks size={16} />推荐任务</div><h1>每次推荐，都留下一条可追溯记录。</h1><p>任务运行期间展示接口返回的步骤和进度。失败任务会明确显示退款状态。</p></div><Link className="button button-primary" to="/recommendation-runs/new"><Plus size={18} />新建推荐</Link></section>{state === "loading" && <RecommendationSkeleton />}{state === "error" && <StatePanel title="推荐任务暂时不可用" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}{state === "empty" && <StatePanel title="还没有推荐任务" description="保存求职画像后，可以创建第一条推荐任务。" actionLabel="完善求职画像" onAction={() => undefined} link="/profile" />}{state === "ready" && <section className="run-list" aria-label="推荐任务列表">{runs.map((run) => <RunRow key={run.run_id} run={run} />)}</section>}</div>;
}

export function NewRecommendationPage() {
  const navigate = useNavigate();
  const [credits, setCredits] = useState<CreditSummary | null>(null);
  const [creditsError, setCreditsError] = useState<string | null>(null);
  const [extraRequest, setExtraRequest] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const keyRef = useRef<string | null>(null);
  useEffect(() => {
    creditsApi.summary().then((response) => {
      setCredits(response);
      setCreditsError(null);
    }).catch((error: unknown) => {
      setCredits(null);
      setCreditsError(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "积分暂时无法加载，请稍后重试。");
    });
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = keyRef.current ?? createIdempotencyKey("recommendation");
    keyRef.current = key;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const accepted = await recommendationsApi.create({ extra_request: extraRequest.trim() || null }, key);
      navigate(`/recommendation-runs/${accepted.run_id}`);
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐任务创建失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return <div className="new-recommendation-page"><Link className="back-link" to="/recommendation-runs">返回推荐任务</Link><section className="new-recommendation-panel"><div className="new-recommendation-heading"><div className="auth-icon"><Sparkle size={22} /></div><div><div className="eyebrow">新建推荐</div><h1>用已保存的画像找一次岗位。</h1><p>推荐任务会读取当前最新画像。下面的补充要求只影响这一次评估。</p></div></div><div className="recommendation-cost"><Coins size={19} /><span>本次消耗</span><strong>{credits?.recommendation_cost ?? "..."}</strong><small>当前余额 {credits?.balance ?? "..."}</small></div><form className="new-recommendation-form" onSubmit={handleSubmit}><label className="field-group"><span>本次补充要求</span><textarea value={extraRequest} placeholder="例如：本次优先推荐 Python 后端岗位" maxLength={1000} onChange={(event) => { setExtraRequest(event.target.value); keyRef.current = null; }} /><small>可不填，最多 1000 个字符。</small></label>{creditsError && <p className="form-error" role="alert">{creditsError}</p>}{errorMessage && <p className="form-error" role="alert">{errorMessage}</p>}{errorMessage?.includes("画像") && <Link className="inline-action" to="/profile">去完善求职画像<ArrowRight size={16} /></Link>}<button className="button button-primary" type="submit" disabled={isSubmitting}><Sparkle size={18} />{isSubmitting ? "创建中" : "开始推荐"}</button></form></section></div>;
}

export function RecommendationRunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [task, setTask] = useState<RecommendationTaskView | null>(null);
  const [results, setResults] = useState<RecommendationResultView[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    let timer: number | undefined;
    let resultsLoaded = false;

    const poll = async () => {
      try {
        const nextTask = await recommendationsApi.status(runId);
        if (!active) return;
        setTask(nextTask);
        setState("ready");
        if (["SUCCEEDED", "FAILED"].includes(nextTask.status)) {
          if (!resultsLoaded) {
            resultsLoaded = true;
            const resultResponse = await recommendationsApi.results(runId);
            if (active) setResults(resultResponse.items);
          }
          if (timer) window.clearInterval(timer);
        }
      } catch (error: unknown) {
        if (!active) return;
        setState("error");
        setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "推荐任务状态暂时无法加载，请稍后重试。");
        if (timer) window.clearInterval(timer);
      }
    };

    void poll();
    timer = window.setInterval(() => void poll(), 2000);
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [runId]);

  async function updateFeedback(item: RecommendationResultView, feedback: RecommendationFeedback) {
    try {
      const response = await recommendationsApi.feedback(item.recommendation_id, feedback);
      setResults((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, feedback: response.feedback } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "反馈暂时无法保存，请稍后重试。");
    }
  }

  async function toggleSaved(item: RecommendationResultView) {
    try {
      const response = item.is_saved ? await jobsApi.unsave(item.job.id) : await jobsApi.save(item.job.id);
      setResults((current) => current.map((entry) => entry.recommendation_id === item.recommendation_id ? { ...entry, is_saved: response.is_saved } : entry));
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "收藏状态暂时无法保存，请稍后重试。");
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

  if (state === "loading") return <RecommendationSkeleton />;
  if (state === "error" || !task) return <StatePanel title="推荐任务暂时不可用" description={errorMessage ?? "请稍后重试。"} actionLabel="返回推荐任务" onAction={() => undefined} link="/recommendation-runs" />;
  const running = task.status === "PENDING" || task.status === "RUNNING";
  return <div className="run-detail-page"><Link className="back-link" to="/recommendation-runs">返回推荐任务</Link><section className="run-detail-header"><div><div className="eyebrow"><Clock size={16} />推荐任务</div><h1>{formatRecommendationStatus(task.status)}</h1><p>任务编号 {task.run_id}，创建于 {formatDate(task.created_at)}</p></div><div className={`run-status-badge run-status-${task.status.toLowerCase()}`}>{formatRecommendationStatus(task.status)}</div></section>{errorMessage && <p className="form-error inline-page-error" role="alert">{errorMessage}</p>}<section className="run-progress-panel"><div className="run-progress-copy"><div><span>当前步骤</span><strong>{formatRecommendationStep(task.current_step)}</strong></div><strong>{task.progress_percent}%</strong></div><div className="run-progress-track" aria-label={`推荐进度 ${task.progress_percent}%`}><span style={{ width: `${task.progress_percent}%` }} /></div><div className="run-counts"><span>已评估 {task.counts.evaluated}</span><span>已推荐 {task.counts.recommended}</span>{running && <span>每 2 秒更新状态</span>}</div></section>{task.status === "FAILED" && <section className="run-failure-panel" role="alert"><WarningCircle size={21} /><div><strong>推荐任务失败</strong><p>{task.error?.message ?? "服务暂时不可用，请稍后重试。"}</p>{task.credits.refunded && <span>本次积分已退回</span>}</div></section>}{task.status === "SUCCEEDED" && <section className="run-result-section"><div className="section-heading"><div><h2>本次推荐结果</h2><p>点击岗位名称查看统一岗位详情。</p></div></div>{results.length ? <div className="recommendation-grid">{results.map((item) => <RecommendationCard key={item.recommendation_id} item={item} onFeedback={(feedback) => void updateFeedback(item, feedback)} onToggleSaved={() => void toggleSaved(item)} onDelete={() => void removeRecommendation(item)} />)}</div> : <div className="inline-empty"><CheckCircle size={24} /><strong>这次没有匹配岗位</strong><p>任务已完成，但没有符合画像和本次要求的结果。</p></div>}</section>}</div>;
}

function RunRow({ run }: { run: RecommendationTaskView }) {
  return <Link className="run-row" to={`/recommendation-runs/${run.run_id}`}><div className="run-row-icon"><ListChecks size={20} /></div><div className="run-row-main"><strong>{formatRecommendationStatus(run.status)}</strong><span>{formatDate(run.created_at)} 创建 · {formatRecommendationStep(run.current_step)}</span></div><div className="run-row-count"><strong>{run.progress_percent}%</strong><span>{run.counts.recommended} 个推荐</span></div><ArrowRight size={19} /></Link>;
}

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return <nav className="pagination" aria-label="推荐分页"><button className="icon-button" type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}>‹</button><span>第 {page} / {totalPages} 页</span><button className="icon-button" type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>›</button></nav>;
}

function RecommendationSkeleton() {
  return <section className="recommendation-grid" aria-busy="true" aria-label="正在加载推荐"><div className="recommendation-skeleton"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div><div className="recommendation-skeleton"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div></section>;
}

function StatePanel({ title, description, actionLabel, onAction, link }: { title: string; description: string; actionLabel: string; onAction: () => void; link?: string }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p>{link ? <Link className="button button-secondary" to={link}>{actionLabel}</Link> : <button className="button button-secondary" type="button" onClick={onAction}>{actionLabel}</button>}</section>;
}
