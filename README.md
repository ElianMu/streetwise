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

- 地图左下角 **Urban Data Layers**（默认收起）按**真实数据集**分为 10 类（街道与步行设施、自然、建筑、历史文化、餐饮商业、交通安全、环境、公共交通、公共服务、滨水与公共空间），不是按 12 个体验维度。54 个已接入数据集可独立开关、搜索、调透明度；未接入的标为 Available · not connected / Missing，并说明原因。
- 范围：**Along selected route**（所选路线两侧 50/100/200/500 m，仅影响显示，不改变评分）或 **Current map view**。切换路线时保留已开启的图层并重新筛选。
- 点击数据要素打开 Urban Feature Inspector（真实字段、缺失为 Not Available、来源、时间范围、更新日期、与路线的距离；事故/投诉标注为历史记录）。点击路线路段打开 Street Segment Evidence（OSM Edge ID、LION 路段或 Unmatched、附近数据的数量/密度/最近距离/覆盖率，以及现有评分指标）。右侧 **Route Urban Data** 汇总路线周边的真实要素数量，点击即在地图上显示。
- 图层是静态文件（`data/layers/catalog.json` + 1 km 瓦片），GitHub Pages 可直接读取，不占用后端内存。重建：`python3 scripts/build_urban_layers.py`（需要 OSMnx/pyproj，约 3 分钟）。
- 步行时间：默认 60 分钟，滑块 10–60，自定义更大值时滑块自动扩展；该值原样作为路线引擎的硬约束。

## Files / 文件

- `routing/engine.py`: pedestrian routing engine — graph loading, snapping, A*, candidate routes, route scores, personalized ranking, navigation progress.
- `server.py`: existing APIs plus `/api/routes`, `/api/edges/…`, `/api/segments/…`, `/api/routing/status`, `/api/navigation/progress`; gzip, data auto-refresh.
- `route-client.js`: AI Journey ↔ engine adapter, Route Intelligence (cards, 12-dimension profile, comparison, ordered edges), route-edge inspector, GPS progress.
- `explore-map.js`: Explore Urban Data (13 maps, segment inspector). `app.js`, `center-map.js`: existing shell, preferences, map, Street evidence panel.
- `scripts/streetwise_indicators.py`: shared indicator definitions and measurement. `build_manhattan_streets.py`: LION scores. `build_pedestrian_network.py`: OSM graph. `match_lion_osm.py`: matching + edge scores.
- `data/manhattan-streets.json`, `data/pedestrian/`: built data. `data/cache/`: raw downloads (safe to delete).
- `urban-layers.js`: dataset catalog panel, static tile loading, map layers, Urban Feature Inspector, Street Segment Evidence, Route Urban Data. `urban-geo.js`: shared geometry (projection, corridor, nearest, coverage). `api-config.js`: API base + `streetwiseJson`. `routing/layers.py`: reference implementation for tests. `scripts/build_urban_layers.py`: datasets → catalog + tiles.
- `tests/`: `test_routing_engine.py` (network, matching, scores, ranking, navigation, HTTP), `test_urban_layers.py` (catalog, geographic accuracy, route queries, static serving, walking-time limits), `urban-geo.test.cjs` (browser geometry = brute-force reference), `test_street_data.py`, `test_server.py`, `dom.test.cjs`, JS spatial tests, Playwright scripts.

## Automated checks / 自动测试

```bash
node tests/spatial.test.cjs
node tests/real-route.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py'   # includes the routing engine end-to-end tests
# Install jsdom separately for DOM integration tests:
npm install --prefix /tmp/streetwise-test jsdom
JSDOM_PATH=/tmp/streetwise-test/node_modules/jsdom node tests/dom.test.cjs
```

Browser scripts require Playwright and a supported Chromium installation. `CHROME_PATH` may specify its executable. Browser/WebGL, touch layout and real hardware GPS acceptance **were not completed in this environment** because browser startup was blocked. DOM tests do not prove rendered map interactions.
