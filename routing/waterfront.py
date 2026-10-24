"""Source-backed water proximity, kept separate from Scenic & Visual's existing definition."""
import gzip,json,math,pathlib,threading
ROOT=pathlib.Path(__file__).resolve().parents[1];_data=None;_lock=threading.Lock()
def data(net=None):
 global _data
 with _lock:
  if _data is None:
   with gzip.open(ROOT/'data/pedestrian/waterfront-features.json.gz','rt') as f:_data=json.load(f)
 if net and _data['metadata']['network_version']!=net.network_version:raise RuntimeError('Waterfront features need rebuilding for this network')
 return _data

def validate(p):
 if p is None:return None
 if not isinstance(p,dict) or set(p)-{'direction','weight'} or p.get('direction') not in ('high','low'):raise ValueError('Waterfront preference needs direction high or low')
 w=p.get('weight') if p.get('weight') is not None else 90
 if type(w) not in (int,float) or not math.isfinite(w) or not 0<w<=100:raise ValueError('Invalid waterfront weight')
 return {'direction':p['direction'],'weight':w}

def apply(route,p,net,core_weights):
 d=data(net);length=route['distance_m'] or 1
 share=sum(e['traversed_length_m']*d['within_100m_share'][e['geometry_index']] for e in route['edges'])/length
 match=100*(share if p['direction']=='high' else 1-share)
 route.setdefault('independent_metrics',{})['waterfront']={'within_100m_share':round(share,4),'near_water_length_m':round(share*length,1),'source_url':d['metadata']['source']['source_url'],'publisher_updated_at':d['metadata']['source']['publisher_updated_at'],'method':d['metadata']['method'],'limitations':d['metadata']['limitations'],'direction':p['direction']}
 ps=route['personalized_score'];parts=ps.setdefault('independent_components',{});parts['waterfront']={'weight':p['weight'],'direction':p['direction'],'match':round(match,4)}
 core=sum(w for w,_ in core_weights.values());total=core+sum(v['weight'] for v in parts.values());combined=(ps['weighted_experience']*core+sum(v['weight']*v['match'] for v in parts.values()))/total
 ps.update(utility=round(combined-ps['travel_cost_penalty']-ps.get('weather_adjustment',0),3),objective_match=round(combined,3),preferences_expressed=True,formula='Weighted core experience and independent objective matches − detour penalty − weather adjustment')
