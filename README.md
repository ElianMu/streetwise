# STREETWISE · NYC — Pedestrian Routing Engine

本版本在原有界面上加入真实的步行路线引擎：路线在 OpenStreetMap 步行路网上计算，12 个体验维度评分与 Explore Urban Data 共用同一套定义和版本。架构见 `ARCHITECTURE.md`，接口和数据契约见 `API.md`。

Routes are computed by `routing/engine.py` on the Manhattan OSM pedestrian graph and scored with the same 12 experience scores Explore shows, transferred to OSM edges through a LION–OSM match table. Scores are relative ranks within Manhattan, not calibrated measurements.

## Run / 运行

1. 解压，进入 `STREETWISE_NYC_v04` 文件夹。
2. Terminal 运行 `python3 server.py`；Mac 也可运行 `bash START_HERE_MAC.command`。
3. 打开 **http://127.0.0.1:8080**。保留终端窗口。
4. 真正的 LLM 自然语言解析需服务端配置 `OPENAI_API_KEY`，可选 `OPENAI_MODEL`。不要把 key 放进 JS。未配置时使用明确标注的有限 Local Preview。

No Python packages are required to run the server; rebuilding the OSM graph needs OSMnx (`scripts/build_pedestrian_network.py`). The built routing data ships in `data/pedestrian/`. An internet connection is required for MapLibre/CARTO assets, Open-Meteo and OSM POIs. Public APIs can rate-limit or fail; no route is fabricated on failure.

`STREETWISE_single_file_demo.html` includes the real pilot snapshot and current application code. Opening it directly supports the pilot interface but does not provide the LLM or POI server endpoints; use `server.py` for the complete supported setup. It is not a fully offline map.

## Try the full flow / 完整交互检查

1. 顶部切换 **Navigate / Explore Urban Data**。地图只有一个 MapLibre 实例。
2. 点击 **Explore Urban Data**：13 张全曼哈顿街段地图（Overall Experience + 12 个维度），约 10,500 条街段，蓝 = 低、黄 = 高、灰 = N/A。整岛缩放下即可悬停（显示街名与当前评分）和点击；点击会高亮街段并打开 **Street Segment Inspector**：显示 Segment ID（LION physicalid，重建后保持稳定）、街名、长度、当前维度评分及其全部子指标（原始值、单位、计算方法、数据来源）；Overall 视图显示全部 12 个维度评分、综合方法与数据覆盖率。切换视图时地图与 Inspector 同步。缺失数据显示 N/A，不填充。评分是曼哈顿内部的百分位排名（原始代理量），**不是**校准后的体验评分。Explore 与 AI Journey 相互独立（Explore 中不显示路线、起终点和 POI）。数据由 `python3 scripts/build_manhattan_streets.py` 生成到 `data/manhattan-streets.json`；`server.py` 启动时若数据超过 30 天（`STREETWISE_REFRESH_DAYS`，设为 0 关闭）会在后台自动重建。
3. 在 Navigate 模式下展开 **Street evidence**，选择 **Nature** 或 **Architecture**，切换 **Street evidence / Original points / Validated score**。前两项显示实际记录或代理量；Validated score 明确显示 NULL，不伪造分数。
4. 点击街段，查看 ID、原始证据、来源、年份与方法。勾选/取消 Trees、Landmarks、Experience、Coverage、POIs。Navigate 下路线强制保持可见；Explore 可关闭 Routes。
5. 默认 Bryant Park → Rockefeller Center，输入 `I want a greener walk with interesting architecture.`，点击 **Plan My Walk**。服务器上的路线引擎在 OSM 步行路网上生成最短、最佳体验和替代路线，按你的偏好排序。
6. 右侧 Route Intelligence 显示每条路线的距离、时间、绕路比例、个性化得分、12 维评分、数据覆盖率和排序说明；“Compare routes” 并排比较；“Route edges” 列出路线经过的 OSM 边。点击地图上的路线路段打开 Route Edge Inspector（OSM Edge ID、匹配的 LION 路段、评分与来源）。
7. 输入后续需求，或打开偏好 Slider 并改变权重。系统重新请求路径及数据并排序，保持视角；若最佳路线几何未变，解释其仍是当前可行候选中的最佳。
8. 点击 GPS：允许、拒绝、超时分别显示状态；再次点击连续定位可停止。GPS 为起点、定位精度 ≤60 m 且偏离路线 >60 m 时请求重规划。仅前台定位，无语音或逐转向导航。
9. 放大到局部范围，点击 **Analyze current view** 进行实时分析。过大的区域、失败或不完整数据不会生成评分。
10. 导出 sections GeoJSON，再通过保留的 **Kepler.gl Studio** 入口导入。GeoJSON 包含 12 个 NULL score 字段和真实代理量。

## Data / 数据

真实快照检索时间与来源 URL 均在 `data/pilot.json`：667 条 NYC Street Centerline 记录、3,177 条官方树木记录、186 条 LPC 地块记录。Nature 只计入 3,025 条 Alive 树木，Dead / Stump 排除。镜像树木源发现字段损坏，已替换为 **NYC Open Data 官方 Socrata 接口**。

The tree census is from 2015, not a live vegetation inventory. LPC and centerline observation years are unspecified in the source snapshot; retrieval time is not substituted for observation year. The 477 interior street sections exclude the 75 m bounding-box margin; this is a Midtown pilot, not complete Manhattan experience coverage. NYC centerlines are not automatically walkable graph edges.

## Navigate: Urban Data Layers / 路线周边城市数据

- 地图左下角 **Urban Data Layers**（默认收起）按**真实数据集**分为 10 类（街道与步行设施、自然、建筑、历史文化、餐饮商业、交通安全、环境、公共交通、公共服务、滨水与公共空间），不是按 12 个体验维度。首次打开时所有已接入数据集（59 个）**默认全部开启**；提供 All on / All off、类别开关（部分开启时为半选状态）、单个数据集开关、搜索、透明度和计数。未接入的标为 Not connected · available / Not connected · no dataset，并说明原因。
- 每个数据集的状态互相区分：Loaded · N within 100 m / No nearby features / Loading / Error / Zoom in to load；失败不会显示为 0。还没有规划路线时，数据按**当前地图视野**显示，规划路线后自动切换为路线两侧。全岛视野下只加载稀疏数据集（公园、地标、车站等），密集数据集（树木、建筑、人行道等）提示放大后加载；瓦片请求最多 12 个并发。
- 范围：**Along selected route**（所选路线两侧 50/100/200/500 m，仅影响显示，不改变评分）或 **Current map view**。切换路线时保留已开启的图层并重新筛选。
- 点击数据要素打开 Urban Feature Inspector（真实字段、缺失为 Not Available、来源、时间范围、更新日期、与路线的距离；事故/投诉标注为历史记录）。点击路线路段打开 Street Segment Evidence（OSM Edge ID、LION 路段或 Unmatched、附近数据的数量/密度/最近距离/覆盖率，以及现有评分指标）。右侧 **Route Urban Data** 汇总路线周边的真实要素数量，点击即在地图上显示。
- 图层是静态文件（`data/layers/catalog.json` + 1 km 瓦片），GitHub Pages 可直接读取，不占用后端内存。重建：`python3 scripts/build_urban_layers.py`（需要 OSMnx/pyproj，约 3 分钟）。
- 步行时间：默认 60 分钟，滑块 10–60，自定义更大值时滑块自动扩展；该值原样作为路线引擎的硬约束。

## Cartographic design system / 地图设计系统

全部数据同时开启时地图仍保持统一、清晰。规则写在 `urban-style.js`（设计 token），由 `urban-layers.js` 使用：

- **唯一强调色**：所选路线是地图上唯一的青柠色（`#d8f365`，带深色描边光晕），位于所有数据之上；备选路线为低对比灰色虚线；起点/终点为精确的小圆点。`tests/urban-style.test.cjs` 检查没有任何数据颜色接近路线色。
- **语义色系**（为深色底图调校、低饱和）：街道 蓝灰 · 建筑 深中性灰 · 公园/树木 柔和绿 · 历史文化 淡紫 · 餐饮商业 琥珀 · 公共设施 青绿 · 交通 冷蓝 · 安全 珊瑚 · 环境 连续色带。同类数据集在同一色相内微调明度（`shade()`）。
- **按几何与层级组合，而不是每个数据集一套图层**：建筑、绿地、铺装、历史街区、地标、线、噪声、树木以及每个类别一个点图层（约 63 个固定图层，原先约 240 个）。图层按层级锚点排序：面 → 线 → 环境 → 树 → 点 → 标签 → 路线。同一建筑在多个建筑数据集中只画一次；通用的 Activity places 不再重复画出已由具体数据集画出的地点。
- **建筑主题**（一次一个填充主题）：Neutral / Height / Age / Land use（PLUTO 地块）。**环境主题**（一次一个连续表面）：311 噪声投诉密度，带单位/年份/来源；空气质量、热岛、洪水风险列出但标为 not connected。
- **四个缩放层级**：City（<13，点按类别聚合为带数字的环）· Neighborhood（13–15）· Street（15–17，人行道/斑马线/建筑轮廓出现，聚合拆开）· Detail（≥17，名称标签）。街道设施类点（坡道、信号等）视觉权重更低；离路线越远的记录越淡。
- **动态图例**（可折叠，手机上默认收起）：只显示当前地图上真正可见的符号，并说明聚合、概括化和当前主题。
- 点击：路线路段优先（Street Segment Evidence），其次是最上层的数据要素（Urban Feature Inspector）；聚合环点击后放大展开。

## Live navigation, route QA and data registry / 实时导航、路线质检与数据登记

| 功能 | 状态 |
|---|---|
| 数据集登记表 `data/registry.json`（`scripts/build_registry.py`：103 个数据集，记录数、有效几何、重复、缺失字段、许可、发布方更新时间、新鲜度、接入状态，全部从实际文件统计） | Implemented & Tested |
| 规范地点模型与实体消解（`build_place_index.py`：canonical ID、provider IDs、步行接入距离、数据质量、冲突字段、LPC 地标与 OSM 关联；同名且同地址或 60 m 内才合并，同楼不同商家保留） | Implemented & Tested |
| 菜品证据四级：Confirmed Menu Match / Probable Match — Review Needed / Unverified / Not Found in Checked Sources；HTML 与 PDF 菜单，图片菜单不做 OCR（Unverified） | Implemented & Tested |
| 菜单抓取 SSRF 防护：只读地点索引中的官方网站；仅 http/https 和标准端口；DNS 解析后必须是公网地址并固定连接该 IP；每次重定向重新校验；大小、页数、超时限制；robots.txt；每客户端限流（菜单 10 次/分钟） | Implemented & Tested |
| 路线质检：每条路线和行程返回 `validation`（几何、步行网络、必经站点、站点入口、时间、距离、菜品证据、数据覆盖、警告、阻断问题、版本、时间），有阻断问题时禁止开始导航 | Implemented & Tested |
| 逐转弯指令 `routing/maneuvers.py`：只基于所选路线的有向边和路网拓扑；无其他可走方向的弯道不播报；人行横道直行不播报；名称来自 OSM、LION（标注为推导）或路的类型；近距离转弯合并；数据断裂给出低置信度提示而不是猜测 | Implemented & Tested |
| 可恢复的导航会话：`route_signature` + 有序边 ID；服务器重启后可用快照重建，版本不一致时拒绝并要求重新规划；浏览器 sessionStorage 仅保存路线和进度（6 小时，不保存 GPS 轨迹） | Implemented & Tested（浏览器刷新恢复：Implemented, Not Device-Tested） |
| 实时导航 `nav-engine.js`：13 个状态的状态机、窗口化地图匹配（精度、步行速度、方向、防跳点、防倒退）、沿路线的转弯距离、去重的提前/接近/立即提醒、多信号偏航判断、站点到达需用户确认 | Implemented & Tested（14 个可重放 GPS 场景） |
| 导航界面 `nav-ui.js`：大号转弯卡片、蓝色定位点、精度圆、仅在有可信方向时显示的方向扇形、北向/航向向上、拖动后暂停跟随并可 Recenter、剩余距离/时间/站点、语音（中/英）、暂停/退出、偏航重算（保留剩余必经站点，限频，失败保留原路线并可重试）、Navigate to Start / 从当前位置重新规划 | Implemented, Not Device-Tested（浏览器内用模拟 GPS 测试） |
| Explore 分析：分布统计、两个维度对比（Spearman ρ）、维度背后的数据集、维度搜索、重置视图；检查器显示归一化方法、数据版本和来源 | Implemented & Tested |
| Explore 中显示城市数据图层（目前只在 Navigate 中） | Partial |

**真实设备测试计划（Not Tested — 需要实体设备和户外步行）：** iPhone Safari、Android Chrome、桌面 Chrome。逐项检查：定位权限、方向权限（iOS 需点击后授权）、精度圆、方向扇形、地图跟随、转弯指令、语音、锁屏和后台（浏览器可能暂停定位，属于平台限制）、断网、Recenter、暂停/继续、到达。屏幕常亮使用 Wake Lock API（支持的浏览器才有效）。本项目不具备 Google Maps 等级的可靠性，也不知道实时施工或封路。

## AI Discover My Walk / 城市漫步发现与多站点路线

游客不需要知道目的地，只要说出想看什么、想吃什么、住在哪里、有多少时间、能走多远。

| 功能 | 状态 | 说明 |
|---|---|---|
| 全纽约地点搜索（起点、终点、酒店、添加站点共用） | Implemented | `places.js`：Photon（OpenStreetMap POI）+ NYC GeoSearch（NYC Planning 官方地址/场所，五大区），输入 2 个字符起查询，300 ms 防抖，可取消请求，旧请求不会覆盖新结果，键盘/鼠标/触摸，加载/无结果/错误状态，显示 GPS 直线距离（标明为直线），选中后绑定来源 ID 和坐标；手动改名即清除坐标。Mapbox Search Box（/suggest + /retrieve）已接好，仅在配置公开 token 后启用（Blocked：未配置）。 |
| 道路交叉口搜索 | Partial | 两个免费服务对 “5 Av & 42 St” 这类交叉口支持有限；可用地图点选（附反向地理编码）。 |
| 地点发现（景点、博物馆、历史建筑、公园、购物、餐饮、酒店、药店、超市、医院、ATM/银行、公共卫生间、行李寄存） | Implemented（仅 Manhattan） | `data/places/`（`scripts/build_place_index.py`）：OpenStreetMap Overpass 快照 + NYC LPC 地标 + NYC 公共卫生间开放数据，只收录离步行路网 150 m 内的地点（共 13,300+ 条），每条有来源 ID、名称、类别、地址、坐标、网站、营业时间、来源和数据时间。“著名程度”使用 Wikidata 条目的维基百科语言版本数（帝国大厦 125），而不是名称相似度。行李寄存在 OSM 中只有 1 条，这是数据缺口。 |
| 自然语言理解 | Partial | 配置 LLM Key 后，`/api/interpret` 输出结构化 `journey`（兴趣、指定地点、餐饮/菜品、服务、酒店、起终点、步行时间、总时长、距离），未知字段为 null，模型不得输出坐标、菜单或价格。线上 Render 当前**没有配置 LLM Key**，因此使用明确标注的“Limited local interpretation”中英文解析器（规范中的多轮语句均已测试）。 |
| 多轮对话状态 | Implemented | 每轮合并而不清空：起点、酒店、站点、餐饮、终点方式、时间和距离都会保留；“再加一个博物馆”、“延长到 180 分钟”只改对应项。 |
| 多站点路线规划 | Implemented | `/api/itinerary`（`routing/itinerary.py`）：地点吸附到 OSM 步行路网 → 真实路网距离矩阵（每个地点一次 Dijkstra） → 必经点 ≤ 7 个时精确枚举顺序与候选，否则最便宜插入 + 2-opt（**标注为启发式，不保证最优**） → 可选站点按“价值/新增分钟”贪心插入，且不超出预算 → 每段用体验加权代价路由并拼接成一条连续路线。必经点不会被静默删除，超出预算时返回“不可行”和原因。支持往返、回酒店、指定终点、开放终点和用户指定顺序。 |
| 步行与停留时间 | Implemented | 默认最大步行时间 100 分钟（快捷 60/100/120/150/自定义）；最大步行距离默认不设（2/5/8/10 km/自定义，km/mi 切换）；可选总时长 = 步行 + 停留。停留时间为估计值，明确标注且可修改。“我有两个小时”= 总时长 120 分钟。 |
| 餐厅与菜单核验 | Partial | 先找真实店铺（OSM 菜系/drink 标签只作为线索），再用 `/api/menu/verify` 读取该店官方网站（优先 `website:menu`），遵守 robots.txt，单次用户操作最多读 3 页。三种状态：Verified on Menu（菜单页上找到，附价格和来源链接）/ Unverified / Not Found in Available Sources。没有接入有授权的菜单 API；菜单上有不代表当天有货。 |
| 酒店 | Implemented | 酒店属于同一个地点搜索；“My Hotel”可作为起点、终点或搜索中心；名称有歧义时列出真实候选让用户确认；只有勾选“Remember on this device”才保存在本浏览器。只是搜索，没有实时房态、价格或预订。 |
| 生活服务 | Implemented | “附近找”只列出地点，不改路线；“沿途找”按真实路网绕路时间排序（`/api/detours`）；“先去存行李”作为必经站点。营业状态来自 OSM 营业时间，不推断一定开放。 |
| 语音输入 | Partial | 浏览器 Web Speech API（中文/English），转写结果进入同一输入框，可编辑后发送，与文字使用同一套解析和规划。没有服务器端语音服务；不支持的浏览器会禁用麦克风并提示。真实麦克风识别未在自动化测试中验证。 |
| 路由覆盖范围 | Manhattan only | 地点搜索覆盖五大区，但步行路网只有 Manhattan。其他行政区的地点会标注 “search only”，规划时明确报错，不生成虚假路线；不把渡轮、地铁当作步行连接。 |

营业时间：`opening-hours.js` 只在 OSM 写法能被确定解析时判断“到达时是否营业”，否则显示“未知”。

## NYC tourism intelligence / 城市旅游信息与证据推荐

Data coverage and quality are measured, not estimated: `python3 scripts/build_registry.py && python3 scripts/build_audit_report.py` writes `data/registry.json`, `DATA_AUDIT_REPORT.md` and `data/audit.json`. Every dataset has a class (`static_urban`, `periodic_poi`, `on_demand_business`, `realtime_availability`), an update frequency and known limitations. `python3 scripts/build_inspections.py` refreshes the NYC DOHMH permits (five boroughs, server-side `data/inspections/dohmh.json.gz`).

| API | Purpose |
|---|---|
| `GET /api/places/search?lat&lon&categories&radius_m&q&cuisine&include_closed` | Canonical places near a point. Manhattan: discovery index (OSM, LPC, NYC restrooms, DOHMH, Wikidata, DOF hotel lots). Other boroughs: DOHMH food permits, `routing_coverage: search_only`. |
| `GET /api/places/<id>` | Canonical place with a `restaurant` / `hotel` / `attraction` / `service` extension, `data_sources` and a rule-based `quality_status` (`verified`, `unverified`, `limited_data`, `closed`). |
| `GET /api/places/<id>/ratings` | Ratings per provider (Google Places, Yelp Fusion, Foursquare), never blended, held 15 min in memory only. Without keys: `blocked_by_provider_access`. |
| `GET /api/hotels/<id>/rooms?checkin&checkout&guests` | Room types, prices and availability need a lodging partner API (Booking.com Demand, Expedia Rapid). None is configured: `blocked_by_provider_access`, no rooms. |
| `POST /api/recommend/food` | Requested item → discover → hard filters (DOHMH closure, closed at arrival, unreachable, detour limit) → official-menu evidence → detour → rank → explanation in four parts: verified facts, derived metrics, rule-based interpretation, unknowns. |

Provider keys (`GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `FOURSQUARE_API_KEY`, `BOOKING_DEMAND_API_KEY`, `EXPEDIA_RAPID_API_KEY`) are read only by the Render backend; `/api/status` reports which are configured as booleans. Rate limits per client per minute: places 60, ratings/rooms 20, recommendations 6. No third-party page (Google Maps, Yelp, Booking.com) is scraped.

| Feature | Status |
|---|---|
| Data audit report, dataset classes, update policy | Implemented & Tested |
| Five-borough coverage | Partial — food places (DOHMH) in all five boroughs, search only outside Manhattan; attractions, hotels and routing stay Manhattan |
| Canonical place model, entity resolution (name + distance; branches stay separate) | Implemented & Tested |
| DOHMH health grade and closure status on restaurant cards | Implemented & Tested |
| Restaurant ratings and review counts | Blocked by Provider Access (adapters tested with recorded responses) |
| Menu items | Partial — item evidence from the official website only (Verified / Probable / Unverified / Not Found); no menu API |
| Food recommendation pipeline with evidence sections | Implemented & Tested (locally); Not Production-Tested |
| Restaurant / hotel / attraction cards with confidence labels | Implemented, Not Production-Tested (checked in a local browser) |
| Hotel stars (OSM) kept apart from guest rating | Implemented & Tested; guest rating Blocked by Provider Access |
| Hotel room types, prices, availability, money budget | Blocked by Provider Access |
| Hotel-based walks (start or return to My Hotel) | Implemented & Tested |
| Attraction opening hours, closed-at-arrival and closing-during-visit checks | Implemented & Tested (OSM hours incl. dated closures; anything else is "unknown") |
| Admission and reservation | Partial — OSM `fee` / `charge` / `reservation` tags; amounts are rarely mapped |
| Current exhibitions, live crowding | Not Implemented (no authorised source) |

## Weather-aware routing / 天气感知路线

天气是**独立的动态上下文**，不是第 13 个维度，也不改变 12 维静态评分。

- **数据**（`weather.js`，全站只请求一次，15 分钟刷新，地图移动不会触发请求）：Open-Meteo 预报 API（无需 Key；`current` 为 15 分钟模型状态，`hourly` 为预报，不是站点实测）+ 美国国家气象局 NWS 当前警报。获取温度、体感温度、湿度、降水、降水概率、风速风向、天气类型、时间戳；显示来源、更新时间和过期状态（45 分钟后标为 stale；引擎拒绝 180 分钟以上的数据）。请求失败或离线时状态为 unavailable，路线照常计算。
- **步行时段**：按“现在出发 + 最大步行时间”覆盖的预报小时取最不利值（最高体感温度、最大降水概率、最大风速、是否白天）。
- **路线成本**（`routing/weather.py` + `routing/engine.py`）：`边成本 = 原有成本 + 系数 × 热度 × 暴露度`，仅在以下条件同时满足时启用：体感温度 ≥ 27 °C（NWS “Caution”，32 °C 时达到满值）、步行时段在白天、有空间证据。暴露度 = 1 − 树木覆盖代理值（行道树密度，150 棵/km 为满值，约曼哈顿第 90 百分位；或与公园相邻的比例）。**这是树木覆盖代理变量，不是实测遮阴。**无证据的边取全网中位数（中性，不当作最差）。原有候选路线完全不变，另加一条 “Cooler Route (tree-cover proxy)” 候选；排序再减去 `20 × 热度 × 暴露长度占比`。用户明确要求更凉快或更遮阴时，权重 ×2。所有系数都在 `CONFIG` 中，并附理由；响应会回传 `config_version`。
- **雨、风**：没有有顶步道、脚手架、积水或街道风环境数据，因此**只做提醒，不改变路线**，也不声称某条路更干或更避风。
- **四种状态分开显示**：Weather Data Available / Weather Context Applied / Weather Routing Active / Weather Routing Unavailable。响应中的 `weather_routing` 记录天气是否进入计算、原因，以及对推荐的实际影响（与不考虑天气时的推荐相比：是否改变、多花几分钟、暴露减少多少）。Route Intelligence 和对话只复述这条记录。
- **AI Journey**：识别 “cooler / too hot / shade / 凉快 / 阴凉” 等（热度项 ×2，不改其他偏好）、“consider today's weather”（使用天气）、“Is my route comfortable in this weather?”（根据数据回答，不重新规划）。LLM 模式下，预报作为上下文传入，输出新增 `weather` 字段。
- **界面**：Navigate 地图左上角是紧凑的天气标签，展开后显示当前天气、步行时段预报、NWS 警报、天气路线状态、开关、刷新，以及天气变化后的 “Recalculate” 按钮；点击地图即收起，Explore 中隐藏。右侧新增 “Weather & your walk”：天气状况 / 对步行的影响 / 天气路线说明。
- **重新规划**：只有天气等级发生变化时才提示重新计算，例如热度档位、白天黑夜、雨或风提醒；数值小幅波动不会提示，也不会自动切换路线。

## Files / 文件

- `routing/engine.py`: pedestrian routing engine — graph loading, snapping, A*, candidate routes, route scores, personalized ranking, navigation progress.
- `server.py`: existing APIs plus `/api/routes`, `/api/edges/…`, `/api/segments/…`, `/api/routing/status`, `/api/navigation/progress`; gzip, data auto-refresh.
- `route-client.js`: AI Journey ↔ engine adapter, Route Intelligence (cards, 12-dimension profile, comparison, ordered edges), route-edge inspector, GPS progress.
- `explore-map.js`: Explore Urban Data (13 maps, segment inspector). `app.js`, `center-map.js`: existing shell, preferences, map, Street evidence panel.
- `scripts/streetwise_indicators.py`: shared indicator definitions and measurement. `build_manhattan_streets.py`: LION scores. `build_pedestrian_network.py`: OSM graph. `match_lion_osm.py`: matching + edge scores.
- `data/manhattan-streets.json`, `data/pedestrian/`: built data. `data/cache/`: raw downloads (safe to delete).
- `nav-engine.js`: navigation engine (map matching, state machine, alerts). `nav-ui.js`: live navigation UI, voice, re-routing, session. `explore-analytics.js`: Explore distribution / comparison / dataset details. `routing/validation.py`: route QA. `routing/maneuvers.py`: turn-by-turn maneuvers. `scripts/build_registry.py` → `data/registry.json`.
- `places.js`: NYC-wide place search (Photon + NYC GeoSearch + optional Mapbox) and the shared autocomplete. `journey.js`: AI Discover My Walk state, agent tools, local journey parser, itinerary planning client. `journey-ui.js`: journey panel, My Hotel, map waypoints, Your City Walk. `voice.js`: Web Speech input. `opening-hours.js`: OSM hours check. `routing/itinerary.py`: multi-stop planner + detours. `routing/menu.py`: official-website menu verification. `scripts/build_place_index.py` → `data/places/`.
- `weather.js`: shared weather context (Open-Meteo + NWS, walk window, routing snapshot). `weather-ui.js`: Navigate weather status, Route Intelligence weather section, weather chat answers. `routing/weather.py`: weather assessment, coefficients, tree-cover exposure.
- `urban-style.js`: cartographic design tokens (colours, zoom tiers, point/line/building/environment styles). `urban-layers.js`: dataset catalog panel, composition into grouped map layers, themes, dynamic legend, static tile loading, map layers, Urban Feature Inspector, Street Segment Evidence, Route Urban Data. `urban-geo.js`: shared geometry (projection, corridor, nearest, coverage). `api-config.js`: API base + `streetwiseJson`. `routing/layers.py`: reference implementation for tests. `scripts/build_urban_layers.py`: datasets → catalog + tiles.
- `tests/`: `test_routing_engine.py` (network, matching, scores, ranking, navigation, HTTP), `test_urban_layers.py` (catalog, geographic accuracy, route queries, static serving, walking-time limits), `urban-style.test.cjs` (design-system rules), `test_weather_routing.py` (weather states, heat cost in A*, constraints, reproducibility), `weather.test.cjs` (forecast window, NY time, snapshot), `test_itinerary.py` (multi-stop planner, matrix = A*, constraints, order, coverage, detours, menu statuses), `places.test.cjs` (place search on recorded provider responses; `LIVE=1` for live), `opening-hours.test.cjs`, `urban-geo.test.cjs` (browser geometry = brute-force reference), `test_street_data.py`, `test_server.py`, `dom.test.cjs`, JS spatial tests, Playwright scripts.

## Automated checks / 自动测试

```bash
node tests/spatial.test.cjs
node tests/real-route.test.cjs
node tests/urban-geo.test.cjs
node tests/urban-style.test.cjs
node tests/weather.test.cjs
node tests/places.test.cjs          # LIVE=1 node tests/places.test.cjs calls the real providers
node tests/opening-hours.test.cjs
node tests/nav-gps.test.cjs          # 14 replayable GPS tracks on a real route
python3 -m unittest discover -s tests -p 'test_*.py'   # includes the routing engine end-to-end tests
python3 -m unittest tests.test_tourism   # datasets, places, hours, providers (stubbed), scenarios A–F, endpoints
# Install jsdom separately for DOM integration tests:
npm install --prefix /tmp/streetwise-test jsdom
JSDOM_PATH=/tmp/streetwise-test/node_modules/jsdom node tests/dom.test.cjs
```

Browser scripts require Playwright and a supported Chromium installation. `CHROME_PATH` may specify its executable. The cartographic redesign was checked visually in a real browser (MapLibre/WebGL, 1440×900 and 375×812): route/street/city/detail zoom, height, age and land-use building themes, Current map view in dense Midtown, clicks on data points and route segments, Explore round trip. Real hardware GPS and touch gestures on a physical phone were not tested. DOM tests do not prove rendered map interactions.
