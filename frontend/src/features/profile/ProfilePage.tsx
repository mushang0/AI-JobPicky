import { useEffect, useRef, useState } from "react";
import { Check, FloppyDisk, WarningCircle, X } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { createIdempotencyKey } from "../../shared/api/idempotency";
import { jobsApi } from "../../shared/api/jobs";
import { profileApi } from "../../shared/api/profile";
import type { JobFilterOptions, ProfileSaveRequest, ProfileView } from "../../shared/api/types";
import { formatDate } from "../../shared/formatting";
import { normalizeProfile, validateProfile } from "../../shared/validation/profile";

const emptyProfile: ProfileSaveRequest = {
  base_version: null,
  target_roles: [],
  target_locations: [],
  recruitment_types: [],
  skills: [],
  education: null,
  graduation_year: null,
  expected_salary_min: null,
  experience_summary: null,
  excluded_roles: [],
  extra_request: null,
};

function profileToForm(profile: ProfileView): ProfileSaveRequest {
  return {
    base_version: profile.version,
    target_roles: profile.target_roles,
    target_locations: profile.target_locations,
    recruitment_types: profile.recruitment_types,
    skills: profile.skills,
    education: profile.education,
    graduation_year: profile.graduation_year,
    expected_salary_min: profile.expected_salary_min,
    experience_summary: profile.experience_summary,
    excluded_roles: profile.excluded_roles,
    extra_request: profile.extra_request,
  };
}

export function ProfilePage() {
  const [form, setForm] = useState<ProfileSaveRequest>(emptyProfile);
  const [filters, setFilters] = useState<JobFilterOptions | null>(null);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const [saveKey, setSaveKey] = useState<string | null>(null);
  const saveKeyRef = useRef<string | null>(null);
  const graduationYears = filters?.graduation_years
    ? [...new Set(profile?.graduation_year && !filters.graduation_years.includes(profile.graduation_year) ? [profile.graduation_year, ...filters.graduation_years] : filters.graduation_years)]
    : [];

  useEffect(() => {
    let active = true;
    Promise.all([
      jobsApi.filterOptions(),
      profileApi.current().catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") return null;
        throw error;
      }),
    ]).then(([filterOptions, currentProfile]) => {
      if (!active) return;
      setFilters(filterOptions);
      setProfile(currentProfile);
      setForm(currentProfile ? profileToForm(currentProfile) : { ...emptyProfile });
      setLoadState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "求职画像暂时无法加载，请稍后重试。");
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isDirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  function markDirty(nextForm: ProfileSaveRequest) {
    setForm(nextForm);
    setIsDirty(true);
    setMessage(null);
    setErrorMessage(null);
    setValidationMessage(null);
    setSaveKey(null);
    saveKeyRef.current = null;
  }

  function updateField<K extends keyof ProfileSaveRequest>(field: K, value: ProfileSaveRequest[K]) {
    markDirty({ ...form, [field]: value });
  }

  function toggleListValue(field: "target_locations" | "recruitment_types", value: string) {
    const values = form[field];
    updateField(field, values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  async function reloadProfile() {
    setLoadState("loading");
    setErrorMessage(null);
    try {
      const currentProfile = await profileApi.current();
      setProfile(currentProfile);
      setForm(profileToForm(currentProfile));
      setIsDirty(false);
      setSaveKey(null);
      saveKeyRef.current = null;
      setLoadState("ready");
    } catch (error: unknown) {
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "求职画像暂时无法加载，请稍后重试。");
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeProfile(form);
    const validation = validateProfile(normalized);
    if (validation) {
      setValidationMessage(validation);
      return;
    }

    const key = saveKeyRef.current ?? createIdempotencyKey("profile");
    saveKeyRef.current = key;
    setSaveKey(key);
    setIsSaving(true);
    setValidationMessage(null);
    setMessage(null);
    setErrorMessage(null);
    try {
      const savedProfile = await profileApi.save(normalized, key);
      setProfile(savedProfile);
      setForm(profileToForm(savedProfile));
      setIsDirty(false);
      setMessage(`画像已保存，版本 ${savedProfile.version}`);
      setSaveKey(null);
      saveKeyRef.current = null;
    } catch (error: unknown) {
      if (error instanceof ApiError && error.code === "PROFILE_VERSION_CONFLICT") {
        setErrorMessage("画像已在其他页面更新，请刷新后重试。");
      } else if (error instanceof ApiError) {
        setErrorMessage(getApiErrorMessage(error.code, error.message));
      } else {
        setErrorMessage("画像保存失败，请稍后重试。");
      }
    } finally {
      setIsSaving(false);
    }
  }

  if (loadState === "loading") return <ProfileSkeleton />;
  if (loadState === "error") return <StatePanel title="求职画像暂时无法加载" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => void reloadProfile()} />;

  return (
    <div className="profile-page">
      <section className="page-intro profile-intro">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" aria-hidden="true" />我的求职画像</div>
          <h1>让推荐知道你在找什么。</h1>
          <p>这是推荐系统使用的结构化求职档案。填写后保存，推荐任务只读取已保存的版本。</p>
        </div>
        <div className="profile-version-note"><span>当前版本</span><strong>{profile?.version ?? "未保存"}</strong></div>
      </section>

      <form className="profile-form" onSubmit={handleSubmit}>
        <ProfileSection title="求职目标" description="城市和招聘类型会作为确定性筛选条件。">
          <TagInput label="目标岗位" values={form.target_roles} placeholder="输入岗位名称后按 Enter" onChange={(values) => updateField("target_roles", values)} />
          <ChoiceField label="目标城市" options={filters?.cities ?? []} values={form.target_locations} onToggle={(value) => toggleListValue("target_locations", value)} emptyText="不选择表示不限地点" />
          <ChoiceField label="招聘类型" options={filters?.recruitment_types ?? []} values={form.recruitment_types} onToggle={(value) => toggleListValue("recruitment_types", value)} emptyText="不选择表示不限类型" />
          <NumberField label="期望税前月薪下限" value={form.expected_salary_min} placeholder="元/月，可不填" onChange={(value) => updateField("expected_salary_min", value)} />
        </ProfileSection>

        <ProfileSection title="教育背景" description="学历和毕业年份用于岗位硬筛选。">
          <label className="field-group"><span>最高学历</span><select value={form.education ?? ""} onChange={(event) => updateField("education", event.target.value || null)}><option value="">不填写</option>{(filters?.educations ?? []).map((option) => <option key={option} value={option}>{option}</option>)}</select></label>
          <label className="field-group"><span>毕业年份</span><select value={form.graduation_year ?? ""} onChange={(event) => updateField("graduation_year", event.target.value ? Number(event.target.value) : null)}><option value="">不填写</option>{graduationYears.map((year) => <option key={year} value={year}>{year}</option>)}</select></label>
        </ProfileSection>

        <ProfileSection title="技能与经历" description="技能和经历会用于岗位召回与 AI 评估。">
          <TagInput label="掌握技能" values={form.skills} placeholder="例如 Python、FastAPI" onChange={(values) => updateField("skills", values)} />
          <TextAreaField label="经历与项目摘要" value={form.experience_summary ?? ""} placeholder="简要描述与你目标岗位相关的经历和项目" onChange={(value) => updateField("experience_summary", value || null)} />
        </ProfileSection>

        <ProfileSection title="排除与补充" description="其他长期要求只作为推荐评估参考，不会自动发起推荐。">
          <TagInput label="明确排除的岗位" values={form.excluded_roles} placeholder="例如 客服、销售" onChange={(values) => updateField("excluded_roles", values)} />
          <TextAreaField label="其他长期要求" value={form.extra_request ?? ""} placeholder="例如 不接受长期出差" onChange={(value) => updateField("extra_request", value || null)} />
        </ProfileSection>

        {profile?.warnings.map((warning) => <p className="profile-warning" key={warning}><WarningCircle size={17} />{warning}</p>)}
        {validationMessage && <p className="form-error profile-form-error" role="alert">{validationMessage}</p>}
        {errorMessage && <p className="form-error profile-form-error" role="alert">{errorMessage}</p>}
        {message && <p className="profile-success" role="status"><Check size={17} />{message}</p>}

        <div className="profile-actions">
          <span className="profile-save-hint">{isDirty ? "有未保存修改" : profile ? `最后保存于 ${formatDate(profile.created_at)}` : "首次保存将创建版本 1"}</span>
          <div>
            {profile && !isDirty && <Link className="button button-secondary" to="/recommendation-runs/new">去获取推荐</Link>}
            <button className="button button-primary" type="submit" disabled={isSaving}><FloppyDisk size={17} />{isSaving ? "保存中" : profile ? "保存修改" : "保存画像"}</button>
          </div>
        </div>
      </form>
    </div>
  );
}

function ProfileSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <section className="profile-section"><div className="profile-section-heading"><h2>{title}</h2><p>{description}</p></div><div className="profile-section-fields">{children}</div></section>;
}

function TagInput({ label, values, placeholder, onChange }: { label: string; values: string[]; placeholder: string; onChange: (values: string[]) => void }) {
  const [draft, setDraft] = useState("");
  function addDraft() {
    const value = draft.trim();
    if (!value) return;
    if (values.includes(value)) {
      setDraft("");
      return;
    }
    onChange([...values, value]);
    setDraft("");
  }
  return <div className="field-group tag-field"><span>{label}</span><div className="tag-input-wrap">{values.map((value) => <span className="profile-tag" key={value}>{value}<button type="button" aria-label={`移除${value}`} onClick={() => onChange(values.filter((item) => item !== value))}><X size={13} /></button></span>)}<input aria-label={label} value={draft} placeholder={values.length ? "继续添加" : placeholder} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addDraft(); } }} onBlur={addDraft} /></div></div>;
}

function ChoiceField({ label, options, values, onToggle, emptyText }: { label: string; options: string[]; values: string[]; onToggle: (value: string) => void; emptyText: string }) {
  return <div className="field-group choice-field"><span>{label}</span><div className="choice-options">{options.map((option) => <button className={`choice-option ${values.includes(option) ? "choice-option-selected" : ""}`} key={option} type="button" aria-pressed={values.includes(option)} onClick={() => onToggle(option)}>{values.includes(option) && <Check size={14} />}{option}</button>)}</div><small>{emptyText}</small></div>;
}

function NumberField({ label, value, placeholder, onChange }: { label: string; value: number | null; placeholder: string; onChange: (value: number | null) => void }) {
  return <label className="field-group"><span>{label}</span><input type="number" min="0" max="1000000" value={value ?? ""} placeholder={placeholder} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} /></label>;
}

function TextAreaField({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return <label className="field-group"><span>{label}</span><textarea value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function ProfileSkeleton() {
  return <section className="profile-skeleton" aria-busy="true" aria-label="正在加载求职画像"><span className="skeleton-line skeleton-short" /><span className="skeleton-line detail-skeleton-title" /><div className="profile-skeleton-block"><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div><div className="profile-skeleton-block"><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div></section>;
}

function StatePanel({ title, description, actionLabel, onAction }: { title: string; description: string; actionLabel: string; onAction: () => void }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p><button className="button button-secondary" type="button" onClick={onAction}>{actionLabel}</button></section>;
}
