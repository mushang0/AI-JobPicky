import { useEffect, useState } from "react";
import { ArrowLeft, ArrowSquareOut, BookmarkSimple, Briefcase, CalendarBlank, GraduationCap, MapPin, Money, WarningCircle } from "@phosphor-icons/react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../../adapters/web/AuthProvider";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { jobsApi } from "../../shared/api/jobs";
import type { JobDetailView } from "../../shared/api/types";
import { formatDate, formatJobStatus, formatSalaryRange } from "../../shared/formatting";

type LoadState = "loading" | "ready" | "error";

function loginPath(returnTo: string): string {
  return `/login?returnTo=${encodeURIComponent(returnTo)}`;
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { status: authStatus } = useAuth();
  const [job, setJob] = useState<JobDetailView | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    setLoadState("loading");
    setErrorMessage(null);
    jobsApi.detail(jobId).then((response) => {
      if (!active) return;
      setJob(response);
      setLoadState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "岗位详情暂时无法加载，请稍后重试。");
    });
    return () => {
      active = false;
    };
  }, [jobId, retryKey]);

  async function toggleSaved() {
    if (!job) return;
    if (authStatus !== "authenticated") {
      navigate(loginPath(`/jobs/${job.id}`));
      return;
    }

    setIsSaving(true);
    try {
      const saved = job.is_saved ? await jobsApi.unsave(job.id) : await jobsApi.save(job.id);
      setJob((current) => current ? { ...current, is_saved: saved.is_saved } : current);
    } catch (error: unknown) {
      if (error instanceof ApiError) setErrorMessage(getApiErrorMessage(error.code, error.message));
    } finally {
      setIsSaving(false);
    }
  }

  if (loadState === "loading") return <DetailSkeleton />;

  if (loadState === "error" || !job) {
    return <section className="state-panel detail-state" role="status"><WarningCircle size={28} /><h1>岗位详情暂时不可用</h1><p>{errorMessage ?? "请稍后重试。"}</p><div className="detail-state-actions"><button className="button button-primary" type="button" onClick={() => setRetryKey((current) => current + 1)}>重新加载</button><button className="button button-secondary" type="button" onClick={() => navigate(-1)}>返回岗位池</button></div></section>;
  }

  const isClosed = job.status === "CLOSED";
  return (
    <div className="job-detail-page">
      <Link className="back-link" to="/jobs"><ArrowLeft size={18} />返回岗位池</Link>
      <section className="detail-hero">
        <div>
          <span className={`detail-status ${isClosed ? "detail-status-closed" : ""}`}>{formatJobStatus(job.status)}</span>
          <h1>{job.title}</h1>
          <p className="detail-company">{job.company_name} · {job.source.name}</p>
        </div>
        <button className="button button-secondary detail-save-button" type="button" disabled={isSaving} aria-pressed={job.is_saved === true} onClick={() => void toggleSaved()}><BookmarkSimple size={18} weight={job.is_saved ? "fill" : "regular"} />{job.is_saved ? "已收藏" : "收藏岗位"}</button>
      </section>

      <section className="detail-facts" aria-label="岗位信息">
        <Fact icon={<MapPin size={19} />} label="工作地点" value={job.locations.join("、") || "地点待确认"} />
        <Fact icon={<Money size={19} />} label="薪资范围" value={formatSalaryRange(job.salary_min, job.salary_max, job.salary_months)} />
        <Fact icon={<GraduationCap size={19} />} label="学历要求" value={job.education_requirement ?? "学历待确认"} />
        <Fact icon={<Briefcase size={19} />} label="招聘类型" value={job.recruitment_type ?? "类型待确认"} />
        <Fact icon={<CalendarBlank size={19} />} label="最后确认" value={formatDate(job.last_confirmed_at)} />
      </section>

      <section className="detail-content-grid">
        <article className="detail-description">
          <h2>岗位描述</h2>
          <p>{job.description ?? job.description_preview ?? "岗位描述待确认。"}</p>
        </article>
        <aside className="detail-side-panel">
          <h2>投递入口</h2>
          {isClosed ? (
            <p className="closed-note">该岗位已关闭，暂不可投递。</p>
          ) : job.apply_url ? (
            <a className="button button-primary apply-button" href={job.apply_url} target="_blank" rel="noreferrer">前往官方投递<ArrowSquareOut size={17} /></a>
          ) : (
            <p className="closed-note">官方投递入口待确认。</p>
          )}
          <div className="detail-side-meta"><span>岗位来源</span><strong>{job.source.name}</strong><span>首次发现</span><strong>{formatDate(job.first_seen_at)}</strong></div>
        </aside>
      </section>
    </div>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="detail-fact"><span className="detail-fact-icon">{icon}</span><span>{label}</span><strong>{value}</strong></div>;
}

function DetailSkeleton() {
  return <section className="detail-skeleton" aria-busy="true" aria-label="正在加载岗位详情"><span className="skeleton-line skeleton-short" /><span className="skeleton-line detail-skeleton-title" /><span className="skeleton-line skeleton-medium" /><div className="detail-skeleton-grid"><span className="skeleton-line" /><span className="skeleton-line" /><span className="skeleton-line" /><span className="skeleton-line" /></div><span className="skeleton-line detail-skeleton-body" /><span className="skeleton-line detail-skeleton-body" /><span className="skeleton-line detail-skeleton-body" /></section>;
}
