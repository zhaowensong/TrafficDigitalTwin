// ==========================================
// 1. Config (Focused on Shanghai)
// ==========================================
const CONFIG = {
    MAPBOX_TOKEN: 'YOUR_MAPBOX_TOKEN_HERE',
    API_BASE: 'http://127.0.0.1:5000/api', // Local
    // API_BASE: '/api',  // Online
    
    // Shanghai City Center
    DEFAULT_CENTER: [121.4737, 31.2304], 
    DEFAULT_ZOOM: 10.5,

    // Shanghai Coordinate Bounds [Southwest, Northeast]
    SHANGHAI_BOUNDS: [
        [120.80, 30.60], // Southwest
        [122.50, 31.90]  // Northeast
    ]
};

// ==========================================
// 2. Globals
// ==========================================
let chartInstance = null;
let predictionChartInstance = null; 
let currentMarker = null;
let mapInstance = null;
let globalStationData = [];
let animationFrameId = null;
let isPredictionMode = false; 
let predictionMarker = null; 
let optimalMarker = null;     
let energyMainChartInstance = null;
let energyDeltaChartInstance = null;
let isControlMode = false;

// ==========================================
// 3. API Logic
// ==========================================
async function fetchLocations() {
    console.log("Requesting backend data...");
    const res = await fetch(`${CONFIG.API_BASE}/stations/locations`);
    if (!res.ok) throw new Error(`API Error: ${res.status}`);
    return await res.json();
}

async function fetchStationDetail(id) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/stations/detail/${id}`);
        return await res.json();
    } catch (e) {
        console.error("Fetch Detail Error:", e);
        return null;
    }
}

// Fetch AI Prediction Data
async function fetchPrediction(id) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/predict/${id}?t=${Date.now()}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        return data;
    } catch (e) {
        console.error("Prediction API Error:", e);
        alert("Prediction failed: " + e.message);
        return null;
    }
}

function loadSatellitePatch(lng, lat) {
    // Logic for loading static satellite imagery patch
    const img = document.getElementById('satellite-patch');
    const placeholder = document.getElementById('sat-placeholder');
    if(!img) return;
    
    img.style.display = 'none'; 
    placeholder.style.display = 'flex'; 
    placeholder.innerHTML = '<p>Loading...</p>';
    
    img.src = `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/${lng},${lat},16,0,0/320x200?access_token=${CONFIG.MAPBOX_TOKEN}`;
    img.onload = () => { img.style.display = 'block'; placeholder.style.display = 'none'; };
}

// ==========================================
// 4. Chart Logic (Normal & Prediction)
// ==========================================
function renderChart(recordData) {
    const ctx = document.getElementById('energyChart').getContext('2d');
    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: { 
            labels: recordData.map((_, i) => i), 
            datasets: [
                { 
                    label: 'Traffic', data: recordData, 
                    borderColor: '#00cec9', backgroundColor: 'rgba(0, 206, 201, 0.1)', 
                    borderWidth: 1.5, fill: true, pointRadius: 0, tension: 0.3 
                },
                { 
                    label: 'Current', data: [], type: 'scatter', 
                    pointRadius: 6, pointBackgroundColor: '#ffffff', 
                    pointBorderColor: '#e84393', pointBorderWidth: 3 
                }
            ] 
        },
        options: { 
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: false } }, 
            scales: { x: { display: false }, y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', font: {size: 10} } } } 
        }
    });
}

function updateChartCursor(timeIndex) {
    if (chartInstance && chartInstance.data.datasets[0].data.length > timeIndex) {
        const yValue = chartInstance.data.datasets[0].data[timeIndex];
        chartInstance.data.datasets[1].data = [{x: timeIndex, y: yValue}];
        chartInstance.update('none');
    }
}

// Render AI Prediction Comparison Chart
function renderPredictionChart(realData, predData) {
    const canvas = document.getElementById('predictionChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    if (predictionChartInstance) {
        predictionChartInstance.destroy();
    }

    // Generate X-axis labels (e.g., H0, H1...)
    const labels = realData.map((_, i) => `H${i}`);

    predictionChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Real Traffic',
                    data: realData,
                    borderColor: 'rgba(0, 206, 201, 0.8)', // Cyan
                    backgroundColor: 'rgba(0, 206, 201, 0.1)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'AI Prediction',
                    data: predData,
                    borderColor: '#f39c12', // Orange
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [5, 5], // Dashed line effect
                    pointRadius: 0,
                    fill: false,
                    tension: 0.3 
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false, // Tooltip shows both values simultaneously
            },
            plugins: {
                legend: { 
                    display: true, 
                    labels: { color: '#e0e0e0', font: { size: 10 } }
                }
            },
            scales: {
                x: { 
                    display: true, 
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#64748b', font: {size: 9}, maxTicksLimit: 14 } 
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.1)' },
                    ticks: { color: '#888', font: {size: 10} },
                    beginAtZero: true
                }
            }
        }
    });
}

function setupControlMode(map) {
    const controlBtn = document.getElementById('control-toggle');
    const controlPanel = document.getElementById('energy-control-panel');
    const closeControlBtn = document.getElementById('close-control-btn');

    if (!controlBtn) return;

    controlBtn.addEventListener('click', () => {
        const pitch = map.getPitch();
        if (pitch > 10) {
            alert("Energy Control Mode is only available in 2D View. Please switch to 2D first.");
            return;
        }

        if (!isControlMode && isPredictionMode) {
            document.getElementById('predict-toggle').click();
        }

        isControlMode = !isControlMode;
        if (isControlMode) {
            controlBtn.classList.add('predict-on');
            controlBtn.innerHTML = '<span class="icon">🔋</span> Control: ON';
            
            controlPanel.classList.add('active');
            
            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) rightBtn.classList.add('active');
            
            map.getCanvas().style.cursor = 'crosshair'; 
        } else {
            controlBtn.classList.remove('predict-on');
            controlBtn.innerHTML = '<span class="icon">🔋</span> Energy Control';
            
            controlPanel.classList.remove('active');
            controlPanel.classList.remove('collapsed');
            
            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) {
                rightBtn.innerText = '▶';
                rightBtn.classList.remove('active'); 
                rightBtn.classList.remove('collapsed');
            }
            
            map.getCanvas().style.cursor = '';
            clearPredictionExtras(map); 
        }
    });

    if (closeControlBtn) closeControlBtn.addEventListener('click', () => controlBtn.click());
}

function renderEnergyControlCharts(realData, genData, decisionData, deltaData) {
    const labels = realData.map((_, i) => `H${i}`);
    const ctxMain = document.getElementById('energyControlMainChart').getContext('2d');
    if (energyMainChartInstance) energyMainChartInstance.destroy();

    energyMainChartInstance = new Chart(ctxMain, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'Real Traffic', data: realData, borderColor: '#00cec9', borderWidth: 1.5, pointRadius: 0, tension: 0.2 },
                { label: 'AI Prediction', data: genData, borderColor: '#f39c12', borderDash: [5, 5], borderWidth: 1.2, pointRadius: 0, tension: 0.2, alpha: 0.7 },
                { label: 'Control Target', data: decisionData, borderColor: '#ffffff', borderDash: [2, 2], borderWidth: 2, pointRadius: 0, tension: 0.2 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: true, labels: { color: '#e0e0e0', font: { size: 10 } } } },
            scales: {
                x: { display: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', maxTicksLimit: 14 } },
                y: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#888' }, beginAtZero: true }
            }
        }
    });

    const ctxDelta = document.getElementById('energyControlDeltaChart').getContext('2d');
    if (energyDeltaChartInstance) energyDeltaChartInstance.destroy();

    const barColors = deltaData.map(val => val < 0 ? '#2ecc71' : '#ff4757');
    const borderColors = deltaData.map(val => val < 0 ? '#2ecc71' : '#ff4757');

    energyDeltaChartInstance = new Chart(ctxDelta, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{ 
                label: 'Delta', 
                data: deltaData, 
                backgroundColor: barColors, 
                borderColor: borderColors, 
                borderWidth: 1,
                barPercentage: 1.0,
                categoryPercentage: 1.0
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false } },
            scales: { x: { display: false }, y: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#888' } } }
        }
    });
}


// ==========================================
// 5. Map Manager 
// ==========================================
function initMap() {
    mapboxgl.accessToken = CONFIG.MAPBOX_TOKEN;
    mapInstance = new mapboxgl.Map({
        container: 'map',
        style: 'mapbox://styles/mapbox/satellite-streets-v12',
        center: CONFIG.DEFAULT_CENTER,
        zoom: CONFIG.DEFAULT_ZOOM,
        pitch: 60, 
        bearing: -15, 
        antialias: true,
        maxBounds: CONFIG.SHANGHAI_BOUNDS, 
        minZoom: 9 
    });
    mapInstance.addControl(new mapboxgl.NavigationControl(), 'top-right');
    return mapInstance;
}

function setupMapEnvironment(map) {
    map.addSource('mapbox-dem', { 
        'type': 'raster-dem', 
        'url': 'mapbox://mapbox.mapbox-terrain-dem-v1', 
        'tileSize': 512, 
        'maxzoom': 14 });
        
    map.setTerrain({ 'source': 'mapbox-dem', 
        'exaggeration': 1.5 });
    
    map.addLayer({ 
        'id': 'sky', 
        'type': 'sky', 
        'paint': { 'sky-type': 'atmosphere', 'sky-atmosphere-sun': [0.0, 0.0], 'sky-atmosphere-sun-intensity': 15 } 
    });
    
    if (map.setFog) {
        map.setFog({ 'range': [0.5, 10], 
            'color': '#240b36', 
            'horizon-blend': 0.1, 
            'high-color': '#0f172a', 
            'space-color': '#000000', 
            'star-intensity': 0.6 });
    }

    const labelLayerId = map.getStyle().layers.find(l => l.type === 'symbol' && l.layout['text-field']).id;
    if (!map.getLayer('3d-buildings')) {
        map.addLayer({
            'id': '3d-buildings', 'source': 'composite', 
            'source-layer': 'building', 'filter': ['==', 'extrude', 'true'], 
            'type': 'fill-extrusion', 'minzoom': 11,
            'paint': {
                'fill-extrusion-color': ['interpolate', ['linear'], ['get', 'height'], 0, '#0f0c29', 30, '#1e2a4a', 200, '#4b6cb7'],
                'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-base': ['get', 'min_height'], 'fill-extrusion-opacity': 0.6
            }
        }, labelLayerId);
    }
}

function updateGeoJSONData(map, stations, mode = 'avg', timeIndex = 0) {
    const pointFeatures = [];
    const polygonFeatures = [];
    const r = 0.00025; // Marker radius

    stations.forEach(s => {
        const lng = s.loc[0], lat = s.loc[1];
        // Note: vals removed from API response to reduce size, use val_h (avg) for all modes
        let valH = s.val_h || 0;
        let valC = (s.val_c !== undefined) ? s.val_c : 0;
        
        const props = { id: s.id, load_avg: valH, load_std: valC };
        
        pointFeatures.push({ type: 'Feature', geometry: { 
            type: 'Point', coordinates: [lng, lat] }, properties: props });
        polygonFeatures.push({ type: 'Feature', geometry: { 
            type: 'Polygon', coordinates: [[ [lng-r, lat-r], [lng+r, lat-r], [lng+r, lat+r], [lng-r, lat+r], [lng-r, lat-r] ]] }, properties: props });
    });

    if (map.getSource('stations-points')) {
        map.getSource('stations-points').setData({ 
            type: 'FeatureCollection', 
            features: pointFeatures });

        map.getSource('stations-polygons').setData({ 
            type: 'FeatureCollection', 
            features: polygonFeatures });
    }
    return { points: { type: 'FeatureCollection', features: pointFeatures }, polys: { type: 'FeatureCollection', features: polygonFeatures } };
}

function addStationLayers(map, geoData, statsLoad, statsColor) {
    map.addSource('stations-points', { type: 'geojson', data: geoData.points });
    map.addSource('stations-polygons', { type: 'geojson', data: geoData.polys });

    map.addLayer({
        id: 'stations-heatmap', type: 'heatmap', source: 'stations-points', maxzoom: 14,
        paint: {
            'heatmap-weight': ['interpolate', ['linear'], ['get', 'load_avg'], statsLoad.min, 0, statsLoad.max, 1],
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1, 13, 3],
            'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', 0.2, '#0984e3', 0.4, '#00cec9', 0.6, '#a29bfe', 0.8, '#fd79a8', 1, '#ffffff'],
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 2, 13, 25],
            'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 12, 1, 14, 0]
        }
    });

    map.addLayer({
        id: 'stations-2d-dots', type: 'circle', source: 'stations-points', minzoom: 12,
        paint: {
            'circle-radius': 3,
            'circle-color': ['step', ['get', 'load_std'], '#1e1e2e', statsColor.t1, '#0984e3', statsColor.t2, '#00cec9', statsColor.t3, '#fd79a8', statsColor.t4, '#e84393'],
            'circle-stroke-width': 1, 'circle-stroke-color': '#fff', 'circle-opacity': 0.8
        }
    });

    map.addLayer({
        id: 'stations-3d-pillars', type: 'fill-extrusion', source: 'stations-polygons', minzoom: 12,
        paint: {
            'fill-extrusion-color': ['step', ['get', 'load_std'], '#1e1e2e', statsColor.t1, '#0984e3', statsColor.t2, '#00cec9', statsColor.t3, '#fd79a8', statsColor.t4, '#e84393'],
            'fill-extrusion-height': ['interpolate', ['linear'], ['get', 'load_avg'], 0, 0, statsLoad.min, 5, statsLoad.max, 300],
            'fill-extrusion-opacity': 0.7
        }
    });

    map.addLayer({ id: 'stations-hitbox', type: 'circle', source: 'stations-points', 
        paint: { 'circle-radius': 10, 'circle-color': 'transparent', 'circle-opacity': 0 } });
}

// ==========================================
// 6. Map Interactions 
// ==========================================
function setupInteraction(map) {
    const popup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, className: 'cyber-popup' });

    map.on('mouseenter', 'stations-hitbox', (e) => {
        map.getCanvas().style.cursor = 'pointer';
        if (isPredictionMode || isControlMode) return; 

        const props = e.features[0].properties;
        const coordinates = e.features[0].geometry.coordinates.slice();
        
        while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) { coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360; }
        
        popup.setLngLat(coordinates)
            .setHTML(`
                <div style="font-weight:bold; color:#fff; border-bottom:1px solid #444; padding-bottom:2px; margin-bottom:2px;">Station ${props.id}</div>
                <div style="color:#00cec9;">Load: <span style="color:#fff;">${props.load_avg.toFixed(2)}</span></div>
                <div style="color:#fd79a8;">Stability: <span style="color:#fff;">${props.load_std.toFixed(4)}</span></div>
            `).addTo(map);
    });

    map.on('mouseleave', 'stations-hitbox', () => { 
        if (!isPredictionMode && !isControlMode) map.getCanvas().style.cursor = ''; 
        popup.remove(); 
    });

    // Core Interaction Logic
    map.on('click', 'stations-hitbox', async (e) => {
        const coordinates = e.features[0].geometry.coordinates.slice();
        const id = e.features[0].properties.id;


        if (isPredictionMode || isControlMode) {
            
            if (optimalMarker) { optimalMarker.remove(); optimalMarker = null; }
            
            if (predictionMarker) { predictionMarker.remove(); }
            const pinColor = isPredictionMode ? '#f39c12' : '#2ecc71'; 
            predictionMarker = new mapboxgl.Marker({ color: pinColor })
                .setLngLat(coordinates)
                .addTo(map);

            if (isPredictionMode) {
                updatePredictionGrid(map, coordinates[0], coordinates[1]);
            } else {
                if (map.getSource('pred-grid-source')) {
                    map.getSource('pred-grid-source').setData({ type: 'FeatureCollection', features: [] });
                }
            }

            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) rightBtn.classList.add('active');

            if (isPredictionMode) {
                document.getElementById('prediction-panel').classList.add('active');
                if (document.getElementById('site-map-container')) document.getElementById('site-map-container').style.display = 'none';
                if (predictionChartInstance) { predictionChartInstance.destroy(); predictionChartInstance = null; }

                document.getElementById('pred-station-id').innerHTML = `
                    ${id}
                    <span style="display: block; font-size: 14px; color: #00cec9; margin-top: 10px; font-family: 'Courier New', monospace; font-weight: normal;">
                        > SYSTEM READY : Inference in progress...<br>
                        <span style="color: #00cec9; font-size: 12px;">[Cloud resource limited, please standby]</span>
                    </span>
                `;
            }
            
            if (isControlMode) {
                document.getElementById('energy-control-panel').classList.add('active');
                
                const explanationBox = document.getElementById('energy-explanation');
                if (explanationBox) explanationBox.style.display = 'none';

                document.getElementById('energy-station-id').innerHTML = `
                    ${id}
                    <span style="display: block; font-size: 14px; color: #2ecc71; margin-top: 10px; font-family: 'Courier New', monospace; font-weight: normal;">
                        > SYSTEM READY : Inference in progress...<br>
                        <span style="color: #2ecc71; font-size: 12px;">[Cloud resource limited, please standby]</span>
                    </span>
                `;

                if (energyMainChartInstance) { 
                    energyMainChartInstance.destroy(); 
                    energyMainChartInstance = null; 
                }
                if (energyDeltaChartInstance) { 
                    energyDeltaChartInstance.destroy(); 
                    energyDeltaChartInstance = null; 
                }
            }

            const result = await fetchPrediction(id);
            
            if(result && result.status === "success") {
                
                if (isPredictionMode) {
                    document.getElementById('pred-station-id').innerText = id; 
                    renderPredictionChart(result.real, result.prediction);
                    
                    const siteMapContainer = document.getElementById('site-map-container');
                    const siteMapImg = document.getElementById('site-map-img');
                    if (result.site_map_b64 && siteMapContainer && siteMapImg) {
                        siteMapImg.src = `data:image/png;base64,${result.site_map_b64}`;
                        siteMapContainer.style.display = 'block'; 
                        
                        const explanationBox = document.getElementById('site-explanation');
                        if (explanationBox && result.explanation) {
                            explanationBox.style.display = 'block';
                            explanationBox.innerHTML = `<strong>> SYSTEM LOG: AI DECISION</strong><br><span id="typewriter-text"></span><span class="cursor" style="animation: blink 1s step-end infinite;">_</span>`;
                            const textTarget = document.getElementById('typewriter-text');
                            const fullText = result.explanation;
                            let charIndex = 0;
                            function typeWriter() {
                                if (charIndex < fullText.length) {
                                    textTarget.innerHTML += fullText.charAt(charIndex);
                                    charIndex++;
                                    setTimeout(typeWriter, Math.random() * 20 + 10);
                                }
                            }
                            typeWriter();
                        }

                        if (result.best_loc) {
                            if (optimalMarker) { 
                                optimalMarker.remove(); 
                                optimalMarker = null; 
                            }
                            if (predictionMarker) { predictionMarker.remove(); predictionMarker = null; }
                            const customPin = document.createElement('div');
                            customPin.className = 'optimal-pulse-pin';
                            optimalMarker = new mapboxgl.Marker(customPin) 
                                .setLngLat(result.best_loc)
                                .setPopup(new mapboxgl.Popup({ offset: 25, closeButton: false, className: 'cyber-popup' })
                                .setHTML('<div style="color:#2ecc71; font-weight:bold; font-size:14px;">🌟 Best LSI Site</div>'))
                                .addTo(map);
                            optimalMarker.togglePopup();
                            map.flyTo({ center: result.best_loc, zoom: 16.5, speed: 1.2 });
                        }
                    }
                }

                if (isControlMode && result.energy_control) {
                    document.getElementById('energy-station-id').innerText = id;
                    renderEnergyControlCharts(result.real, result.prediction, result.energy_control.decision, result.energy_control.delta);
                    const explanationBox = document.getElementById('energy-explanation');
                    if (explanationBox) {
                        explanationBox.style.display = 'block';
                        explanationBox.innerHTML = `<strong>> SYSTEM LOG: ENERGY AUDIT</strong><br><span id="energy-typewriter-text"></span><span class="cursor" style="animation: blink 1s step-end infinite;">_</span>`;
                        
                        const textTarget = document.getElementById('energy-typewriter-text');
                        const savedVal = (result.energy_control.saving_rate * 100).toFixed(1);
                        const qoeVal = (result.energy_control.qoe_rate * 100).toFixed(1);
                        const fullText = `Based on model inference and volatility-aware policy, the dynamic control strategy achieves a Total Saved = ${savedVal}% and a QoE Maintained = ${qoeVal}%.`;
                        
                        let charIndex = 0;
                        function typeWriterEnergy() {
                            if (charIndex < fullText.length) {
                                textTarget.innerHTML += fullText.charAt(charIndex);
                                charIndex++;
                                setTimeout(typeWriterEnergy, Math.random() * 20 + 10);
                            }
                        }
                        typeWriterEnergy();
                    }
                }

            } else {
                if (isPredictionMode) document.getElementById('pred-station-id').innerText = `${id} (Failed)`;
                if (isControlMode) document.getElementById('energy-station-id').innerText = `${id} (Failed)`;
            }
            return; 
        }

        if (currentMarker) currentMarker.remove();
        currentMarker = new mapboxgl.Marker().setLngLat(coordinates).addTo(map);
        
        const pitch = map.getPitch();
        map.flyTo({ center: coordinates, zoom: 15, pitch: pitch > 10 ? 60 : 0, speed: 1.5 });
        
        document.getElementById('selected-id').innerText = id;

        try {
            document.getElementById('station-details').innerHTML = '<p class="placeholder-text">Loading details...</p>';
            
            const detailData = await fetchStationDetail(id);
            if (detailData) {
                const stats = detailData.stats || {avg:0, std:0};
                
                document.getElementById('station-details').innerHTML = 
                    `<div style="margin-top:10px;">
                        <p><strong>Longitude:</strong> ${detailData.loc[0].toFixed(4)}</p>
                        <p><strong>Latitude:</strong> ${detailData.loc[1].toFixed(4)}</p>
                        <hr style="border:0; border-top:1px solid #444; margin:5px 0;">
                        <p><strong>Avg Load:</strong> <span style="color:#00cec9">${stats.avg.toFixed(4)}</span></p>
                        <p><strong>Stability:</strong> <span style="color:#fd79a8">${stats.std.toFixed(4)}</span></p>
                    </div>`;
                
                if (detailData.bs_record) {
                    renderChart(detailData.bs_record);
                }
            }
        } catch (err) {
            console.error("Failed to fetch clicked station details:", err);
            document.getElementById('station-details').innerHTML = '<p style="color:red">Error loading data</p>';
        }
    });
}

// Prediction Mode State Control
function setupPredictionMode(map) {
    const predictBtn = document.getElementById('predict-toggle');
    const predPanel = document.getElementById('prediction-panel');
    const closePredBtn = document.getElementById('close-pred-btn');

    if (!predictBtn) return;

    predictBtn.addEventListener('click', () => {
        // Enforce 2D view check for prediction mode
        const pitch = map.getPitch();
        if (pitch > 10) {
            alert("Prediction Mode is only available in 2D View. Please switch to 2D first.");
            return;
        }

        if (!isPredictionMode && isControlMode) {
            document.getElementById('control-toggle').click();
        }

        isPredictionMode = !isPredictionMode;
        
        if (isPredictionMode) {
            predictBtn.classList.add('predict-on');
            predictBtn.innerHTML = '<span class="icon">🔮</span> Mode: ON';
            map.getCanvas().style.cursor = 'crosshair';
        } else {
            predictBtn.classList.remove('predict-on');
            predictBtn.innerHTML = '<span class="icon">🔮</span> Prediction Mode';
            map.getCanvas().style.cursor = '';
            predPanel.classList.remove('active');

            // Reset UI state when exiting prediction
            predPanel.classList.remove('collapsed');
            const rightBtn = document.getElementById('toggle-right-btn');
            if(rightBtn) {
                rightBtn.innerText = '▶';
                rightBtn.classList.remove('active'); 
                rightBtn.classList.remove('collapsed');
            }

            // Clear markers and grids
            clearPredictionExtras(map);
        }
    });

    if (closePredBtn) {
        closePredBtn.addEventListener('click', () => {
            predPanel.classList.remove('active');
            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) rightBtn.classList.remove('active');
            predictBtn.click(); // Trigger toggle to clean up state
        });
    }
}

// function updatePredictionGrid(map, centerLng, centerLat) {
//     const features = [];
//     const step = 0.002; 
//     const gridSize = 3;
//     const offset = Math.floor(gridSize / 2);

//     for (let i = 0; i < gridSize; i++) {
//         for (let j = 0; j < gridSize; j++) {
//             const cLng = centerLng + (j - offset) * step;
//             const cLat = centerLat - (i - offset) * step;
//             const w = step / 2;

//             features.push({
//                 'type': 'Feature',
//                 'geometry': {
//                     'type': 'Polygon',
//                     'coordinates': [[
//                         [cLng - w, cLat - w], [cLng + w, cLat - w],
//                         [cLng + w, cLat + w], [cLng - w, cLat + w],
//                         [cLng - w, cLat - w]
//                     ]]
//                 }
//             });
//         }
//     }

//     const geojson = { 'type': 'FeatureCollection', 'features': features };

//     if (map.getSource('pred-grid-source')) {
//         map.getSource('pred-grid-source').setData(geojson);
//     } else {
//         map.addSource('pred-grid-source', { type: 'geojson', data: geojson });
//         map.addLayer({
//             'id': 'pred-grid-fill', 'type': 'fill', 'source': 'pred-grid-source',
//             'paint': { 'fill-color': '#f39c12', 'fill-opacity': 0.1 }
//         });
//         map.addLayer({
//             'id': 'pred-grid-line', 'type': 'line', 'source': 'pred-grid-source',
//             'paint': { 'line-color': '#f39c12', 'line-width': 2, 'line-dasharray': [2, 2] }
//         });
//     }
// }

// Dynamic 3x3 grid matching the 256px satellite patch bounds
function updatePredictionGrid(map, centerLng, centerLat) {
    const features = [];
    const gridSize = 3;
    const offset = Math.floor(gridSize / 2);

    // Precise Web Mercator projection span calculation at Zoom 15
    const zoom = 15; 
    
    // Total Longitude span for 256 pixels at this zoom
    const lonSpan = 360 / Math.pow(2, zoom); 
    // Latitude span (scaled by local latitude)
    const latSpan = lonSpan * Math.cos(centerLat * Math.PI / 180);

    // Actual step sizes for 3x3 division
    const stepLon = lonSpan / gridSize;
    const stepLat = latSpan / gridSize;

    for (let i = 0; i < gridSize; i++) {
        for (let j = 0; j < gridSize; j++) {
            // Center point of each micro-grid cell
            const cLng = centerLng + (j - offset) * stepLon;
            const cLat = centerLat - (i - offset) * stepLat;

            const wLon = stepLon / 2;
            const wLat = stepLat / 2;

            features.push({
                'type': 'Feature',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [[
                        [cLng - wLon, cLat - wLat], [cLng + wLon, cLat - wLat],
                        [cLng + wLon, cLat + wLat], [cLng - wLon, cLat + wLat],
                        [cLng - wLon, cLat - wLat]
                    ]]
                }
            });
        }
    }

    const geojson = { 'type': 'FeatureCollection', 'features': features };

    if (map.getSource('pred-grid-source')) {
        map.getSource('pred-grid-source').setData(geojson);
    } else {
        map.addSource('pred-grid-source', { type: 'geojson', data: geojson });
        map.addLayer({
            'id': 'pred-grid-fill', 'type': 'fill', 'source': 'pred-grid-source',
            'paint': { 'fill-color': '#f39c12', 'fill-opacity': 0.1 }
        });
        map.addLayer({
            'id': 'pred-grid-line', 'type': 'line', 'source': 'pred-grid-source',
            'paint': { 'line-color': '#f39c12', 'line-width': 2, 'line-dasharray': [2, 2] }
        });
    }
}

// Cleanup prediction visual elements
function clearPredictionExtras(map) {
    if (predictionMarker) { predictionMarker.remove(); predictionMarker = null; }
    if (optimalMarker) { optimalMarker.remove(); optimalMarker = null; } // ====== 新增：清理绿色点 ======
    if (map.getSource('pred-grid-source')) {
        map.getSource('pred-grid-source').setData({ type: 'FeatureCollection', features: [] });
    }
}

// ==========================================
// 7. Timeline Logic
// ==========================================
function setupTimeLapse(map, globalData) {
    const playBtn = document.getElementById('play-btn');
    const slider = document.getElementById('time-slider');
    const display = document.getElementById('time-display');
    if (!playBtn || !slider) return;

    const totalHours = (globalData.length > 0 && globalData[0].vals) ? globalData[0].vals.length : 672;
    slider.max = totalHours - 1;
    let isPlaying = false;
    let speed = 100;

    const updateTime = (val) => {
        const day = Math.floor(val / 24) + 1;
        const hour = val % 24;
        display.innerText = `Day ${day.toString().padStart(2, '0')} - ${hour.toString().padStart(2, '0')}:00`;
        
        updateGeoJSONData(map, globalData, 'time', val);
        updateChartCursor(val);
    };

    const play = () => {
        let val = parseInt(slider.value);
        val = (val + 1) % totalHours; 
        slider.value = val;
        updateTime(val);
        if (isPlaying) animationFrameId = setTimeout(() => requestAnimationFrame(play), speed); 
    };

    playBtn.onclick = () => {
        isPlaying = !isPlaying;
        playBtn.innerText = isPlaying ? '⏸' : '▶';
        if (isPlaying) play(); else clearTimeout(animationFrameId);
    };

    slider.oninput = (e) => {
        isPlaying = false; 
        if(animationFrameId) clearTimeout(animationFrameId);
        playBtn.innerText = '▶';
        updateTime(parseInt(e.target.value));
    };
}

// ==========================================
// 8. UI Controls
// ==========================================
function setupModeToggle(map) {
    const btn = document.getElementById('view-toggle');
    const timePanel = document.querySelector('.time-panel');
    let is3D = true;

    if (!btn) return;

    btn.onclick = () => {
        if (isPredictionMode || isControlMode) {
            alert("Please exit AI Mode (Prediction / Energy Control) before switching to 3D.");
            return;
        }

        is3D = !is3D;
        if (is3D) {
            if(map.getLayer('stations-3d-pillars')) map.setLayoutProperty('stations-3d-pillars', 'visibility', 'visible');
            map.easeTo({ pitch: 60, bearing: -15 });
            btn.innerHTML = '<span class="icon">👁️</span> View: 3D';
            if (timePanel) {
                timePanel.style.display = 'flex';
                setTimeout(() => { timePanel.style.opacity = '1'; }, 10);
            }
        } else {
            if(map.getLayer('stations-3d-pillars')) map.setLayoutProperty('stations-3d-pillars', 'visibility', 'none');
            map.easeTo({ pitch: 0, bearing: 0 });
            btn.innerHTML = '<span class="icon">🗺️</span> View: 2D';
            if (timePanel) {
                timePanel.style.display = 'none';
                timePanel.style.opacity = '0';
            }
            const playBtn = document.getElementById('play-btn');
            if (playBtn && playBtn.innerText === '⏸') playBtn.click();
        }
    };
}

function setupDataToggle(map) {
    const btn = document.getElementById('data-toggle');
    const layers = ['stations-3d-pillars', 'stations-2d-dots', 'stations-heatmap', 'stations-hitbox'];
    let isVisible = true;
    if(btn) btn.onclick = () => {
        isVisible = !isVisible;
        const val = isVisible ? 'visible' : 'none';
        layers.forEach(id => { if(map.getLayer(id)) map.setLayoutProperty(id, 'visibility', val); });
        btn.innerHTML = isVisible ? '<span class="icon">📡</span> Toggle Data' : '<span class="icon">🚫</span> Toggle Data';
        btn.style.opacity = isVisible ? '1' : '0.6';
    };
}

// function setupFilterMenu(map, statsColor) {
//     const btn = document.getElementById('filter-btn');
//     const menu = document.getElementById('filter-menu');
//     if (!btn || !menu) return;

//     // Define stability levels based on Standard Deviation thresholds
//     const levels = [
//         { label: "Level 5: Highly Unstable", color: "#e84393", filter: ['>=', 'load_std', statsColor.t4] },
//         { label: "Level 4: Volatile",        color: "#fd79a8", filter: ['all', ['>=', 'load_std', statsColor.t3], ['<', 'load_std', statsColor.t4]] },
//         { label: "Level 3: Normal",          color: "#00cec9", filter: ['all', ['>=', 'load_std', statsColor.t2], ['<', 'load_std', statsColor.t3]] },
//         { label: "Level 2: Stable",          color: "#0984e3", filter: ['all', ['>=', 'load_std', statsColor.t1], ['<', 'load_std', statsColor.t2]] },
//         { label: "Level 1: Highly Stable",   color: "#1e1e2e", filter: ['<', 'load_std', statsColor.t1] }
//     ];

//     menu.innerHTML = ''; 
//     levels.forEach((lvl) => {
//         const item = document.createElement('div');
//         item.className = 'filter-item';
//         item.innerHTML = `<div class="color-box" style="background:${lvl.color}; box-shadow: 0 0 5px ${lvl.color};"></div><span>${lvl.label}</span>`;
//         item.onclick = (e) => {
//             e.stopPropagation(); 
//             if (item.classList.contains('selected')) {
//                 item.classList.remove('selected'); 
//                 applyFilter(map, null); 
//             } else {
//                 document.querySelectorAll('.filter-item').forEach(el => el.classList.remove('selected'));
//                 item.classList.add('selected'); 
//                 applyFilter(map, lvl.filter);
//             }
//         };
//         menu.appendChild(item);
//     });

//     // Toggle menu visibility
//     btn.onclick = (e) => { e.stopPropagation(); menu.classList.toggle('active'); };
//     document.addEventListener('click', (e) => { if (!menu.contains(e.target) && !btn.contains(e.target)) menu.classList.remove('active'); });
// }

function setupFilterMenu(map, statsColor) {
    const btn = document.getElementById('filter-btn');
    const menu = document.getElementById('filter-menu');
    if (!btn || !menu) return;

    const levels = [
        { label: "Level 5: Highly Unstable", color: "#e84393", filter: ['>=', 'load_std', statsColor.t4] },
        { label: "Level 4: Volatile",        color: "#fd79a8", filter: ['all', ['>=', 'load_std', statsColor.t3], ['<', 'load_std', statsColor.t4]] },
        { label: "Level 3: Normal",          color: "#00cec9", filter: ['all', ['>=', 'load_std', statsColor.t2], ['<', 'load_std', statsColor.t3]] },
        { label: "Level 2: Stable",          color: "#0984e3", filter: ['all', ['>=', 'load_std', statsColor.t1], ['<', 'load_std', statsColor.t2]] },
        { label: "Level 1: Highly Stable",   color: "#1e1e2e", filter: ['<', 'load_std', statsColor.t1] }
    ];

    menu.innerHTML = ''; 
    
    levels.forEach((lvl, index) => {
        const item = document.createElement('div');
        item.className = 'filter-item';
        item.innerHTML = `<div class="color-box" style="background:${lvl.color}; box-shadow: 0 0 5px ${lvl.color};"></div><span>${lvl.label}</span>`;
        
        // Muti Select
        item.onclick = (e) => {
            e.stopPropagation(); 
            item.classList.toggle('selected');
            const activeFilters = [];
            const allItems = menu.querySelectorAll('.filter-item');
            allItems.forEach((el, i) => {
                if (el.classList.contains('selected')) {
                    activeFilters.push(levels[i].filter);
                }
            });
            if (activeFilters.length === 0) {
                applyFilter(map, null);
            } else {
                const combinedFilter = ['any', ...activeFilters];
                applyFilter(map, combinedFilter);
            }
        };
        menu.appendChild(item);
    });

    btn.onclick = (e) => { e.stopPropagation(); menu.classList.toggle('active'); };
    document.addEventListener('click', (e) => { 
        if (!menu.contains(e.target) && !btn.contains(e.target)) menu.classList.remove('active'); 
    });
}


function applyFilter(map, filterExpression) {
    const targetLayers = ['stations-3d-pillars', 'stations-2d-dots', 'stations-heatmap', 'stations-hitbox'];
    targetLayers.forEach(layerId => { if (map.getLayer(layerId)) map.setFilter(layerId, filterExpression); });
}

function setupSearch(map, globalData) {
    const input = document.getElementById('search-input');
    const btn = document.getElementById('search-btn');
    const clearBtn = document.getElementById('clear-search-btn');
    const keepCheck = document.getElementById('keep-markers-check');

    if (!input || !btn) return;

    let searchMarkers = [];

    const clearAllMarkers = () => {
        searchMarkers.forEach(marker => marker.remove());
        searchMarkers = [];
    };

    const performSearch = async () => {
        const queryId = input.value.trim();
        if (!queryId) return;

        const target = globalData.find(s => String(s.id) === String(queryId));

        if (target) {
            if (!keepCheck.checked) {
                clearAllMarkers();
            }

            // Fly to searched station and switch to high-detail view
            map.flyTo({
                center: target.loc,
                zoom: 16,
                pitch: 60,
                essential: true
            });

            document.getElementById('selected-id').innerText = target.id;
            try {
                const detailData = await fetchStationDetail(target.id);
                if (detailData) {
                    const stats = detailData.stats || {avg:0, std:0};
                    document.getElementById('station-details').innerHTML = 
                        `<div style="margin-top:10px;">
                            <p><strong>Longitude:</strong> ${detailData.loc[0].toFixed(4)}</p>
                            <p><strong>Latitude:</strong> ${detailData.loc[1].toFixed(4)}</p>
                            <hr style="border:0; border-top:1px solid #444; margin:5px 0;">
                            <p><strong>Avg Load:</strong> <span style="color:#00cec9">${stats.avg.toFixed(4)}</span></p>
                            <p><strong>Stability:</strong> <span style="color:#fd79a8">${stats.std.toFixed(4)}</span></p>
                        </div>`;
                    
                    if (detailData.bs_record) renderChart(detailData.bs_record);
                }
            } catch (e) {
                console.error("Fetch details failed", e);
            }

            // Create red highlight marker for searched target
            const marker = new mapboxgl.Marker({ color: '#ff0000', scale: 0.8 })
                .setLngLat(target.loc)
                .setPopup(new mapboxgl.Popup({ offset: 25 }).setText(`Station ID: ${target.id}`)) 
                .addTo(map);
            
            searchMarkers.push(marker);

        } else {
            alert("Station ID not found!");
        }
    };

    btn.onclick = performSearch;
    
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });

    if (clearBtn) {
        clearBtn.onclick = () => {
            clearAllMarkers();
            input.value = '';
        };
    }
}

// Sidebar & Panel Toggle Logic
function setupPanelToggles(map) {
    const leftSidebar = document.querySelector('.sidebar');
    const leftToggleBtn = document.getElementById('toggle-left-btn');
    
    if (leftToggleBtn && leftSidebar) {
        leftToggleBtn.addEventListener('click', () => {
            leftSidebar.classList.toggle('collapsed');
            leftToggleBtn.classList.toggle('collapsed'); 
            leftToggleBtn.innerText = leftSidebar.classList.contains('collapsed') ? '▶' : '◀';
            setTimeout(() => map.resize(), 300);
        });
    }

    const rightToggleBtn = document.getElementById('toggle-right-btn');
    if (rightToggleBtn) {
        rightToggleBtn.addEventListener('click', () => {
            const predPanel = document.getElementById('prediction-panel');
            const ctrlPanel = document.getElementById('energy-control-panel');
            
            let activePanel = null;
            if (predPanel && predPanel.classList.contains('active')) activePanel = predPanel;
            if (ctrlPanel && ctrlPanel.classList.contains('active')) activePanel = ctrlPanel;

            if (activePanel) {
                activePanel.classList.toggle('collapsed');
                rightToggleBtn.classList.toggle('collapsed'); 
                rightToggleBtn.innerText = activePanel.classList.contains('collapsed') ? '◀' : '▶';
                setTimeout(() => map.resize(), 300);
            }
        });
    }
}

// ==========================================
// 9. Main Entry Point
// ==========================================
window.onload = async () => {
    const map = initMap();
    
    map.on('load', async () => {
        setupMapEnvironment(map);
        
        try {
            // Load initial station metadata
            const data = await fetchLocations();
            globalStationData = data.stations;
            document.getElementById('total-stations').innerText = globalStationData.length;

            // Initialize Map Layers with empty data initially
            addStationLayers(map, 
                             {points: {type:'FeatureCollection', features:[]}, polys: {type:'FeatureCollection', features:[]} }, 
                             data.stats_height, data.stats_color);
            
            // Immediately load data for T=0 (initial state)
            updateGeoJSONData(map, globalStationData, 'time', 0);
            updateChartCursor(0);

            // Start Time Lapse
            setupTimeLapse(map, globalStationData);
            
            // Bind Interactions
            setupPredictionMode(map);   // Initialize AI Prediction events
            setupControlMode(map);
            setupInteraction(map);      // Initialize standard map clicks/popups
            setupModeToggle(map);       // 2D/3D View switch
            setupDataToggle(map);       // Layer visibility switch
            setupFilterMenu(map, data.stats_color); // Load-stability filters
            setupSearch(map, globalStationData);    // Search bar logic

            // Initialize sidebar collapse/expand controls
            setupPanelToggles(map);

            // Remove Loading Screen
            document.getElementById('loading').style.display = 'none';
        } catch (e) {
            console.error(e);
            alert('System Initialization Failed. Check Console.');
            document.getElementById('loading').innerHTML = '<h2>Error Loading Data</h2>';
        }
    });
};