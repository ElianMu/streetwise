"""Independent historical complaint-density objective. Never modifies the 12 experience dimensions.
NYPD locations and occurrence dates are source approximations; neither density nor
absence of reports predicts current individual victimization risk.
"""
import array,hashlib,json,math,threading,time
from collections import Counter,OrderedDict
from datetime import date
from .urban_store import connection,manifest

MX=111320*math.cos(math.radians(40.78));MY=110540
CORRIDOR_M=100;GRID_M=200
_cache=OrderedDict();_corridor_cache=OrderedDict();_lock=threading.Lock();_field_build_lock=threading.Lock();_corridor_build_lock=threading.Lock();STATS={'edge_cache_hits':0,'edge_cache_misses':0,'sql_queries':0}

def metadata():return manifest('crime')

def validate(doc,require_coverage=True,require_labels=True):
    if doc is None:return None
    if not isinstance(doc,dict) or set(doc)-{'direction','weight','from','to','offense_types','offense_codes','law_categories'}:raise ValueError('Invalid crime preference fields')
    m=metadata();direction=doc.get('direction');weight=doc.get('weight',90)
    if direction not in ('high','low'):raise ValueError('crime.direction must be high or low; direction is never inverted')
    if type(weight) not in (int,float) or not math.isfinite(weight) or not 0<weight<=100:raise ValueError('crime.weight must be 0 < weight <= 100')
    for field in ('offense_codes','offense_types'):
        value=doc.get(field)
        if value is not None and (not isinstance(value,list) or len(value)>100 or any(not isinstance(x,str) if field=='offense_types' else type(x) not in (str,int) for x in value)):
            raise ValueError('crime.'+field+' must be a bounded list of '+('labels' if field=='offense_types' else 'codes'))
    start=doc.get('from') or m['default_start'];end=doc.get('to') or m['available_end_exclusive']
    try:begin,finish=date.fromisoformat(start),date.fromisoformat(end)
    except (ValueError,TypeError):raise ValueError('Crime dates need YYYY-MM-DD; to is exclusive')
    if begin.isoformat()!=start or finish.isoformat()!=end:raise ValueError('Crime dates need YYYY-MM-DD; to is exclusive')
    if start>=end:raise ValueError('Crime start date must precede exclusive end date')
    if require_coverage and not (m['available_start']<=start<end<=m['available_end_exclusive']):raise ValueError('Crime dates outside indexed interval '+m['available_start']+' to '+m['available_end_exclusive']+' (exclusive)')
    codes=set()
    for value in doc.get('offense_codes') or []:
        if str(value) not in m['offenses']:raise ValueError('Unknown NYPD offense code')
        codes.add(int(value))
    for label in doc.get('offense_types') or []:
        matches=[int(k) for k,names in m['offenses'].items() if label.upper() in [n.upper() for n in names]]
        if not matches and require_labels:raise ValueError('Unknown NYPD offense label: '+str(label)[:80])
        codes.update(matches)
    laws=doc.get('law_categories') or (['FELONY','MISDEMEANOR','VIOLATION'] if codes else ['FELONY','MISDEMEANOR'])
    if not isinstance(laws,list) or not laws or set(laws)-{'FELONY','MISDEMEANOR','VIOLATION'}:raise ValueError('Invalid NYPD law_categories')
    return {'direction':direction,'weight':float(weight),'from':start,'to':end,'offense_codes':sorted(codes),'law_categories':sorted(set(laws)),
        'day_from':begin.toordinal(),'day_to':finish.toordinal()}

def _where(p,prefix=''):
    fields=[prefix+'day>=?',prefix+'day<?',prefix+'law IN ('+','.join('?' for _ in p['law_categories'])+')'];args=[p['day_from'],p['day_to'],*p['law_categories']]
    if p['offense_codes']:fields.append(prefix+'offense IN ('+','.join('?' for _ in p['offense_codes'])+')');args+=p['offense_codes']
    return ' AND '.join(fields),args

def public_preference(p):return {k:p[k] for k in ['direction','weight','from','to','offense_codes','law_categories']}

def _pt_seg(p,a,b):
    ux,uy=b[0]-a[0],b[1]-a[1];ll=ux*ux+uy*uy
    t=max(0,min(1,((p[0]-a[0])*ux+(p[1]-a[1])*uy)/ll)) if ll else 0
    return math.hypot(p[0]-a[0]-t*ux,p[1]-a[1]-t*uy)

def edge_field(net,p):
    # One build per key at a time: concurrent cold requests must not repeat the offline-field query.
    with _field_build_lock:return _edge_field(net,p)

def _edge_field(net,p):
    """200 m daily grids → mean density in nine neighbouring cells at edge samples every 50 m.
    This 600 m neighbourhood is a candidate-search heuristic; final routes use 100 m
    exact published-point corridors and one common normalization scale.
    """
    m=metadata();key=(m['sha256'],net.network_version,p['from'],p['to'],tuple(p['offense_codes']),tuple(p['law_categories']))
    with _lock:
        if key in _cache:STATS['edge_cache_hits']+=1;_cache.move_to_end(key);return _cache[key]
    t=time.perf_counter();where,args=_where(p)
    # Restrict to the actual routing graph bounds instead of loading NYC historical records.
    xs=[c[0] for c in net.nodes.values()];ys=[c[1] for c in net.nodes.values()]
    box=(math.floor(min(xs)*MX/GRID_M)-2,math.floor(max(xs)*MX/GRID_M)+2,math.floor(min(ys)*MY/GRID_M)-2,math.floor(max(ys)*MY/GRID_M)+2)
    with connection('crime') as db:
        rows=db.execute('SELECT gx,gy,sum(n) FROM grid_daily WHERE '+where+' AND gx BETWEEN ? AND ? AND gy BETWEEN ? AND ? GROUP BY gx,gy',args+list(box))
        cells={(x,y):n for x,y,n in rows}
    area=(3*GRID_M/1000)**2
    def density(x,y):
        gx,gy=math.floor(x/GRID_M),math.floor(y/GRID_M)
        return sum(cells.get((gx+dx,gy+dy),0) for dx in (-1,0,1) for dy in (-1,0,1))/area
    values=array.array('f')
    for geom in net.gxy:
        samples=[]
        for a,b in zip(geom,geom[1:]):
            n=max(1,math.ceil(math.dist(a,b)/50))
            samples.extend(density(a[0]+(b[0]-a[0])*(j+.5)/n,a[1]+(b[1]-a[1])*(j+.5)/n) for j in range(n))
        values.append(sum(samples)/len(samples) if samples else 0)
    ordered=sorted(v for v in values if v>0);scale=ordered[min(len(ordered)-1,int(.95*len(ordered)))] if ordered else 1.0
    out={'values':values,'scale':max(scale,1),'query_seconds':round(time.perf_counter()-t,4),'grid_cells':len(cells)}
    with _lock:
        STATS['edge_cache_misses']+=1;STATS['sql_queries']+=1;_cache[key]=out
        while len(_cache)>4:_cache.popitem(last=False)
    return out

def fit(density,direction,scale):
    value=max(0,density)/(max(0,density)+max(scale,1))
    return value if direction=='high' else 1-value

def corridor(coords,p,distance_m):
    key=(metadata()['sha256'],p['from'],p['to'],tuple(p['offense_codes']),tuple(p['law_categories']),distance_m,hashlib.sha256(json.dumps(coords,separators=(',',':')).encode()).digest())
    with _corridor_build_lock:
        with _lock:
            if key in _corridor_cache:
                STATS['corridor_cache_hits']=STATS.get('corridor_cache_hits',0)+1;_corridor_cache.move_to_end(key);return {**_corridor_cache[key],'cache_hit':True,'query_seconds':0.0}
        result=_measure_corridor(coords,p,distance_m)
        with _lock:
            _corridor_cache[key]=result
            while len(_corridor_cache)>64:_corridor_cache.popitem(last=False)
        return {**result,'cache_hit':False}

def _measure_corridor(coords,p,distance_m):
    t=time.perf_counter();line=[(c[0]*MX,c[1]*MY) for c in coords];index={};size=128
    for a,b in zip(line,line[1:]):
        for x in range(math.floor((min(a[0],b[0])-CORRIDOR_M)/size),math.floor((max(a[0],b[0])+CORRIDOR_M)/size)+1):
            for y in range(math.floor((min(a[1],b[1])-CORRIDOR_M)/size),math.floor((max(a[1],b[1])+CORRIDOR_M)/size)+1):index.setdefault((x,y),[]).append((a,b))
    bounds=[min(c[0] for c in line)-CORRIDOR_M,max(c[0] for c in line)+CORRIDOR_M,min(c[1] for c in line)-CORRIDOR_M,max(c[1] for c in line)+CORRIDOR_M]
    where,args=_where(p,'i.');counts=Counter();law=Counter();samples=[];count=0;examined=0
    # Read only occupied corridor cells from physically clustered rows. Broad R*Tree
    # boxes previously caused random primary-key reads across a 200 MB table on Render.
    cells=set()
    for a,b in zip(line,line[1:]):
        for x in range(math.floor((min(a[0],b[0])-CORRIDOR_M)/GRID_M),math.floor((max(a[0],b[0])+CORRIDOR_M)/GRID_M)+1):
            for y in range(math.floor((min(a[1],b[1])-CORRIDOR_M)/GRID_M),math.floor((max(a[1],b[1])+CORRIDOR_M)/GRID_M)+1):cells.add((x,y))
    ordered=sorted(cells);queries=0
    with connection('crime') as db:
        for offset in range(0,len(ordered),200):
            chunk=ordered[offset:offset+200]
            sql='WITH cells(gx,gy) AS (VALUES '+','.join('(?,?)' for _ in chunk)+') SELECT i.id,i.offense,i.law,i.x,i.y FROM cells c CROSS JOIN corridor_points i WHERE i.gx=c.gx AND i.gy=c.gy AND '+where
            cursor=db.execute(sql,[v for cell in chunk for v in cell]+args);queries+=1
            for pid,offense,kind,x,y in cursor:
                examined+=1
                parts=index.get((math.floor(x/size),math.floor(y/size)),())
                if parts and min(_pt_seg((x,y),a,b) for a,b in parts)<=CORRIDOR_M:
                    count+=1;counts[str(offense)]+=1;law[kind]+=1
                    if len(samples)<8:samples.append(str(pid))
    with _lock:STATS['sql_queries']+=queries
    km=distance_m/1000;linear=count/km if km else None
    # Nominal strip area, not an exact union of the buffered polyline; loops/endcaps differ.
    nominal_area=km*2*CORRIDOR_M/1000
    m=metadata()
    return {'metric':'Historical Reported Complaint Density','count':count,'reported_incidents_per_route_km':round(linear,3) if linear is not None else None,
        'nominal_corridor_incidents_per_km2':round(count/nominal_area,3) if nominal_area else None,'nominal_area_km2':round(nominal_area,5),
        'area_method':'length × 2 × corridor width; not a polygon-union area. Primary measure is unique complaints per route kilometre.',
        'corridor_m':CORRIDOR_M,'from':p['from'],'to_exclusive':p['to'],'offense_codes':p['offense_codes'],'law_categories':p['law_categories'],
        'by_offense':dict(counts),'by_law_category':dict(law),'sample_source_complaint_ids':samples,'source_urls':[s['url'] for s in m['sources']],
        'publisher_updated_at':[s['publisher_updated_at'] for s in m['sources']],'snapshot':m['sha256'],'coordinate_accuracy':'NYPD published approximate/block-level coordinates; not independently surveyed',
        'limitations':m['limitations'],'query_seconds':round(time.perf_counter()-t,4),'examined_points':examined,'density_is_not_crime_rate':True}

def apply(route,p,field,core_weights=None):
    metrics=corridor(route['geometry']['coordinates'],p,route['distance_m']);route.setdefault('independent_metrics',{})['crime']=metrics
    # Convert fixed-width linear density to a nominal area density for the same fixed scale.
    density=metrics['nominal_corridor_incidents_per_km2'] or 0;match=100*fit(density,p['direction'],field['scale'])
    ps=route['personalized_score'];weight=sum(w for w,_ in (core_weights or {}).values());cw=p['weight']
    combined=(ps['weighted_experience']*weight+match*cw)/(weight+cw)
    ps['independent_components']={'crime':{'weight':cw,'direction':p['direction'],'match':round(match,3),'normalization':'density / (density + fixed graph p95 neighbourhood density); reverse for low. No hard clipping.','scale_incidents_per_km2':field['scale']}}
    ps['objective_match']=round(combined,3);ps['preferences_expressed']=True
    ps['utility']=round(combined-ps['travel_cost_penalty']-ps.get('weather_adjustment',0),3)
    ps['formula']='Weighted core experience and independent complaint-density fit − detour penalty − weather adjustment'

def map_cells(bounds,p,zoom=13,limit=1800):
    if len(bounds)!=4 or not (-74.3<=bounds[0]<bounds[2]<=-73.68 and 40.45<=bounds[1]<bounds[3]<=40.95):raise ValueError('Crime map bounds must be within NYC')
    size=200 if zoom>=15 else 400 if zoom>=13 else 800
    b=(bounds[0]*MX,bounds[1]*MY,bounds[2]*MX,bounds[3]*MY);where,args=_where(p)
    with connection('crime') as db:
        # Server-side aggregate; historical incidents never become a giant browser GeoJSON.
        factor=size/GRID_M
        rows=list(db.execute('SELECT CAST(floor(gx/?) AS INTEGER),CAST(floor(gy/?) AS INTEGER),sum(n) FROM grid_daily WHERE gx BETWEEN ? AND ? AND gy BETWEEN ? AND ? AND '+where+' GROUP BY 1,2 ORDER BY 3 DESC LIMIT ?', [factor,factor,math.floor(b[0]/size)*factor,(math.floor(b[2]/size)+1)*factor-1,math.floor(b[1]/size)*factor,(math.floor(b[3]/size)+1)*factor-1]+args+[limit+1]))
    clipped=len(rows)>limit;features=[]
    for x,y,n in rows[:limit]:
        west,south,east,north=x*size/MX,y*size/MY,(x+1)*size/MX,(y+1)*size/MY
        features.append({'type':'Feature','id':str(x)+'_'+str(y),'properties':{'feature_id':str(x)+'_'+str(y),'count':n,'density_per_km2':round(n/(size/1000)**2,2),'cell_m':size,'from':p['from'],'to_exclusive':p['to'],'source':'NYPD reported complaints','approximate_locations':True},'geometry':{'type':'Polygon','coordinates':[[[west,south],[east,south],[east,north],[west,north],[west,south]]]}})
    return {'type':'FeatureCollection','features':features,'metadata':{'truncated':clipped,'max_cells':limit,'cell_m':size,'from':p['from'],'to_exclusive':p['to'],'offense_codes':p['offense_codes'],'law_categories':p['law_categories'],'snapshot':metadata()['sha256'],'note':'Whole aggregate cells intersecting the query box, not partial-cell counts; approximate reported locations, not current personal risk. Zoom in if cells are truncated.'}}
