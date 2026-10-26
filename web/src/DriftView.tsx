import {useEffect,useMemo,useState} from 'react';
import DeckGL from '@deck.gl/react';
import {PathLayer,PolygonLayer,ScatterplotLayer} from '@deck.gl/layers';

type Drift={candidate_id:string;track:{coordinates:number[][]};envelopes:Record<string,{coordinates:number[][][]}>;flags:string[]};
export default function DriftView({result}:{result:any}){
 const [hours,setHours]=useState('6');
 const [frame,setFrame]=useState(0);
 useEffect(()=>{const timer=window.setInterval(()=>setFrame(value=>value+1),700);return()=>window.clearInterval(timer)},[]);
 const drifts:Drift[]=result?.drift??[];
 const layers=useMemo(()=>drifts.flatMap((drift)=>{const path=drift.track.coordinates;const envelope=drift.envelopes[hours]?.coordinates?.[0]??[];const index=Math.min(path.length-1,Math.floor(frame%Math.max(1,Math.floor(path.length*Number(hours)/24))));return [
  new PolygonLayer({id:'envelope-'+drift.candidate_id,data:envelope.length?[{polygon:envelope}]:[],getPolygon:(item:any)=>item.polygon,filled:true,stroked:true,getFillColor:[47,197,177,38],getLineColor:[112,221,202,180],lineWidthMinPixels:1}),
  new PathLayer({id:'track-'+drift.candidate_id,data:[{path}],getPath:(item:any)=>item.path,getColor:[255,188,89,230],widthMinPixels:2}),
  new ScatterplotLayer({id:'particle-'+drift.candidate_id,data:path.length?[{position:path[index]}]:[],getPosition:(item:any)=>item.position,getRadius:90,radiusMinPixels:5,getFillColor:[255,239,170,255],getLineColor:[255,255,255,230],lineWidthMinPixels:1})
 ]}),[drifts,hours,frame]);
 if(!result)return <p>Run analysis to see drift scenarios.</p>;
 return <section><h2>First-order drift estimate</h2><p>Not a full Lagrangian model. Envelope samples windage 2–4% and direction ±20°; a moving marker animates the forecast track.</p><div>{['6','12','24'].map(value=><button key={value} onClick={()=>setHours(value)} aria-pressed={hours===value}>{value} h</button>)}</div><div className="drift-map"><DeckGL initialViewState={{longitude:102,latitude:3.2,zoom:5.2,pitch:0,bearing:0}} controller={true} layers={layers}/></div>{drifts.map(drift=><div className="card" key={drift.candidate_id}><b>{drift.candidate_id}</b><p>Forecast vertices: {drift.track.coordinates.length}; {hours} h envelope shown</p><small>{drift.flags.join(', ')||'Forcing available'}</small></div>)}</section>
}
