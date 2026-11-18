/* Chinese interface (简体中文), switchable; English stays the default and the source of truth.

   How it works: the page is written in English. In Chinese mode a text node, placeholder, title or aria-label whose
   whole text is a key of I18N_ZH is shown in Chinese; a MutationObserver does the same for text the app writes later.
   The English original is kept on the node, so switching back restores it exactly. No app code is changed and nothing
   is translated by a machine at run time: every Chinese string below was written by hand.

   What is NOT translated, on purpose:
   - Sentences the app builds from data (route explanations, "Why this route?", AI replies, toasts with numbers). They
     stay in English rather than being half-translated. i18nCoverageNote says so in the menu.
   - Input values. The sentence the priority pills write into the request box stays English because the planner reads
     it. Visitors can type their own request in Chinese: on 2026-11-15 the live interpreter turned
     "我想要一条更绿、更安静、建筑有看头的路线" into Nature, Quiet & Relax and Architecture at 90. A start and destination
     written in a Chinese sentence are not filled into From / To (that step reads English), which the hint says.
   - The 12 dimension names are not renamed: Chinese mode shows a Chinese gloss followed by the unchanged English
     name ("自然 Nature"), so the name on screen always matches the data, the docs and the methodology.
   - Place names and data-source names.

   The choice is remembered in this browser only (localStorage), never sent anywhere. */
const I18N_DIMENSIONS_ZH = {
 'Architecture': '建筑', 'Nature': '自然', 'Culture': '文化', 'Quiet & Relax': '安静放松', 'Spatial Comfort': '空间舒适',
 'Urban Vibrancy': '城市活力', 'Food & Retail': '餐饮零售', 'Scenic & Visual': '景观视野', 'Walkability': '步行便利',
 'Access & Safety': '通行与安全', 'Environment': '环境', 'Transit Connectivity': '公交接驳',
};
const I18N_ZH = {
 // navigation and menus
 'Plan walk': '规划步行', 'Start & destination': '起点与终点', 'Customize walk': '自定义步行', 'Time & 12 dimensions': '时间与 12 个维度',
 'Explore urban data': '浏览城市数据', 'Explore Urban Data': '浏览城市数据', 'NYC GIS layers': '纽约 GIS 图层', 'Map layers': '地图图层', 'Weather & legend': '天气与图例',
 'Map': '地图', 'Dark': '深色', 'Light': '浅色', 'Reset map view': '重置地图视图', 'Back to Manhattan': '回到曼哈顿', 'Data legend': '数据图例',
 'Show or hide': '显示或隐藏', 'Data sources': '数据来源', 'Status & coverage': '状态与覆盖范围', 'About': '关于', 'This prototype': '本原型',
 'Export to Kepler': '导出到 Kepler', 'GIS data': 'GIS 数据', 'Kepler studio': 'Kepler 工作台', 'Menu': '菜单', 'Back': '返回', '← Map': '← 地图',
 'Weather loading…': '天气加载中…', 'Weather…': '天气…', 'Find routes →': '查找路线 →', '⚙ Prefs': '⚙ 偏好', 'Navigate': '导航', 'Edit': '编辑', 'New': '新建',
 '☷ Plan': '☷ 规划', '◈ Results': '◈ 结果', 'Your walk': '你的步行', 'Interface language': '界面语言',
 // route result labels (the sentences and numbers beside them are built from data and stay in English)
 'Personalized score': '个性化得分', 'Overall score': '综合得分', 'Data coverage': '数据覆盖', 'Detour': '绕行', 'Shortest distance': '最短距离', 'Engine route': '引擎路线',
 'Describe your ideal walk...': '描述你理想的步行…（中文也可以）', 'choose destination': '选择终点',
 // planning
 '01 / HOW DO YOU WANT TO WALK?': '01 / 你想怎么走？', 'Find your': '找到属于你的', 'kind': '那种', 'of walk.': '步行。',
 'Not just the shortest way. Your way through the city.': '不只是最短的路，而是你穿过城市的方式。',
 'Made for people new to New York: get to know a Manhattan neighbourhood on a walk of 20 minutes or more.': '为刚到纽约的人而做：用一段 20 分钟以上的步行，认识曼哈顿的一个街区。',
 'WHAT MATTERS ON THIS WALK': '这次步行你在意什么',
 'Or describe the walk in your own words. From and To fill in from your sentence.': '也可以用自己的话描述这次步行，中文也可以。用中文描述时，起点和终点请在下方选择。',
 'Voice or text — you can edit the transcript.': '语音或文字均可，识别结果可以修改。',
 'I\u2019d like a greener, quieter walk with interesting architecture.': '我想要一条更绿、更安静、建筑有看头的路线。',
 'Make it quieter, even if it takes five more minutes…': '再安静一点，多走五分钟也可以…', 'Search address or landmark': '搜索地址或地标', 'Search dimensions…': '搜索维度…',
 'Search urban datasets…': '搜索城市数据集…', 'Add a stop: any NYC place': '添加途经点：纽约任意地点', 'Search any NYC address, place or business': '搜索纽约的地址、地点或商家',
 'Search your hotel (name or brand)': '搜索你的酒店（名称或品牌）',
 'Plan My Walk': '规划我的步行', 'Create My Walk': '生成我的步行', 'How would you like to explore New York?': '你想怎样探索纽约？',
 'Checking AI interpretation service…': '正在检查 AI 理解服务…',
 'Know a neighbourhood': '认识一个街区', 'The nicer way': '走更舒服的那条路', 'A walk with a point': '有内容的散步',
 '02 / FROM & TO': '02 / 起点与终点', 'FROM': '起点', 'TO': '终点', 'From': '起点', 'To': '终点', '◎ Use GPS': '◎ 使用定位',
 'Quick-pick a start (default: my location)': '快速选择起点（默认：我的位置）', 'Quick-pick a destination (optional)': '快速选择终点（可选）',
 'Custom map / address point': '自选地图点或地址', 'My current location': '我的当前位置', 'Swap': '交换', 'STOPS': '途经点', 'optional · in order': '可选 · 按顺序',
 '⌖ PICK ON MAP': '⌖ 在地图上选点', 'Destination': '指定终点', 'Discover for me': '为我推荐', 'Back to start': '回到起点', 'Back to hotel': '回到酒店',
 'My hotel ·': '我的酒店 ·', 'not set': '未设置', 'Start here': '从这里出发', 'Return here': '回到这里', 'Explore nearby': '探索周边',
 'Remember on this device': '在本设备上记住', 'stored only in this browser': '仅保存在本浏览器',
 'Hotel search shows real places from map data. No live room availability, prices or booking.': '酒店搜索显示的是地图数据中的真实地点，不提供实时房态、价格或预订。',
 'DISCOVERY': '探索', 'Clear journey': '清空行程', 'QUICK PREFERENCES': '快捷偏好',
 'Each chip sets an existing experience dimension (or adds a café stop through the journey planner). Nothing is claimed until routes are computed.': '每个按钮对应一个已有的体验维度（或通过行程规划加一个咖啡停留点）。路线算出来之前，不会声称任何效果。',
 'Click anywhere on the map to set a point.': '点击地图任意位置来设定一个点。', 'CANCEL': '取消',
 // preferences
 '03 / YOUR WALKING PREFERENCES': '03 / 你的步行偏好', 'NOT INTERPRETED': '尚未解析',
 'Strollane turns your words into priorities; unmentioned dimensions stay neutral.': 'Strollane 把你的话转成偏好；没提到的维度保持中性。',
 '✧ Your interpreted priorities appear here after planning.': '✧ 规划后，这里会显示解析出的偏好。',
 'Fine-tune (12 dimensions)': '微调（12 个维度）', 'EXPERIENCE DIMENSION': '体验维度', 'PREFERENCE': '偏好', '✎ Adjust preferences': '✎ 调整偏好',
 'Weights indicate user preference (0–100), not objective city quality. Default 50 = not expressed. Route scores are relative ranks within Manhattan, computed from public NYC and OpenStreetMap records: proxies, not validated measures of how a street feels.': '权重表示你的偏好（0–100），不是城市的客观质量。默认 50 表示未表达偏好。路线分数是曼哈顿内部的相对排名，由纽约公开数据和 OpenStreetMap 记录算出：它们是替代指标，并非经过验证的街道感受度量。',
 // constraints
 '04 / WALK OPTIONS': '04 / 步行选项', '04 / WALKING CONSTRAINTS': '04 / 步行限制', 'MAX WALKING TIME · A HARD LIMIT': '最长步行时间 · 硬性上限', 'Custom': '自定义',
 'Custom maximum (minutes)': '自定义上限（分钟）', 'Default 100 min. Type any whole number of minutes (10 or more); the slider extends to match.': '默认 100 分钟。可输入任意整数分钟（不少于 10），滑杆会随之延长。',
 'MAX WALKING DISTANCE · HARD LIMIT': '最长步行距离 · 硬性上限', 'NOT SET': '未设置', 'Not set': '未设置', 'Custom distance': '自定义距离',
 'Total outing (walking + visits, optional, minutes)': '总外出时间（步行 + 停留，可选，分钟）', 'Maximum detour over shortest candidate (%)': '相对最短路线的最大绕行（%）',
 'Avoid excessive detours': '避免过多绕行', '≤ 25% longer than baseline': '比基准路线最多长 25%', 'Step-free access': '无台阶通行', 'verified pedestrian-access data required': '需要经过核实的无障碍数据',
 'Avoid stairs': '避开楼梯', 'excludes OpenStreetMap steps from routing': '规划时排除 OpenStreetMap 中的台阶',
 '⚠ Step-free access needs verified curb-ramp and elevator data, which is not connected. Recommendations are blocked while this constraint is on.': '⚠ 无台阶通行需要经过核实的路缘坡道和电梯数据，目前尚未接入。开启此限制时不会给出推荐。',
 // conversation
 '05 / REFINE YOUR WALK': '05 / 调整你的步行', 'CONVERSATION': '对话', 'Ask for changes. New route results and the map are recomputed when possible.': '可以提出修改。条件允许时会重新计算路线和地图。',
 'Enter to send · Shift + Enter for a new line': '回车发送 · Shift + 回车换行', 'CONVERSATION LOG (FULL)': '完整对话记录',
 // results
 'YOUR WALK': '你的步行', 'Choose how it': '选择它带给你的', 'feels.': '感受。', 'YOUR WALK OPTIONS': '可选路线', 'No walks yet': '还没有路线',
 'Describe how you want to walk, or tap a few chips.': '描述你想怎么走，或者点几个按钮。', 'More routes': '更多路线', '➤ Start Navigation': '➤ 开始导航',
 '3D map preview': '3D 地图预览', 'Share this walk': '分享这条路线', 'ALONG THIS WALK': '沿途', 'On the street': '街景',
 'Choose a walk to see the places along it.': '选一条路线，查看沿途地点。', 'REFINE YOUR WALK': '调整你的步行',
 'More Nature': '更多自然', 'Quieter Streets': '更安静的街道', 'More Architecture': '更多建筑', 'Shorter Walk': '更短的路线',
 'Each action updates state and requests fresh pedestrian candidate routes. A preference without evidence will not be claimed as achieved.': '每次操作都会更新状态并重新请求候选步行路线。没有数据支持的偏好，不会被声称已实现。',
 'Technical details': '技术细节', 'Scores, ranking, data and edges': '分数、排名、数据与路段', 'LIVE WEATHER': '实时天气', 'Awaiting forecast': '等待天气预报',
 'GPS STATUS': '定位状态', 'OFF': '关闭', 'Location unavailable': '无法获取位置', 'RANKING': '排名', 'No route data yet.': '还没有路线数据。',
 'WHY THIS ROUTE?': '为什么是这条路线？', 'Generate routes to see evidence-grounded reasons.': '生成路线后，可查看有数据依据的理由。',
 'WEATHER & YOUR WALK': '天气与你的步行', 'Loading the forecast…': '正在加载天气预报…', 'ROUTE URBAN DATA': '路线周边城市数据',
 'Select a route to see the real city data around it.': '选一条路线，查看周边的真实城市数据。', 'ROUTE EDGES': '路线路段', 'Ordered OSM pedestrian edges': '按顺序排列的 OSM 步行路段',
 'Select a route to list the OSM pedestrian edges it uses, in order.': '选一条路线，按顺序列出它经过的 OSM 步行路段。',
 'EXPERIENCE PROFILE': '体验概况', 'NOT AVAILABLE': '暂无', 'Selected route': '所选路线', 'Compare routes': '比较路线',
 'Dimension Score ≠ Preference Weight. Missing is not zero.': '维度分数 ≠ 偏好权重。缺失不等于零。',
 'RESEARCH / RAW STREET EVIDENCE': '研究 / 街道原始数据', 'Click a street segment to inspect its recorded attributes.': '点击一段街道，查看它的记录属性。',
 'Clear selected street': '取消选中的街道', 'DATA & METHODOLOGY ↗': '数据与方法 ↗', 'Export GIS data for Kepler.gl': '导出 GIS 数据到 Kepler.gl',
 'PROJECT NOTES / TRANSPARENCY': '项目说明 / 透明度', "What is real, and what's next.": '哪些是真实的，接下来做什么。',
 // map and explore
 'Connecting to the city': '正在连接城市数据', 'Loading the Manhattan basemap and official NYC street-centerline data.': '正在加载曼哈顿底图和纽约官方街道中心线数据。',
 'CONNECTING TO NYC DATA…': '正在连接纽约数据…', 'Street evidence ▾': '街道数据 ▾', 'Dimension': '维度', 'Display': '显示', 'Experience': '体验', 'Coverage': '覆盖率',
 'Analyze current view': '分析当前视图', 'Scores require calibration. Unknown ≠ zero.': '分数需要校准。未知 ≠ 零。', 'Reset view': '重置视图', 'Line opacity': '线条不透明度',
 'Loading computed 12-dimension street data…': '正在加载已计算的 12 维度街道数据…', 'Choose a journey to compare real walking routes.': '选择一段行程，比较真实的步行路线。',
 'Urban Data Layers': '城市数据图层', 'Explore real NYC data along your route': '浏览路线沿途的真实纽约数据', 'ACTIVE DATASETS': '已启用的数据集', 'All on': '全部开启', 'All off': '全部关闭',
 'Opacity': '不透明度', 'Along selected route': '沿所选路线', 'Current map view': '当前地图视图', 'Route corridor': '路线走廊', 'display only — never changes scores': '仅用于显示，不影响分数',
 'NAVIGATION OVERLAYS': '导航叠加层', 'Alternative routes': '备选路线', 'Route POIs': '路线地点', 'Legend': '图例', 'Lower': '较低', 'Mid': '中等', 'Higher': '较高',
 'The selected route and start / destination always stay on top. Your location appears only after you allow GPS.': '所选路线和起终点始终显示在最上层。只有在你允许定位后，才会显示你的位置。',
 'Summary': '概要', 'Indicators': '指标', 'Methodology': '方法',
 // navigation mode
 'Starting…': '正在开始…', 'Retry': '重试', 'Continue to next stop': '前往下一站', 'Skip optional stop': '跳过可选停留点', 'You have arrived': '你已到达', 'Walk complete.': '步行结束。',
 'End navigation': '结束导航', '◎ Recenter': '◎ 回到当前位置', 'Voice on': '语音开启', 'Pause': '暂停', 'More': '更多', 'Repeat': '重复', 'North up': '正北朝上', 'Exit': '退出',
 // short pill labels (walk-presets.js): a gloss in front of the same short English label
 'Quiet': '安静 Quiet', 'Comfort': '舒适 Comfort', 'Vibrancy': '活力 Vibrancy', 'Scenic': '景观 Scenic', 'Safety': '安全 Safety', 'Transit': '公交 Transit', 'Food': '餐饮 Food',
 // journey and results labels
 "I'd like a greener, quieter walk with interesting architecture.": '我想要一条更绿、更安静、建筑有看头的路线。',
 'Plan your walk': '规划你的步行', 'Your routes': '你的路线', 'Coffee stop': '咖啡停留', 'YOUR CITY WALK': '你的城市漫步', 'WITHIN LIMITS': '在限制范围内', 'Walking': '步行', 'Stops': '停留点',
 'Total outing': '总外出时间', 'Replace': '更换', 'Remove': '移除', 'More museums': '更多博物馆', 'More historic': '更多历史建筑', 'Add coffee': '加一杯咖啡', 'Add restaurant': '加一家餐厅',
 'Return to hotel': '回酒店', 'Less walking': '少走一点', 'Extend time': '延长时间', 'Hours not listed': '未列出营业时间', 'NYC designated landmark': '纽约市指定地标',
 'Park': '公园', 'Historic building': '历史建筑', 'Museum': '博物馆', 'Landmark buildings': '地标建筑', 'Cultural venues': '文化场所', 'route match': '路线匹配',
 'Loading the map…': '地图加载中…', 'The street map is taking longer than usual on this connection. Everything else already works.': '当前网络下街道地图加载较慢，其他功能已可正常使用。',
 'Weather unavailable': '天气不可用', 'Weather n/a': '天气不可用', 'Weather-aware routing': '考虑天气的路线规划', 'Refresh': '刷新', 'Export sections to Kepler.gl': '导出分区到 Kepler.gl',
 'Building theme': '建筑主题', 'Environment theme': '环境主题', 'Open to load the dataset catalog.': '展开以加载数据集目录。', 'Street base (LION)': '街道底图（LION）', '↻ Streets': '↻ 街道',
 'Parks & gardens': '公园与花园', 'Street trees': '行道树', 'Historic districts': '历史街区', 'Landmark lots': '地标地块', 'Streets': '街道', 'Buildings': '建筑', 'Historic': '历史', 'Traffic': '交通', 'Public Services': '公共服务',
 'Places & facilities': '地点与设施', 'YOU': '你', 'Best match': '最佳匹配', 'best match': '最佳匹配', 'Shortest': '最短', 'Fastest': '最快',
 'Looking for street photos…': '正在查找街景照片…', 'Street evidence · raw units': '街道数据 · 原始单位', 'Original points / polygons': '原始点 / 面', 'Validated score · 0–100': '已验证分数 · 0–100',
 'Custom maximum (minutes)': '自定义上限（分钟）', 'Places near this walk have not been looked up yet.': '还没有查找这条路线附近的地点。', 'Generate or select a route to discover POIs.': '生成或选择一条路线以查看沿途地点。',
 // common dynamic labels
 'Planning your walk…': '正在规划你的步行…', 'Waking the route server…': '正在唤醒路线服务器…', 'Finding places & routing…': '正在查找地点并规划…', 'Details': '详情',
 'Locate me': '定位我', 'About the prototype': '关于本原型', 'Dismiss': '关闭', 'Clear': '清除', 'Describe your walk': '描述你的步行', 'Back to map': '回到地图', 'Quick preferences': '快捷偏好',
};
for (const [en, zh] of Object.entries(I18N_DIMENSIONS_ZH)) I18N_ZH[en] = `${zh} ${en}`; // gloss + the unchanged name

const I18N_ATTRS = ['placeholder', 'title', 'aria-label'];
const I18N_SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'CODE', 'PRE']);
const i18n = {lang: 'en', observer: null, busy: false};
const I18N_COVERAGE_NOTE = '界面已切换为中文。路线说明、AI 回复等由数据生成的句子仍为英文；12 个维度保留英文原名并附中文注释。可以用中文描述偏好；起点和终点请在输入框里选择。';

const i18nKey = (s) => s.replace(/\s+/g, ' ').trim();
function i18nText(node) {
 if (node.parentNode && I18N_SKIP.has(node.parentNode.nodeName)) return;
 if (i18n.lang === 'zh') {
  if (node.__zh !== undefined && node.nodeValue === node.__zh) return; // already shown in Chinese
  const key = i18nKey(node.nodeValue), zh = I18N_ZH[key];
  if (!zh) { node.__en = undefined; node.__zh = undefined; return; }
  node.__en = node.nodeValue; node.__zh = node.nodeValue.replace(node.nodeValue.trim(), zh); node.nodeValue = node.__zh;
 } else if (node.__en !== undefined) {
  if (node.nodeValue === node.__zh) node.nodeValue = node.__en; // untouched since translation: restore the original exactly
  node.__en = undefined; node.__zh = undefined;
 }
}
function i18nAttrs(el) {
 for (const a of I18N_ATTRS) {
  if (!el.hasAttribute || !el.hasAttribute(a)) continue;
  const store = 'data-i18n-en-' + a, shown = el.getAttribute(a);
  if (i18n.lang === 'zh') {
   const zh = I18N_ZH[i18nKey(shown)];
   if (zh && zh !== shown) { el.setAttribute(store, shown); el.setAttribute(a, zh); }
  } else if (el.hasAttribute(store)) {
   if (I18N_ZH[i18nKey(el.getAttribute(store))] === shown) el.setAttribute(a, el.getAttribute(store));
   el.removeAttribute(store);
  }
 }
}
function i18nApply(root) {
 if (!root) return;
 if (root.nodeType === 3) return i18nText(root);
 if (root.nodeType !== 1 || I18N_SKIP.has(root.nodeName)) return;
 i18nAttrs(root);
 const walker = document.createTreeWalker(root, 5 /* SHOW_ELEMENT | SHOW_TEXT */);
 for (let n = walker.nextNode(); n; n = walker.nextNode()) { if (n.nodeType === 3) i18nText(n); else i18nAttrs(n); }
}

function setLanguage(lang, remember = true) {
 if (lang !== 'zh' && lang !== 'en') return i18n.lang;
 i18n.lang = lang;
 document.documentElement.lang = lang === 'zh' ? 'zh-Hans' : 'en';
 i18n.busy = true; try { i18nApply(document.body); } finally { i18n.busy = false; }
 if (lang === 'zh' && !i18n.observer && typeof MutationObserver !== 'undefined') {
  i18n.observer = new MutationObserver((records) => {
   if (i18n.lang !== 'zh' || i18n.busy) return;
   i18n.busy = true;
   try {
    for (const r of records) {
     if (r.type === 'characterData') i18nText(r.target);
     else if (r.type === 'attributes') i18nAttrs(r.target);
     else r.addedNodes.forEach(i18nApply);
    }
   } finally { i18n.busy = false; }
  });
  i18n.observer.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: I18N_ATTRS});
 }
 for (const b of document.querySelectorAll('[data-lang-toggle]')) {
  const label = b.querySelector('[data-lang-label]') || b;
  label.textContent = lang === 'zh' ? 'EN' : '中文';
  b.setAttribute('aria-label', lang === 'zh' ? 'Switch the interface to English' : '切换为中文界面');
  b.setAttribute('aria-pressed', String(lang === 'zh'));
 }
 if (remember) { try { localStorage.setItem('strollane.lang', lang); } catch (e) { /* private mode: the choice lasts for this visit */ } }
 return lang;
}
function toggleLanguage() {
 const next = setLanguage(i18n.lang === 'zh' ? 'en' : 'zh');
 if (next === 'zh' && typeof toast === 'function') toast(I18N_COVERAGE_NOTE);
 return next;
}
function setupI18n() {
 for (const b of document.querySelectorAll('[data-lang-toggle]')) b.addEventListener('click', toggleLanguage);
 let saved = null; try { saved = localStorage.getItem('strollane.lang'); } catch (e) { /* no storage: start in English */ }
 if (saved === 'zh') setLanguage('zh', false);
}
if (typeof window !== 'undefined') {
 Object.assign(window, {setLanguage, toggleLanguage, I18N_ZH, I18N_DIMENSIONS_ZH});
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupI18n); else setupI18n();
}
