import { useEffect, useState } from "react";
import { BookmarkSimple, MapPin, WarningCircle, X } from "@phosphor-icons/react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { jobsApi } from "../../shared/api/jobs";
import { savedJobsApi } from "../../shared/api/savedJobs";
import type { SavedJobView } from "../../shared/api/types";
import { formatDate, formatJobStatus, formatSalaryRange } from "../../shared/formatting";
import { currentPath, jobDetailPath, restoreListScroll, saveListScroll } from "../../shared/navigation";

export function SavedJobsPage() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1");
  const [items, setItems] = useState<SavedJobView[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const listPath = currentPath(location.pathname, location.search);

  useEffect(() => {
    let active = true;
    setState("loading");
    savedJobsApi.list({ page, page_size: 10 }).then((response) => {
      if (!active) return;
      setItems(response.items);
      setTotalPages(Math.max(1, Math.ceil(response.total / response.page_size)));
      setState(response.items.length ? "ready" : "empty");
    }).catch((error: unknown) => {
      if (!active) return;
      setState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "收藏岗位加载失败，请稍后重试。");
    });
    return () => { active = false; };
  }, [page, retryKey]);

  useEffect(() => {
    if (state === "ready" || state === "empty") restoreListScroll(listPath);
  }, [listPath, state]);

  async function removeSaved(item: SavedJobView) {
    try {
      await jobsApi.unsave(item.job.id);
      setItems((current) => current.filter((entry) => entry.job.id !== item.job.id));
      if (items.length === 1 && page > 1) setSearchParams({ page: String(page - 1) });
      else if (items.length === 1) setState("empty");
    } catch (error: unknown) {
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "取消收藏失败，请稍后重试。");
    }
  }

  return <div className="saved-jobs-page"><section className="page-intro saved-jobs-intro"><div><div className="eyebrow"><BookmarkSimple size={16} />收藏岗位</div><h1>我的收藏</h1><p>收藏的岗位会显示在这里。</p></div><div className="intro-note"><BookmarkSimple size={20} /><div><strong>{state === "ready" ? items.length : "..."}</strong><span>已收藏</span></div></div></section>{errorMessage && <p className="form-error inline-page-error" role="alert">{errorMessage}</p>}{state === "loading" && <SavedJobsSkeleton />}{state === "error" && <StatePanel title="收藏岗位加载失败" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}{state === "empty" && <StatePanel title="还没有收藏岗位" description="在岗位池或推荐结果中收藏岗位后，会显示在这里。" actionLabel="去岗位池" link="/jobs" onAction={() => undefined} />}{state === "ready" && <><section className="saved-job-list" aria-label="收藏岗位列表">{items.map((item) => <SavedJobCard key={item.job.id} item={item} returnTo={listPath} onRemove={() => void removeSaved(item)} />)}</section><Pagination page={page} totalPages={totalPages} onChange={(next) => setSearchParams({ page: String(next) })} /></>}</div>;
}

function SavedJobCard({ item, returnTo, onRemove }: { item: SavedJobView; returnTo: string; onRemove: () => void }) {
  const { job } = item;
  const isClosed = job.status === "CLOSED";
  return <article className="saved-job-card"><div className="saved-job-card-topline"><span className={`detail-status ${isClosed ? "detail-status-closed" : ""}`}>{formatJobStatus(job.status)}</span><span>收藏于 {formatDate(item.saved_at)}</span></div><Link className="saved-job-link" to={jobDetailPath(job.id, returnTo)} onClick={() => saveListScroll(returnTo)}><h2>{job.title}</h2><p>{job.company_name}</p><div className="saved-job-meta"><span><MapPin size={16} />{job.locations.join("、") || "地点待确认"}</span>{job.recruitment_type && <span>{job.recruitment_type}</span>}{job.education_requirement && <span>{job.education_requirement}</span>}</div><strong>{formatSalaryRange(job.salary_min, job.salary_max, job.salary_months)}</strong></Link><button className="text-button danger-text saved-remove" type="button" onClick={onRemove}><X size={16} />取消收藏</button></article>;
}

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return <nav className="pagination" aria-label="收藏岗位分页"><button className="icon-button" type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}>‹</button><span>第 {page} / {totalPages} 页</span><button className="icon-button" type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>›</button></nav>;
}

function SavedJobsSkeleton() {
  return <section className="saved-job-list" aria-busy="true" aria-label="正在加载收藏岗位"><div className="saved-job-card skeleton-card"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /></div><div className="saved-job-card skeleton-card"><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /></div></section>;
}

function StatePanel({ title, description, actionLabel, onAction, link }: { title: string; description: string; actionLabel: string; onAction: () => void; link?: string }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p>{link ? <Link className="button button-secondary" to={link}>{actionLabel}</Link> : <button className="button button-secondary" type="button" onClick={onAction}>{actionLabel}</button>}</section>;
}
