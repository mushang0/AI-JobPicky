# Platform discovery catalog

Use this as a hypothesis list. Confirm the current page shell and public requests before coding because vendors change routes and field names.

## High-value families

| Family | Recognition hints | Preferred evidence |
|---|---|---|
| `alibaba-campus` | `campus-talent.alibaba.com`, campus position shell | embedded state or public list request; record batch/filter semantics |
| `baidu-campus` | `talent.baidu.com/jobs/list` | server state plus official detail template; do not rely on one filtered list |
| `tencent-campus` | `join.qq.com/post.html` | public list request and `postId` detail request; use `desc`/`request` with Qingyun `topicDetail`/`topicRequirement` fallback, skip explicit `岗位已下架` details, preserve location mapping |
| `meituan-campus` | `zhaopin.meituan.com/web/beidou`, `/web/campus` | `POST /api/official/job/getJobList` with route-specific public filters; use `jobUnionId`, `totalPage`, and public `getJobDetail` only when list JD fields are absent |
| `pdd-global-hr` | `careers.pddglobalhr.com/campus` | `POST /api/careers/api/recruit/position/list` then `POST /api/careers/api/recruit/position/detail`; direct `positionId` links stay scoped |
| `netease-campus` | `campus.163.com`, `campus.game.163.com`, `leihuo.163.com` | project query `id` selects `GET /api/campuspc/position/getJobList`; use `GET /api/campuspc/position/getJobDetails` only when list JD fields are absent |
| `netease-hr` | `hr.163.com/job-detail.html?id=...` | direct public `GET /api/hr163/position/query?id=...`; keep the source position scoped |
| `kuaishou-campus` | `campus.kuaishou.cn/recruit/campus` | `POST /recruit/campus/e/api/v1/open/positions/simple`; `GET /recruit/campus/e/api/v1/open/positions/find?id=...`; require the reported total to be collected |
| `oppo-careers` | `careers.oppo.com/university/oppo/campus/post` | `POST /openapi/position/pageNew` with `records`/`pages`/`total`; list records normally include `positionDesc` and `positionRequire`; use `GET /openapi/position/detail?id=...` only when the list record has no public JD |
| `bilibili-careers` | `jobs.bilibili.com/campus/positions` | obtain a transient public CSRF value from `GET /api/auth/v1/csrf/token`, then `POST /api/campus/position/positionList` with `total/pages`; use `GET /api/campus/position/detail/{id}` only when the list record has no public JD |
| `huawei-careers` | `career.huawei.com/reccampportal/portal5/campus-recruitment.html` | `GET /reccampportal/services/portal/portalpub/getJob/newHr/page/{size}/{page}` with `pageVO.totalRows/totalPages`; use `mainBusiness`/`jobRequire` from the list and the public `getJobDetail/newHr` route only when needed |
| `jd-campus` | `campus.jd.com` | `POST /api/wx/position/page?type=present|internship` with 0-based `pageIndex` and `body.totalNumber`; use `workContent`/`qualification`, then `POST /api/wx/position/detail/{publishId}` only when needed |
| `didi-careers` | `outreach.didichuxing.com/elite` | discover the official `app.mokahr.com/campus-recruitment/didiglobal/116021` link and reuse the verified Moka campus adapter |
| `xiaohongshu-careers` | `job.xiaohongshu.com/campus/position` | `POST /websiterecruit/position/pageQueryPosition` with `recruitType`, `themeCode`, `totalPage`; use `positionId` and public `queryPositionDetail` only when list JD fields are absent |
| `zte-careers` | `job.zte.com.cn/.../Recruitment_positions/freshstudent.html` | discover the official `app.mokahr.com/campus-recruitment/zte/46903` link and reuse the unfiltered Moka campus adapter |
| `yonyou-careers` | `career.yonyou.com/SU.../pb/school.html` | form `POST /wecruit/positionInfo/listPosition/SU...` with `dataCount/totalPage`, then public `listPositionDetail/SU...` for `workContent`/`serviceCondition` |
| `phenom-careers` | `careers.bcg.com/global/en/job/...` | public `phApp.ddo.jobDetail.data.job` embedded in the detail page; direct detail pages only until a public list contract is verified |
| `feishu-careers` | `xiaomi.jobs.f.mioffice.cn`, `jobs.ecoflow.com`, `career.papegames.com` | reuse the Feishu `position/<id>/detail` API and rendered list navigation on verified custom domains; keep the first portal path as `website-path` |
| `moka-careers` | `campus.sonoscape.com`, `campus.fingard.com`, `apply.careers.dji.com` | reuse `#init-data` for the public org/site/AES-IV bootstrap, then `POST /api/outer/ats-apply/website/jobs/v2` with bounded `limit`/`offset`; validate `jobStats.total` and use `jobDescription`; direct or missing-JD records use public `POST /api/outer/ats-apply/website/job` |
| `10jqka-campus` | `campus.10jqka.com.cn` | `GET /api/v3/school_recruitment/apply/apply_list` then `GET /api/v3/school_recruitment/apply/apply_detail`; omit empty array filters |
| `hcm-cloud` | HCM shell, `/recruit#/portal_job_list` | discover transfer strategy, public list endpoint, pagination, and detail URL template |
| `redsea-platform` | `/RedseaPlatform/` | discover channel configuration, list endpoint, detail endpoint, and recruitment type |

## Generic ATS families

Greenhouse, Workday, SmartRecruiters, BambooHR, and vendor career-site shells should be recognized by host and page structure. Reuse an ATS adapter only when the public list/detail contracts are actually the same; a shared vendor brand is not proof of identical endpoints.

## Discovery sequence

1. Fetch the entry shell with a bounded response size and timeout.
2. Extract embedded JSON and script sources.
3. Inspect only the smallest relevant script or route chunk for list/detail strings.
4. Replay the public request with the same non-secret method, body, and required public headers.
5. Validate one list page and one detail record before implementing pagination.

## Stop conditions

Stop and record an unsupported boundary when the source requires login, CAPTCHA, a private cookie, a secret signing key, or browser state that cannot be reproduced deterministically. Do not bypass the control or mark the source complete.
