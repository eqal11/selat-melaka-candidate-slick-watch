import { useState } from 'react';

function geometryRings(geometry: any): number[][][] {
  if (geometry?.type === 'Polygon') return [geometry.coordinates?.[0] ?? []];
  if (geometry?.type === 'MultiPolygon') return (geometry.coordinates ?? []).map((polygon: any[]) => polygon[0] ?? []);
  return [];
}

function CaseScene({ result }: { result: any }) {
  const [variant, setVariant] = useState<'raw' | 'filtered'>('filtered');
  const bounds = result.preview_bounds as [number, number, number, number] | undefined;
  const candidates = (result.candidates ?? []).filter((feature: any) => feature.properties?.label === 'candidate');
  const imageUrl = variant === 'raw' ? result.preview_raw_url : result.preview_filtered_url;
  return <section className="case-scene">
    <div className="case-scene-heading">
      <b>REAL Sentinel-1 · {result.satellite} · {result.scene_id}</b>
      <small>{result.acquisition_time_utc} UTC · {result.orbit_direction} · {result.polarization?.join(', ')} · <a href={result.stac_href} target="_blank" rel="noreferrer">STAC item ↗</a></small>
    </div>
    {bounds && imageUrl && <div className="case-preview">
      <img src={imageUrl} loading="lazy" alt={`${variant} Sentinel-1 SAR in dB`} />
      <svg viewBox="0 0 600 600" role="img" aria-label="Detector candidate slick polygons aligned over the Sentinel-1 image">
        {candidates.flatMap((feature: any) => geometryRings(feature.geometry).map((ring, index) => {
          const [west, south, east, north] = bounds;
          const points = ring.map(([lon, lat]) => `${(lon - west) / (east - west) * 600},${(north - lat) / (north - south) * 600}`).join(' ');
          return <polygon key={`${feature.properties.id}-${index}`} points={points} />;
        }))}
      </svg>
    </div>}
    <div className="case-controls" role="group" aria-label="SAR preview type">
      <button type="button" aria-pressed={variant === 'raw'} onClick={() => setVariant('raw')}>Raw SAR</button>
      <button type="button" aria-pressed={variant === 'filtered'} onClick={() => setVariant('filtered')}>Filtered SAR</button>
      <span>Fixed stretch −25 to 0 dB · red outline = candidate slick</span>
    </div>
    <div className="case-metrics">
      <span><b>{result.candidate_count}</b> candidate slick(s) · {Number(result.total_candidate_area_km2 ?? 0).toFixed(3)} km²</span>
      <span>Wind: {result.wind_speed_ms == null ? 'unavailable' : `${Number(result.wind_speed_ms).toFixed(1)} m/s`} · {result.conditions?.wind_source} · {result.conditions?.time} UTC</span>
      <span>Valid pixels: {Number(result.qa?.valid_pixel_percent ?? 0).toFixed(1)}%</span>
    </div>
    {result.candidate_count === 0 && <p><b>No candidate slicks detected in this scene.</b></p>}
    <details><summary>Funnel, QA and candidate details</summary>
      <pre>{JSON.stringify({ funnel: result.funnel, flags: result.qa?.flags, candidates: candidates.map((item: any) => ({ id: item.properties.id, area_km2: item.properties.area_km2, score: item.properties.score, band: item.properties.band, distance_km: result.candidate_distances_to_reported_location_km?.find((d: any) => d.candidate_id === item.properties.id)?.distance_km })) }, null, 2)}</pre>
    </details>
  </section>;
}

export default function ValidationCases({ register }: { register: any }) {
  return <>
    <h2>Validation cases</h2>
    <p>Evidence register for research review. Every displayed result links to a real Sentinel-1 item. A candidate slick is not a confirmed spill.</p>
    {register?.error ? <p role="alert">Case register unavailable: {register.error}</p> : <>
      <p>{register?.scene_search_note}</p>
      {(register?.cases ?? []).map((item: any) => <article className="card validation-case" key={item.id}>
        <b>{item.category === 'natural_seep' ? 'Natural seep' : 'Documented spill'} · {item.id}</b>
        <div>{item.location}</div>
        {item.incident_date && <small>Incident date: {item.incident_date}{item.extent_observation_date ? ` · extent observation: ${item.extent_observation_date}` : ''}</small>}
        <p>{item.reported_extent}</p>
        {item.location_coordinates && <small>Published/source coordinates [lon, lat]: {item.location_coordinates.join(', ')} · {item.coordinate_basis}</small>}
        <div><b>Search status:</b> {item.run_status ?? item.scene_search?.status ?? 'not yet run'}</div>
        {(item.processing_results ?? []).filter((result: any) => result.status === 'processed').map((result: any) => <CaseScene key={result.scene_id} result={result} />)}
        {(item.processing_results ?? []).filter((result: any) => result.status !== 'processed').map((result: any) => <div key={result.scene_id} role="status"><b>{result.scene_id}:</b> {result.reason ?? result.error ?? result.status}</div>)}
        {(!item.processing_results || item.processing_results.length === 0) && <div><b>Detector:</b> Not run; no detection outcome is claimed.</div>}
        {item.scene_search?.catalog_errors?.map((error: any, index: number) => <small key={index}>Catalog issue · {error.catalog}: {error.error}</small>)}
        <div className="case-sources"><b>Sources:</b> {(item.sources ?? []).map((source: any) => <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.organization} ↗</a>)}</div>
      </article>)}
    </>}
  </>;
}
