/* opening-hours.js: OSM opening_hours evaluated in New York time; unsupported syntax is "unknown", never a guess. */
const assert=require('node:assert/strict'),{isOpenAt}=require('../opening-hours.js');
const T=[['Mo-Fr 09:00-17:00','2026-10-23T10:00:00-04:00',true],['Mo-Fr 09:00-17:00','2026-10-24T10:00:00-04:00',false],['Mo-Fr 09:00-17:00','2026-10-23T18:00:00-04:00',false],
 ['24/7','2026-10-24T03:00:00-04:00',true],['Th-Sa 11:00-16:00; Su 11:00-15:00','2026-10-25T12:00:00-04:00',true],['Th-Sa 11:00-16:00; Su 11:00-15:00','2026-10-26T12:00:00-04:00',false],
 ['Mo-Su 18:00-02:00','2026-10-24T01:00:00-04:00',true],['Mo-Su 18:00-02:00','2026-10-24T03:00:00-04:00',false],['Mo-Fr 08:00-12:00,13:00-18:00','2026-10-23T12:30:00-04:00',false],
 ['sunrise-sunset','2026-10-23T12:00:00-04:00',null],['Mo-Fr 09:00-17:00; Sa off','2026-10-24T10:00:00-04:00',false],['10:00-22:00','2026-10-25T11:00:00-04:00',true],[null,'2026-10-25T11:00:00-04:00',null],
 ...[['2026-11-26T12:00:00-05:00',false],['2026-11-19T12:00:00-05:00',true],['2026-12-25T12:00:00-05:00',false],['2027-01-01T12:00:00-05:00',false]].map(([d,e])=>['10:00-17:00; Fr-Sa 10:00-21:00; We off; Nov Th[4] off; Dec 25 off; Jan 01 off',d,e]),
 ['Jul-Aug Mo-Fr 09:00-17:00','2026-07-15T12:00:00-04:00',null]];
for(const [h,d,exp] of T)assert.equal(isOpenAt(h,new Date(d)),exp,`${h} @ ${d}`);
console.log(`OPENING HOURS PASS: ${T.length} cases (New York time, past-midnight ranges, off-days, dated closures, unknown syntax → null)`);
