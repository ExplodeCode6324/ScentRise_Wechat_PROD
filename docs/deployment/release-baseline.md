# 后端发布基线、记录及回退入口

Issue：https://github.com/ExplodeCode6324/ScentRise_Wechat_PROD/issues/4

状态：候选实现待审；master、生产发布来源、分支保护及线上配置均未切换。
Master 于 2026-10-28 批准实施计划并要求验证、CI 后提交 PR；未授权合并或生产发布。

## 代码基线与审阅方式

| 来源 | 完整 SHA / 去向 |
|---|---|
| 旧默认 master | `bffe5a0516351dbb6e7c14e8511cf42a41558778` |
| 保留的业务提交 B | `6609c38561661bf8607c4461c346229e4007022e` |
| 保留的治理提交 G | `e6c6727dbac5b92458e912330f58d993ac6b41e5`，后端 PR #2 |
| 本 Issue 候选 | `codex/issue-4-release-baseline-20261028` → master，含 B/G 的原始祖先关系 |
| 后续开发起点 | 本 PR 获准合并后的实际 master 合并提交 M4；未合并前不存在 M4 |

B 相对旧 master 只有一个提交，但涉及 35 文件（+3309/-1728）：运行方式变为
Gunicorn/非 root/8080、环境配置及认证硬化、导入预检、管理 SPA、模型与迁移、
依赖版本等。不是单纯的部署文档改动，必须审阅既有业务差异。

```bash
# 审阅原业务差异
git diff bffe5a0516351dbb6e7c14e8511cf42a41558778 6609c38561661bf8607c4461c346229e4007022e
# 审阅本任务增量：治理文件、计划、文档、发布记录校验和 CI
git diff 6609c38561661bf8607c4461c346229e4007022e codex/issue-4-release-baseline-20261028
```

候选分支组合 B/G 供完整 CI 验证，仅发生在独立候选分支，未把任何 PR 合入
master。合并顺序仍为后端 PR #2 → 本 Issue PR；每个具体 PR 均需 Master 明确授权。
#2 实际合入 master 后，将新的 master 合入候选分支并重跑当前 head CI，再提请授权。
本 PR 应使用保留 B/G 祖先关系的 merge commit，不 squash/rebase 改写来源。

前端独立仓库的 PR #2 仍未合并；它不是后端收敛的硬前置。前端任务不得从只有 README
的旧 main 覆盖已导入源码。后续后端实现等待记录 M4，提前调查及计划可以进行。

## 线上只读核验与缺口

2026-10-28 只读查看了现有微信云托管的线上版本与发布详情页面。页面显示：
线上版本正常、1 个实例、端口 8080；发布日志检出
`codex/harden-import-security-20260822`，使用 Python 3.11 Alpine、非 root、
Gunicorn；日志包含镜像推送成功及 sha256 digest。

这些信息属于历史发布日志和当前页面显示，不能证明源码完整 SHA，也不证明配置、
数据库和运行时镜像之间的全部对应关系。生产服务名、环境标识、镜像仓库地址及日志
原文保存在本地受控证据中，不提交公开仓库。

待核实：线上完整 source SHA、运行时镜像与构建 digest 的一致性、当前流水线跟踪
设置、配置修订与备份引用、数据库实际 revision/schema、历史镜像兼容性和恢复演练。
没有访问证据的字段使用 unknown；不得猜测或用 CI 重建镜像替代归档生产镜像。
本次没有运行生产 SQL、迁移或数据写入。

## 发布记录及校验

[记录模板](release-record.template.json) 只含字段及 unknown，不含真实环境、
凭据或生产数据。复制到受控的发布证据目录后逐项补齐，公开 PR 仅保存脱敏说明。

```bash
# 草稿结构检查，不代表具备发布条件
python tools/check_release_record.py docs/deployment/release-record.template.json
# 实际记录完成后检查；草稿、未授权、未知来源、失败 CI、未验证回退均应失败
python tools/check_release_record.py /controlled/path/release-record.json --require-ready
```

状态为 draft / verified / deployed / rolled_back。verified 及以后要求：
完整 source/rollback SHA、基础与最终镜像 digest、CI 链接及成功结果、配置与迁移映射、
兼容结论、备份恢复证据和三类授权引用全部齐全，blockers 为空。
校验只验证结构和所填结论，不能验证证据真实性，也不能代替人工审核或授权。
变更状态必须保留前一份记录及审批证据，部署与回退结果分别保存。
操作人不能仅凭把字段填成 success/compatible 来获得生产操作权限。

镜像必须使用 `repository@sha256:<64位十六进制>`，不使用可变 tag 定位回退。
配置只记录键名和受控版本引用；不得填 secret 的真实值，也不公开弱密码的哈希。
同一个代码 SHA 可能因基础镜像或间接依赖变化生成不同镜像，应分别保存构建证据。
现有 requirements.txt 固定直接版本，尚不是完整传递依赖锁；此限制继续记录。

## 验证和 CI

Backend Baseline CI 对 master 的 PR 和本候选分支运行，无生产凭据、无部署动作：

- Regression and release record：检查 B/G 祖先关系及业务文件未改动，治理文档、
  发布模板、拒绝不完整记录的反例、独立校验测试、原有 14 项 pytest、Ruff。
- Container and synthetic MySQL compatibility：临时 MySQL 8.0 上构造空库、合成旧结构、
  重名分类三种场景；执行现有迁移、验证版本/字段/唯一性和重名阻断。
  构建候选镜像和 B 的源码重建镜像，分别连接迁移后的同一临时库，检查 Gunicorn、
  UID 10001、8080、健康探针、公开只读 API 和后管 HTML/JS。运行证据上传 artifact。
- Dependency security scan (release gate)：扫描现有固定依赖并上传 JSON；存在漏洞时
  检查保持失败，不允许自动忽略或 continue-on-error。

本地已验证原有 pytest 14 passed、新校验 unittest 7 passed、Ruff。
本机为 Python 3.12；Linux Python 3.11、容器和 MySQL 使用隔离 GitHub CI 验证。
本地扫描现有依赖在 3 个包中检出 54 条公告（2026-10-28），扫描退出码 1；
升级归 Issue #10，此 PR 不改变运行依赖。以当前 CI artifact 为准，不将其描述为扫描通过。

MySQL 场景仅是**合成 schema 兼容测试**：不是生产快照、完整迁移重放测试或恢复演练。
现有迁移引用当前 metadata，完整可重放性修复归 Issue #11。
B 的重建镜像只证明该源码在测试库上的读取兼容性；不是线上旧镜像回退验收。
CI 全部功能检查通过也不能填补线上证据和安全扫描缺口。

本 PR 可供审阅，但有任何失败检查或证据缺口时保持待审/阻断发布，不提前关闭 Issue #4。

## 授权后的收敛与生产切换

1. 刷新 PR/refs 状态；Master 先对治理 PR #2、再对本 PR 分别授权合并。
2. 记录 master 的实际完整 M4 SHA；确认包含 B/G；后续修复从 M4 或其后继建立分支。
3. 建议 master 要求 PR 和实际有效的 required checks，禁止强推/删除，保留 Master
   的具体 PR 授权流程。人数按实际协作者配置，不设无法满足的多人审阅。
   本次未修改任何保护设置。
4. 安全扫描、线上来源、配置/schema、候选与归档回退镜像、备份恢复证据全部完成，
   且 Master 另行明确授权生产切换后，才处理云托管跟踪分支/发布。
5. 不直接推送旧云托管发布分支。确认切换跟踪分支是否立即触发发布；若会触发，
   将其视为一次完整生产发布，不能称为无影响的设置更新。
6. 按环境既有流程发布精确镜像并记录版本/流量和验证结果。源码合并、配置切换及
   生产发布分别登记，禁止混称“发布完成”。

## 风险与回退

- 未发布：关闭本 PR 可终止本轮变更，不影响线上。已合并但未发布时走新的修正/revert
  PR 并取得授权，禁止强制回退 master 或恢复旧业务代码后继续开发。
- 发布后：使用已归档且验证兼容的上一镜像 digest 恢复版本/流量，同时恢复匹配的
  端口、探针和配置修订，记录原因与结果并复核健康、公开只读 API、后管入口。
- 不把旧 master bffe5a0 当作默认回退目标，它的依赖、端口、配置和数据访问不同。
- 迁移 20260822_01 的 downgrade 是 pass，保留新增结构。代码回退不等于 schema 回退。
  默认保留兼容扩展，不自动降迁移、不重跑 schema.sql、不 DROP、不覆盖新数据。
- 若归档镜像不兼容当前 schema，停止回退，采用预先验证的兼容镜像或修复版本。
  只有必须恢复数据库时，才另行准备停写、恢复演练和数据补偿，并获取 Master 授权。

本任务的完整范围、计划及验收见
[Issue #4 实施计划](fix_01_后端发布基线与回退流程_20261028.md)。
