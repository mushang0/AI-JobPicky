import { useEffect, useMemo, useState } from "react";
import { BookmarkSimple, Briefcase, CaretLeft, CaretRight, Funnel, MagnifyingGlass, WarningCircle, X } from "@phosphor-icons/react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../adapters/web/AuthProvider";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { jobsApi } from "../../shared/api/jobs";
import type { JobFilterOptions, JobListItem, JobQuery, JobsPageResponse } from "../../shared/api/types";
import { formatDate, formatSalaryRange } from "../../shared/formatting";
import { validateJobQuery } from "../../shared/validation/jobs";

type LoadState = "loading" | "ready" | "empty" | "error";

interface FilterDraft {
  q: string;
  city: string[];
  companyNature: string[];
  sourceId: string[];
  recruitmentType: string[];
  education: string[];
  graduationYear: string[];
  salaryMin: string;
  salaryMax: string;
  pageSize: string;
}

const emptyDraft: FilterDraft = {
  q: "",
  city: [],
  companyNature: [],
  sourceId: [],
  recruitmentType: [],
  education: [],
  graduationYear: [],
  salaryMin: "",
  salaryMax: "",
  pageSize: "30",
};

function readDraft(params: URLSearchParams): FilterDraft {
  return {
    q: params.get("q") ?? "",
    city: params.getAll("city"),
    companyNature: params.getAll("company_nature"),
    sourceId: params.getAll("source_id"),
    recruitmentType: params.getAll("recruitment_type"),
    education: params.getAll("education"),
    graduationYear: params.getAll("graduation_year"),
    salaryMin: params.get("salary_min") ?? "",
    salaryMax: params.get("salary_max") ?? "",
    pageSize: params.get("page_size") ?? "30",
  };
}

function readQuery(params: URLSearchParams): JobQuery {
  const numberOrUndefined = (value: string | null): number | undefined => {
    if (!value) return undefined;
    const number = Number(value);
    return Number.isFinite(number) ? number : undefined;
  };
  const many = (key: string): string[] | undefined => {
    const values = params.getAll(key).filter(Boolean);
    return values.length > 0 ? values : undefined;
  };
  const graduationYears = params.getAll("graduation_year").map(Number).filter(Number.isInteger);

  return {
    page: numberOrUndefined(params.get("page")) ?? 1,
    page_size: numberOrUndefined(params.get("page_size")) ?? 30,
    q: params.get("q") ?? undefined,
    city: many("city"),
    company_nature: many("company_nature"),
    source_id: many("source_id"),
    recruitment_type: many("recruitment_type"),
    education: many("education"),
    graduation_year: graduationYears.length > 0 ? graduationYears : undefined,
    salary_min: numberOrUndefined(params.get("salary_min")),
    salary_max: numberOrUndefined(params.get("salary_max")),
  };
}

function loginPath(returnTo: string): string {
  return `/login?returnTo=${encodeURIComponent(returnTo)}`;
}

export function JobsPage() {
  const { status } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryString = searchParams.toString();
  const query = useMemo(() => readQuery(searchParams), [queryString]);
  const [draft, setDraft] = useState<FilterDraft>(() => readDraft(searchParams));
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [jobs, setJobs] = useState<JobsPageResponse | null>(null);
  const [filters, setFilters] = useState<JobFilterOptions | null>(null);
  const [filterErrorMessage, setFilterErrorMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [savingJobId, setSavingJobId] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    setDraft(readDraft(searchParams));
  }, [queryString]);

  useEffect(() => {
    let active = true;
    jobsApi.filterOptions().then((response) => {
      if (active) {
        setFilters(response);
        setFilterErrorMessage(null);
      }
    }).catch(() => {
      if (active) setFilterErrorMessage("筛选配置暂时无法加载，当前可以先使用关键词搜索。");
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const validationMessage = validateJobQuery(query);
    if (validationMessage) {
      setLoadState("error");
      setErrorMessage(validationMessage);
      return;
    }

    let active = true;
    setLoadState("loading");
    setErrorMessage(null);
    jobsApi.list(query).then((response) => {
      if (!active) return;
      setJobs(response);
      setLoadState(response.items.length ? "ready" : "empty");
    }).catch((error: unknown) => {
      if (!active) return;
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "岗位暂时无法加载，请稍后重试。");
    });

    return () => {
      active = false;
    };
  }, [queryString, retryKey]);

  function updateDraft(field: keyof FilterDraft, value: string | string[]) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function applyFilters(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if ((draft.salaryMin && !/^\d+$/.test(draft.salaryMin)) || (draft.salaryMax && !/^\d+$/.test(draft.salaryMax))) {
      setLoadState("error");
      setErrorMessage("薪资范围请输入数字。");
      return;
    }
    if (draft.salaryMin && draft.salaryMax && Number(draft.salaryMin) > Number(draft.salaryMax)) {
      setLoadState("error");
      setErrorMessage("薪资下限不能高于薪资上限。");
      return;
    }
    const next = new URLSearchParams();
    const values: Array<[string, string | string[]]> = [
      ["q", draft.q.trim()],
      ["city", draft.city],
      ["company_nature", draft.companyNature],
      ["source_id", draft.sourceId],
      ["recruitment_type", draft.recruitmentType],
      ["education", draft.education],
      ["graduation_year", draft.graduationYear],
      ["salary_min", draft.salaryMin],
      ["salary_max", draft.salaryMax],
    ];
    values.forEach(([key, value]) => {
      if (Array.isArray(value)) {
        value.forEach((item) => next.append(key, item));
      } else if (value) {
        next.set(key, value);
      }
    });
    next.set("page", "1");
    next.set("page_size", draft.pageSize || "30");
    setSearchParams(next);
  }

  function clearFilters() {
    setSearchParams({ page: "1", page_size: "30" });
  }

  function goToPage(page: number) {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(page));
    setSearchParams(next);
  }

  async function toggleSaved(job: JobListItem) {
    const returnTo = `/jobs${queryString ? `?${queryString}` : ""}`;
    if (status !== "authenticated") {
      navigate(loginPath(returnTo));
      return;
    }

    setSavingJobId(job.id);
    try {
      const saved = job.is_saved ? await jobsApi.unsave(job.id) : await jobsApi.save(job.id);
      setJobs((current) => current ? { ...current, items: current.items.map((item) => item.id === job.id ? { ...item, is_saved: saved.is_saved } : item) } : current);
    } catch (error: unknown) {
      if (error instanceof ApiError) setErrorMessage(getApiErrorMessage(error.code, error.message));
    } finally {
      setSavingJobId(null);
    }
  }

  const totalPages = jobs ? Math.max(1, Math.ceil(jobs.total / jobs.page_size)) : 1;
  const hasFilters = Array.from(searchParams.keys()).some((key) => key !== "page" && key !== "page_size");

  return (
    <div className="jobs-page">
      <section className="page-intro">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" aria-hidden="true" />岗位池</div>
          <h1>先看真实岗位，再决定下一步。</h1>
          <p>岗位来自已确认的公开招聘源。搜索、筛选和收藏会与账号同步。</p>
        </div>
        <div className="intro-note" aria-label="岗位池说明">
          <Briefcase size={20} />
          <div><strong>{jobs?.pool_total ?? "..."}</strong><span>可见岗位池</span></div>
        </div>
      </section>

      <section className="jobs-toolbar" aria-label="岗位池状态">
        <div className="toolbar-copy"><span className="toolbar-label">当前视图</span><strong>{jobs ? `共 ${jobs.total} 个匹配岗位` : "正在读取岗位"}</strong></div>
        <div className="toolbar-meta">
          {filters ? `公开访问每页最多 ${filters.limits.public_page_size_max} 个岗位` : "正在读取筛选配置"}
          <span className="toolbar-divider" aria-hidden="true" />
          <span>{status === "authenticated" ? "收藏状态已同步" : "登录后可搜索、筛选和收藏"}</span>
        </div>
      </section>

      <form className="job-filters" onSubmit={applyFilters} aria-label="搜索和筛选岗位">
        <label className="search-field field-group">
          <span>搜索岗位或公司</span>
          <span className="search-input-wrap">
            <MagnifyingGlass size={18} aria-hidden="true" />
            <input value={draft.q} onChange={(event) => updateDraft("q", event.target.value)} placeholder="例如：Python、数据平台" />
          </span>
        </label>
        <div className="filter-grid">
          <MultiSelectField id="job-filter-city" label="城市" value={draft.city} options={filters?.cities ?? []} onChange={(value) => updateDraft("city", value)} />
          <MultiSelectField id="job-filter-recruitment-type" label="招聘类型" value={draft.recruitmentType} options={filters?.recruitment_types ?? []} onChange={(value) => updateDraft("recruitmentType", value)} />
          <MultiSelectField id="job-filter-education" label="学历" value={draft.education} options={filters?.educations ?? []} onChange={(value) => updateDraft("education", value)} />
          <MultiSelectField id="job-filter-company-nature" label="公司性质" value={draft.companyNature} options={filters?.company_natures ?? []} onChange={(value) => updateDraft("companyNature", value)} />
          <MultiSelectField id="job-filter-source" label="来源" value={draft.sourceId} options={filters?.sources.map((source) => source.id) ?? []} labels={Object.fromEntries(filters?.sources.map((source) => [source.id, source.name]) ?? [])} onChange={(value) => updateDraft("sourceId", value)} />
          <MultiSelectField id="job-filter-graduation-year" label="届次" value={draft.graduationYear} options={(filters?.graduation_years ?? []).map(String)} onChange={(value) => updateDraft("graduationYear", value)} />
          <label className="field-group"><span>最低薪资</span><input inputMode="numeric" value={draft.salaryMin} onChange={(event) => updateDraft("salaryMin", event.target.value)} placeholder="元/月" /></label>
          <label className="field-group"><span>最高薪资</span><input inputMode="numeric" value={draft.salaryMax} onChange={(event) => updateDraft("salaryMax", event.target.value)} placeholder="元/月" /></label>
        </div>
        <div className="filter-actions">
          <label className="page-size-field"><span>每页</span><select value={draft.pageSize} onChange={(event) => updateDraft("pageSize", event.target.value)}><option value="6">6</option><option value="12">12</option><option value="30">30</option>{status === "authenticated" && <><option value="50">50</option><option value="100">100</option></>}</select></label>
          {hasFilters && <button className="button button-secondary" type="button" onClick={clearFilters}><X size={16} />清除筛选</button>}
          <button className="button button-primary" type="submit"><Funnel size={17} />应用筛选</button>
        </div>
      </form>

      {filterErrorMessage && <p className="form-error inline-page-error" role="alert">{filterErrorMessage}</p>}

      {loadState === "loading" && <JobGridSkeleton />}
      {loadState === "error" && <StatePanel title="岗位暂时没有准备好" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => setRetryKey((current) => current + 1)} />}
      {loadState === "empty" && <StatePanel title="当前没有匹配岗位" description="没有找到符合当前条件的岗位，可以放宽筛选条件后再试。" actionLabel="清除筛选" onAction={clearFilters} />}

      {loadState === "ready" && jobs && (
        <>
          <section className="job-grid" aria-label="岗位列表">
            {jobs.items.map((job) => <JobCard key={job.id} job={job} isSaving={savingJobId === job.id} onToggleSaved={() => void toggleSaved(job)} />)}
          </section>
          <Pagination page={jobs.page} totalPages={totalPages} onChange={goToPage} />
        </>
      )}
    </div>
  );
}

function MultiSelectField({ id, label, value, options, labels, onChange }: { id: string; label: string; value: string[]; options: string[]; labels?: Record<string, string>; onChange: (value: string[]) => void }) {
  return <div className="field-group multi-select-field"><label htmlFor={id}>{label}</label><select id={id} multiple size={Math.min(4, Math.max(2, options.length))} value={value} onChange={(event) => onChange(Array.from(event.target.selectedOptions, (option) => option.value))} aria-describedby={`${id}-hint`}>{options.map((option) => <option key={option} value={option}>{labels?.[option] ?? option}</option>)}</select><small id={`${id}-hint`}>可多选{value.length > 0 ? `，已选 ${value.length} 项` : "，未选择即不限"}</small></div>;
}

function JobCard({ job, isSaving, onToggleSaved }: { job: JobListItem; isSaving: boolean; onToggleSaved: () => void }) {
  return (
    <article className="job-card">
      <div className="job-card-topline">
        <span className="source-chip">{job.source.name}</span>
        <button className="save-button" type="button" aria-label={job.is_saved ? `取消收藏 ${job.title}` : `收藏 ${job.title}`} aria-pressed={job.is_saved === true} disabled={isSaving} onClick={onToggleSaved}>
          <BookmarkSimple size={19} weight={job.is_saved ? "fill" : "regular"} />
        </button>
      </div>
      <Link className="job-card-link" to={`/jobs/${job.id}`}>
        <div className="job-card-heading"><h2>{job.title}</h2></div>
        <p className="job-company">{job.company_name}</p>
        <div className="job-tags">
          {job.locations.length > 0 && <span>{job.locations.join("、")}</span>}
          {job.recruitment_type && <span>{job.recruitment_type}</span>}
          {job.education_requirement && <span>{job.education_requirement}</span>}
        </div>
        <p className="job-preview">{job.description_preview ?? "岗位描述待确认。"}</p>
        <div className="job-card-footer"><span>{formatSalaryRange(job.salary_min, job.salary_max, job.salary_months)}</span><span className="job-date">{formatDate(job.last_confirmed_at)} 更新</span></div>
      </Link>
    </article>
  );
}

function Pagination({ page, totalPages, onChange }: { page: number; totalPages: number; onChange: (page: number) => void }) {
  if (totalPages <= 1) return null;
  return <nav className="pagination" aria-label="岗位分页"><button className="icon-button" type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}><CaretLeft size={18} /></button><span>第 {page} / {totalPages} 页</span><button className="icon-button" type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(page + 1)}><CaretRight size={18} /></button></nav>;
}

function JobGridSkeleton() {
  return <section className="job-grid" aria-label="正在加载岗位" aria-busy="true">{Array.from({ length: 6 }, (_, index) => <div className="job-card skeleton-card" key={index}><span className="skeleton-line skeleton-short" /><span className="skeleton-line skeleton-title" /><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-footer" /></div>)}</section>;
}

function StatePanel({ title, description, actionLabel, onAction }: { title: string; description: string; actionLabel: string; onAction: () => void }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p><button className="button button-secondary" type="button" onClick={onAction}>{actionLabel}</button></section>;
}
