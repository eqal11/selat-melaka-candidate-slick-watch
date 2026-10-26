import {useMemo} from 'react';
import {ResponsiveContainer,LineChart,Line,XAxis,YAxis,Tooltip,CartesianGrid,Legend} from 'recharts';

type Entry={id:string;zone:string;acquisition_time:string;count:number;total_area_km2:number;data_label:string};
function weekKey(dateString:string){const date=new Date(dateString);date.setUTCHours(0,0,0,0);const weekday=date.getUTCDay()||7;date.setUTCDate(date.getUTCDate()-weekday+1);return date.toISOString().slice(0,10)}
export default function HistoryChart({entries,zone}:{entries:Entry[];zone:string}){
 const rows=useMemo(()=>{const weeks=new Map<string,{week:string;count:number;area:number}>();for(const entry of entries){if(entry.zone!==zone)continue;const week=weekKey(entry.acquisition_time);const row=weeks.get(week)??{week,count:0,area:0};row.count+=entry.count;row.area+=entry.total_area_km2;weeks.set(week,row)}return [...weeks.values()].sort((a,b)=>a.week.localeCompare(b.week))},[entries,zone]);
 return <section><h2>Archived candidates · weekly · {zone}</h2>{!rows.length?<p>Archive is empty for this zone. No real detections are available.</p>:<><ResponsiveContainer width="100%" height={220}><LineChart data={rows}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="week"/><YAxis yAxisId="count"/><YAxis yAxisId="area" orientation="right"/><Tooltip/><Legend/><Line yAxisId="count" type="monotone" dataKey="count" name="Candidates" stroke="#56d2c4"/><Line yAxisId="area" type="monotone" dataKey="area" name="Area km²" stroke="#ffbd59"/></LineChart></ResponsiveContainer><small>{rows.length} week(s) with archived scene results. Counts are model candidates, not confirmed spills.</small></>}</section>
}
