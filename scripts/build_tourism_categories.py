"""Evidence-backed category catalog. Zero matches means not connected, not 'none exist in NYC'."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
# id, label, existing parent categories, permitted source subtype (None=parent), support limit.
SPECS=[
('famous','Famous attractions',['attractions'],None,None),('historical','Historical landmarks',['historic','historic_lpc'],None,None),
('historic_districts','Historic districts',[],None,'Polygon urban layer only; no verified visitor entrance'),
('architectural','Architectural landmarks',['historic_lpc'],None,None),('museums','Museums',['museums'],['tourism=museum'],None),
('galleries','Art galleries',['museums'],['tourism=gallery'],None),('cultural','Cultural institutions',['culture'],None,None),
('theatres','Theatres',['culture'],['amenity=theatre'],None),('public_art','Public art',['attractions'],['tourism=artwork'],None),
('viewpoints','Scenic viewpoints',['attractions'],['tourism=viewpoint'],None),('observation_decks','Observation decks',[],None,'No explicit supported source subtype'),
('waterfront','Waterfront parks',['parks'],None,'Only official park waterfront flag; not all waterfront attractions'),
('parks','Parks',['parks'],None,None),('gardens','Gardens',['parks'],['leisure=garden','Garden'],None),('seasonal','Seasonal attractions',[],None,'No current seasonal schedule provider'),
('restaurants','Restaurants',['restaurants'],None,None),('cafes','Cafés',['cafes'],None,None),('bakeries','Bakeries',['bakeries'],None,None),
('desserts','Dessert shops',['bakeries'],['amenity=ice_cream','shop=pastry','shop=confectionery'],None),
('specialty_coffee','Specialty coffee',['cafes'],['shop=coffee'],'Coffee-shop tag only, not independently verified specialty quality'),
('local_food','Local food destinations',[],None,'Local distinction is not established by the source'),
('food_markets','Food markets',['groceries'],['amenity=marketplace'],None),('food_halls','Food halls',[],None,'No explicit supported source subtype'),
('casual_dining','Casual dining',[],None,'No authoritative dining-class field'),('fine_dining','Fine dining',[],None,'No authoritative dining-class field'),
('hotels','Hotels',['hotels'],['tourism=hotel'],None),('boutique_hotels','Boutique hotels',[],None,'No verified boutique classification'),
('hostels','Hostels',['hotels'],['tourism=hostel'],None),('apartments','Apartment accommodation',['hotels'],['tourism=apartment'],'OSM listing, not proof of licensed aparthotel status'),
('licensed_accommodation','Other licensed accommodation',[],None,'Tax-lot class is not an accommodation operating licence'),
('shopping_streets','Shopping streets',[],None,'Street geometry is not a verified retail district inventory'),
('shopping_centres','Shopping centres',['shopping'],['shop=mall','shop=department_store'],None),('stores','Independent stores',['shopping'],None,'Independence not verified'),
('markets','Markets',['groceries'],['amenity=marketplace'],None),('entertainment','Entertainment venues',['culture'],None,'Broad culture listing, no event schedules'),
('performance','Live performance venues',['culture'],['amenity=theatre'],'No live performance schedule'),
('restrooms','Public restrooms',['restrooms'],None,None),('pharmacies','Pharmacies',['pharmacies'],None,None),
('supermarkets','Supermarkets',['groceries'],['shop=supermarket'],None),('convenience','Convenience stores',['groceries'],['shop=convenience'],None),
('transit','Transit entrances',[],None,'Urban layer only, not canonical place discovery'),('visitor_centres','Visitor centres',[],None,'No explicit supported source subtype'),
('luggage','Luggage storage',['luggage'],None,None),('medical','Medical facilities',['health'],None,None)]


def main():
 idx=json.loads((ROOT/'data/places/index.json').read_text())
 records=[{**r,'cat':c['id']} for c in idx['categories'] for r in json.loads((ROOT/'data/places'/ (c['id']+'.json')).read_text())['records']]
 records+=json.loads((ROOT/'data/places/citywide.json').read_text())['records']
 rows=[]
 for id,label,cats,subtypes,limit in SPECS:
  matches=[r for r in records if r['cat'] in cats and (not subtypes or r.get('sub') in subtypes) and (id!='waterfront' or r.get('waterfront') is True) and (id!='famous' or (r.get('sl') or 0)>=8)]
  rows.append({'id':id,'label':label,'parent_categories':cats,'source_subtypes':subtypes,'snapshot_records':len(matches),
   'implementation_status':'Partial' if limit and matches else 'Implemented & Tested' if matches else 'Not Implemented',
   'limit':limit,'coverage':'Source snapshots; mostly Manhattan, official parks/restrooms NYC citywide. No live completeness guarantee.'})
 (ROOT/'data/places/category_catalog.json').write_text(json.dumps({'categories':rows,'note':'Counts are source records, not unique operating businesses or guaranteed visitor-accessible parks. Unconnected categories are not evidence of absence.'},indent=1))
 print(len(rows),'tourism categories;',sum(bool(r['snapshot_records']) for r in rows),'have supported source records')
if __name__=='__main__':main()
