import { useEffect, useMemo, useRef, useState } from "react";
import { BookmarkSimple, Briefcase, CaretDown, CaretLeft, CaretRight, Check, Funnel, MagnifyingGlass, WarningCircle, X } from "@phosphor-icons/react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../adapters/web/AuthProvider";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { jobsApi } from "../../shared/api/jobs";
import type { JobFilterOptions, JobListItem, JobQuery, JobsPageResponse } from "../../shared/api/types";
import { formatDate, formatSalaryRange } from "../../shared/formatting";
import { validateJobQuery } from "../../shared/validation/jobs";
import { CityPicker } from "../../components/CityPicker";

type LoadState = "loading" | "ready" | "empty" | "error";

interface FilterDraft {
  q: string;
  city: string[];
  companyNature: string[];
  recruitmentType: string[];
  education: string[];
  graduationYear: string[];
  salaryMin: string;
  salaryMax: string;
  publishedDate: string;
}

const JOBS_PAGE_SIZE = 12;
const FILTER_PARAM_KEYS = [
  "city",
  "company_nature",
  "recruitment_type",
  "education",
  "graduation_year",
  "salary_min",
  "salary_max",
  "published_within_days",
  "published_at_unknown",
] as const;

function hasFilterParams(params: URLSearchParams): boolean {
  return FILTER_PARAM_KEYS.some((key) => params.getAll(key).some(Boolean));
}

function readDraft(params: URLSearchParams): FilterDraft {
  return {
    q: params.get("q") ?? "",
    city: params.getAll("city"),
    companyNature: params.getAll("company_nature"),
    recruitmentType: params.getAll("recruitment_type"),
    education: params.getAll("education"),
    graduationYear: params.getAll("graduation_year"),
    salaryMin: params.get("salary_min") ?? "",
    salaryMax: params.get("salary_max") ?? "",
    publishedDate: params.get("published_at_unknown") === "true" ? "unknown" : params.get("published_within_days") ?? "",
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
  const publishedDate = params.get("published_within_days");
  const publishedAtUnknown = params.get("published_at_unknown") === "true";

  return {
    page: numberOrUndefined(params.get("page")) ?? 1,
    page_size: JOBS_PAGE_SIZE,
    q: params.get("q") ?? undefined,
    city: many("city"),
    company_nature: many("company_nature"),
    recruitment_type: many("recruitment_type"),
    education: many("education"),
    graduation_year: graduationYears.length > 0 ? graduationYears : undefined,
    salary_min: numberOrUndefined(params.get("salary_min")),
    salary_max: numberOrUndefined(params.get("salary_max")),
    published_within_days: publishedAtUnknown ? undefined : numberOrUndefined(publishedDate),
    published_at_unknown: publishedAtUnknown || undefined,
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
  const [isFilterPanelOpen, setIsFilterPanelOpen] = useState(() => hasFilterParams(searchParams));

  useEffect(() => {
    const nextDraft = readDraft(searchParams);
    setDraft(nextDraft);
  }, [queryString]);

  useEffect(() => {
    let active = true;
    jobsApi.filterOptions().then((response) => {
      if (active) {
        setFilters(response);
        setFilterErrorMessage(null);
      }
    }).catch(() => {
      if (active) setFilterErrorMessage("筛选选项暂时无法加载，你仍可以先搜索岗位。");
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
    if (draft.publishedDate === "unknown") {
      next.set("published_at_unknown", "true");
    } else if (draft.publishedDate) {
      next.set("published_within_days", draft.publishedDate);
    }
    next.set("page", "1");
    setSearchParams(next);
  }

  function clearFilters() {
    setSearchParams({ page: "1" });
    setIsFilterPanelOpen(false);
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
  const hasFilters = Array.from(searchParams.keys()).some((key) => !["page", "page_size", "source_id"].includes(key));
  const activeFilterCount = [
    draft.city.length,
    draft.companyNature.length,
    draft.recruitmentType.length,
    draft.education.length,
    draft.graduationYear.length,
    draft.publishedDate ? 1 : 0,
    draft.salaryMin ? 1 : 0,
    draft.salaryMax ? 1 : 0,
  ].reduce((total, count) => total + count, 0);

  return (
    <div className="jobs-page">
      <section className="page-intro">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" aria-hidden="true" />岗位池</div>
          <h1>先看真实岗位，再决定下一步。</h1>
          <p>岗位来自已整理的招聘渠道。搜索、筛选和收藏会与账号同步。</p>
        </div>
        <div className="intro-note" aria-label="岗位池说明">
          <Briefcase size={20} />
          <div><strong>{jobs?.pool_total ?? "..."}</strong><span>可见岗位池</span></div>
        </div>
      </section>

      <section className="jobs-toolbar" aria-label="岗位池状态">
        <div className="toolbar-copy"><span className="toolbar-label">当前视图</span><strong>{jobs ? `共 ${jobs.total} 个匹配岗位` : "正在读取岗位"}</strong></div>
        <div className="toolbar-meta">
          <span>岗位池持续更新</span>
          <span className="toolbar-divider" aria-hidden="true" />
          <span>{status === "authenticated" ? "收藏状态已同步" : "登录后可搜索、筛选和收藏"}</span>
        </div>
      </section>

      <form className="job-filters" onSubmit={applyFilters} aria-label="搜索和筛选岗位">
        <div className="job-search-row">
          <label className="search-field field-group">
            <span>搜索岗位或公司</span>
            <span className="search-input-wrap">
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input value={draft.q} onChange={(event) => updateDraft("q", event.target.value)} placeholder="搜索岗位、公司或关键词，例如：Python、数据平台" />
            </span>
          </label>
          <div className="job-search-actions">
            {hasFilters && <button className="button button-secondary" type="button" onClick={clearFilters}><X size={16} />清除筛选</button>}
            <button
              className="button button-secondary mobile-filter-toggle"
              type="button"
              aria-expanded={isFilterPanelOpen}
              aria-controls="job-filter-panel"
              onClick={() => setIsFilterPanelOpen((current) => !current)}
            >
              <Funnel size={17} />筛选{activeFilterCount > 0 && <span className="filter-count">{activeFilterCount}</span>}
            </button>
            <button className="button button-primary desktop-filter-submit" type="submit"><Funnel size={17} />应用筛选</button>
          </div>
        </div>
        <div id="job-filter-panel" className={`filter-grid${isFilterPanelOpen ? " is-open" : ""}`}>
          <div className="field-group jobs-city-filter"><span>城市</span><CityPicker label="城市" values={draft.city} onChange={(value) => updateDraft("city", value)} /></div>
          <FilterDropdown id="job-filter-recruitment-type" label="招聘类型" value={draft.recruitmentType} options={filters?.recruitment_types ?? []} disabled={!filters} onChange={(value) => updateDraft("recruitmentType", value)} />
          <FilterDropdown id="job-filter-education" label="学历" value={draft.education} options={filters?.educations ?? []} disabled={!filters} onChange={(value) => updateDraft("education", value)} />
          <FilterDropdown id="job-filter-company-nature" label="公司性质" value={draft.companyNature} options={filters?.company_natures ?? []} disabled={!filters} onChange={(value) => updateDraft("companyNature", value)} />
          <SelectField label="发布日期" value={draft.publishedDate} options={[
            ["", "不限"],
            ["3", "最近 3 天"],
            ["7", "最近 7 天"],
            ["30", "最近 30 天"],
            ["unknown", "发布日期未注明"],
          ]} onChange={(value) => updateDraft("publishedDate", value)} />
          <FilterDropdown id="job-filter-graduation-year" label="届次" value={draft.graduationYear} options={(filters?.graduation_years ?? []).map(String)} disabled={!filters} onChange={(value) => updateDraft("graduationYear", value)} />
          <label className="field-group"><span>最低薪资</span><input type="number" min="0" inputMode="numeric" value={draft.salaryMin} onChange={(event) => updateDraft("salaryMin", event.target.value)} placeholder="元/月" /></label>
          <label className="field-group"><span>最高薪资</span><input type="number" min="0" inputMode="numeric" value={draft.salaryMax} onChange={(event) => updateDraft("salaryMax", event.target.value)} placeholder="元/月" /></label>
        </div>
        <div className="filter-panel-actions">
          <button className="button button-secondary" type="button" onClick={clearFilters} disabled={!hasFilters}>清除筛选</button>
          <button className="button button-primary" type="submit"><Funnel size={17} />完成筛选</button>
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

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: ReadonlyArray<readonly [string, string]>; onChange: (value: string) => void }) {
  return <label className="field-group"><span>{label}</span><span className="select-control-wrap"><select value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([option, optionLabel]) => <option key={option} value={option}>{optionLabel}</option>)}</select><CaretDown className="select-control-arrow" size={16} aria-hidden="true" /></span></label>;
}

function FilterDropdown({ id, label, value, options, labels, disabled = false, onChange }: { id: string; label: string; value: string[]; options: string[]; labels?: Record<string, string>; disabled?: boolean; onChange: (value: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  const selectedLabels = value.map((option) => labels?.[option] ?? option);
  const summary = disabled ? "正在加载…" : selectedLabels.length === 0 ? "不限" : selectedLabels.length <= 2 ? selectedLabels.join("、") : `已选 ${selectedLabels.length} 项`;

  function toggleOption(option: string) {
    onChange(value.includes(option) ? value.filter((item) => item !== option) : [...value, option]);
  }

  return (
    <div className={`field-group filter-dropdown${open ? " is-open" : ""}`} ref={containerRef}>
      <span id={`${id}-label`}>{label}</span>
      <button className="filter-dropdown-trigger" type="button" aria-labelledby={`${id}-label`} aria-controls={`${id}-menu`} aria-expanded={open} aria-haspopup="listbox" disabled={disabled} onClick={() => setOpen((current) => !current)}>
        <span className={`filter-dropdown-value${selectedLabels.length === 0 ? " is-placeholder" : ""}`}>{summary}</span>
        <CaretDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <div className="filter-dropdown-menu" id={`${id}-menu`} role="listbox" aria-labelledby={`${id}-label`} aria-multiselectable="true">
          <div className="filter-menu-header">
            <small>可多选，未选择即不限</small>
            <button className="filter-menu-clear" type="button" disabled={value.length === 0} onClick={() => onChange([])}>清除</button>
          </div>
          <div className="filter-menu-options">
            {options.length > 0 ? options.map((option) => {
              const selected = value.includes(option);
              return <button className={`filter-option${selected ? " is-selected" : ""}`} key={option} type="button" role="option" aria-selected={selected} onClick={() => toggleOption(option)}><span className="filter-checkbox" aria-hidden="true">{selected && <Check size={13} weight="bold" />}</span><span>{labels?.[option] ?? option}</span></button>;
            }) : <div className="filter-menu-empty">暂无可选项</div>}
          </div>
          <div className="filter-menu-footer"><button className="filter-menu-done" type="button" onClick={() => setOpen(false)}>完成</button></div>
        </div>
      )}
    </div>
  );
}

function JobCard({ job, isSaving, onToggleSaved }: { job: JobListItem; isSaving: boolean; onToggleSaved: () => void }) {
  return (
    <article className="job-card">
      <div className="job-card-topline">
        <span className="source-chip">{job.source.name}</span>
        <button className={`save-button ${job.is_saved ? "is-saved" : ""}`} type="button" aria-label={job.is_saved ? `取消收藏 ${job.title}` : `收藏 ${job.title}`} aria-pressed={job.is_saved === true} disabled={isSaving} onClick={onToggleSaved}>
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
        <div className="job-card-footer"><span>{formatSalaryRange(job.salary_min, job.salary_max, job.salary_months)}</span><span className="job-date">{job.published_at ? `发布 ${formatDate(job.published_at)}` : "发布日期未注明"}</span></div>
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
