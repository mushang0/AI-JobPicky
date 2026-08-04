# Platform discovery catalog

Use this as a hypothesis list. Confirm the current page shell and public requests before coding because vendors change routes and field names.

## High-value families

| Family | Recognition hints | Preferred evidence |
|---|---|---|
| `alibaba-campus` | `campus-talent.alibaba.com`, campus position shell | embedded state or public list request; record batch/filter semantics |
| `baidu-campus` | `talent.baidu.com/jobs/list` | server state plus official detail template; do not rely on one filtered list |
| `tencent-campus` | `join.qq.com/post.html` | public list request and `postId` detail request; preserve location mapping |
| `pdd-global-hr` | `careers.pddglobalhr.com/campus` | `POST /api/careers/api/recruit/position/list` then `POST /api/careers/api/recruit/position/detail`; direct `positionId` links stay scoped |
| `netease-campus` | `campus.163.com`, `campus.game.163.com`, `leihuo.163.com` | project query `id` selects `GET /api/campuspc/position/getJobList`; use `GET /api/campuspc/position/getJobDetails` only when list JD fields are absent |
| `netease-hr` | `hr.163.com/job-detail.html?id=...` | direct public `GET /api/hr163/position/query?id=...`; keep the source position scoped |
| `kuaishou-campus` | `campus.kuaishou.cn/recruit/campus` | `POST /recruit/campus/e/api/v1/open/positions/simple`; `GET /recruit/campus/e/api/v1/open/positions/find?id=...`; require the reported total to be collected |
| `phenom-careers` | `careers.bcg.com/global/en/job/...` | public `phApp.ddo.jobDetail.data.job` embedded in the detail page; direct detail pages only until a public list contract is verified |
| `feishu-careers` | `xiaomi.jobs.f.mioffice.cn`, `jobs.ecoflow.com`, `career.papegames.com` | reuse the Feishu `position/<id>/detail` API and rendered list navigation on verified custom domains; keep the first portal path as `website-path` |
| `moka-careers` | `campus.sonoscape.com`, `campus.fingard.com` | reuse the Moka server-rendered `#init-data` contract; public list facts are valid, but encrypted detail JD remains unavailable |
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
