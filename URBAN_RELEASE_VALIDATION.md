# STREETWISE · NYC：城市数据扩容阶段验收

记录时间：2026-10-24T21:40:00.842919+00:00。真实 API/浏览器验收版本：`11e6185e1c5f9e37e537a366316faee153520b11`。后续纯移动控件/证据标记补丁的部署结果以 PR #23 的验收更新为准。

本阶段新增 11 个可追溯来源、1,771,190 条保留/聚合记录；完整登记表 125 个数据集。它们是来源记录和专题数据，不是去重后的商家总数。保留原有 12 维定义、全部 10,533 条街段的几何/原始指标/数值评分及 Manhattan OSM 路网。

| 测试 | 状态 | 实际证据与限制 |
|---|---|---|
| 1 Crime high | PASS | 真实 AI → 5 条真实候选；推荐 3.712 km，100 m 内 3611 条投诉，972.765 条/路线 km。 |
| 2 Crime low | PASS | 同起终点推荐 3.561 km，2208 条投诉，620.051 条/km；几何与高密度路线不同。 |
| 3 Architecture | PASS | Architecture 高/低偏好评分 84/74；独立核查 100 m 内指定地标地块 43/30（地块数，不冒充不同建筑或风格）。 |
| 4 Nature | PASS | Nature 高/低评分 33/15；真实库存点 30 m 内 370/148，98.562/37.247 点/km；包括源条件标记，不能解释为实测遮荫。 |
| 5 Bagel + Cappuccino | PASS | 真实 AI、两次推荐及行程均 HTTP 200；Zucker’s 一处真实 waypoint 同时保留两项菜单证据。1.199 km / 15 分钟步行，停留时间是估计。 |
| 6 Architecture + Nature + Coffee | PASS | 真实浏览器请求保留 Architecture/Nature 权重及必需 coffee；官方 COFFEE 菜单证据通过，真实 OSM 行程成功。 |
| 7 Waterfront reversal | PASS | 同一会话从偏好河边改为避开河边；接近水体的采样长度比例 98.38% → 6.01%，路径改变且未添加未请求景点。 |
| 8 Five-borough routing | NOT IMPLEMENTED | 五区树木查询通过；MTA 三类 × 五区共 15 项实际查询通过。Manhattan 路由 200；Brooklyn/Queens/Bronx 422，Staten Island 400，均说明图覆盖限制。 |
| 9 Production concurrency | BLOCKED | 单客户端整条链路未触发 OOM，当前 cgroup OOM 计数为 0；RSS 仍接近上限，多用户并发待下一任务先加资源约束再验证。 |
| 10 Data quality | PASS | 固定随机样本 12 条 NYPD 与 8 条树木记录，与官方实时接口字段一致；坐标/时间/唯一 ID/重复/缺失率另有完整快照审计。不是逐条实地测绘。 |

## 数据与执行路径

- [新来源清单](URBAN_DATA_INVENTORY.csv)、[完整既有清单](DATA_AUDIT_REPORT.md)、[扩容方法与缺口](URBAN_DATA_EXPANSION_REPORT.md)。
- NYPD 保留 844,984 个唯一投诉 ID，时间 2025-01-01 至 2026-07-01（不含结束日）；默认最近可用 365 天。4 条报告时间早于发生时间的记录隔离；UNKNOWN 行政区不猜测补齐。
- 897,619 条 Forestry Full-structure 点为可查询库存，包含 Dead/Unknown；不把 Full 写作 Living。新树木查询没有偷偷改写原有 Nature 数值。
- 原始点 → 日期/类型分区及空间索引 → 连续网格/日期读取 → 实际路线 100 m 去重投诉统计 → 单独偏好匹配与排序。网格图层显示完整聚合格，不能与路线缓冲区计数混为一谈。
- 原始水体几何 → ≤25 m 采样 → 100 m 水体邻近比例 → 真实边成本和排序。包括湖泊/海岸，不代表可见水景、入口开放或实时洪水情况。
- MTA 496 站、2,120 出入口；23,218 条线路—站点关系按官方站点 ID 与完全相同坐标归并成 13,735 站，并保留线路/有效期。它们是可查询地图背景，既有 Transit 数值没有变成实时 GTFS。
- 建筑 Footprints/PLUTO、施工许可、座椅等明确区分背景数据与实际评分来源；未假称所有下载数据均用于优化。施工日期区间不证明人行道全时段封闭。

## 实际修复

1. 统一结构化契约，crime/waterfront 与 12 维分离；权重/方向成对验证，未知字段和非法数值拒绝。真实 OpenAI 仅理解需求，路网和城市数据计算路径。
2. 修复随机主键回表造成的密度查询延迟；按网格/日期聚簇读取相同原始点，保留精确 100 m 标准。索引与默认场在接流量前准备，启动准备时间没有被隐瞒成零成本。
3. 请求结束仅保留 4 MiB/200 条以内的导航几何，不保留完整评分路线对象；客户端已有恢复快照仍可使用。
4. 删除会被模型复制的实时对话示例，拒绝无用户依据的酒店和景点绑定；保留实际要求的 POI、菜单品项和多轮偏好。
5. 已知真实菜单地点先进入检索，再进行距离候选截断；过期记录仅作为待核验线索，不算满足要求。新鲜且可行的证据优先复用，菜单缓存最多 256 项。
6. 控件和地图设计保留；修正手机侧栏遮住自身切换按钮的层级，水体独立目标和投诉过滤范围标记也保持可解释。移动补丁须另见实际部署验收。

## 验证层级

- 本地：231 项 Python、9 个 JavaScript/DOM 脚本通过。Mock API 错误测试与真实索引/几何测试分开记录；没有删除或跳过断言。
- 正式站：真实 gpt-4o-mini 调用、菜单来源、路由/行程和桌面 WebGL 地图通过；13 个 Explore 视图与 Inspector 均实际切换。偏好测试新增“不得添加景点”及新 route ID 断言，防止旧结果误判成功。
- 真实手机、连续 GPS 轨迹和实地走完路线：BLOCKED。云端浏览器/触控视口不能冒充设备现场验收。
- Render 管理日志不可访问。早期网关错误和进程缓存重置有记录，但未凭猜测确认 OOM 根因；当前可读 RSS、uptime 和 cgroup 计数。

## 内存与延迟

- 最新本阶段 API 序列后 RSS/high-water：477.0 MiB；实例 cgroup 上限 512 MiB，观察窗口 OOM/kill 均为 0。文件页缓存也计入 cgroup，不能把 RSS 当作全部内存占用。
- 本阶段完整食品浏览器流程 13.22 秒；组合偏好流程 6.50 秒。它们包括 AI、检索和路径计算，不是单次菜单抓取时长。
- 同一台本地机器，聚簇前/后热犯罪查询约 1.10/0.28 秒；四并发最大约 12.34/1.24 秒。该结果不能替代 Render 并发验收。准备移到启动期后，首个 API 延迟与启动准备时间分别记录。
- 早期生产 90 秒超时、冷请求 36.6 秒，以及带入多余景点的浏览器结果均保留为失败观察；没有只保留成功截图。

## 尚未完成

优先级最高的是 512 MiB 下的并发资源余量、外区 DOHMH 的内存成本和长期回归防线，按后续任务继续处理。全五区步行图、实测遮荫、实时轨道交通、电梯状态、可靠轮椅连通性、商业评分/房间库存/精确预算仍未被假称完成。官方菜单并非实时库存；OSM 营业时间也不是实时开门观测。

复现明细：[生产证据 JSON](data/urban/research/production-acceptance.json)、[数据源抽样](data/urban/research/live-source-sample.json)、[查询计划](data/urban/research/crime-query-plans.json)、[本地性能范围](data/urban/research/local-performance.json)。PR：[#19](https://github.com/ElianMu/streetwise/pull/19)、[#20](https://github.com/ElianMu/streetwise/pull/20)、[#21](https://github.com/ElianMu/streetwise/pull/21)、[#22](https://github.com/ElianMu/streetwise/pull/22)、[#23](https://github.com/ElianMu/streetwise/pull/23)。
