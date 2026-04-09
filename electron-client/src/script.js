// ==========================================
// 1. Config (Focused on Shanghai)
// ==========================================
// 从本地存储读取服务器配置，或使用默认值
const SERVER_CONFIG = JSON.parse(localStorage.getItem('serverConfig')) || {
    host: '127.0.0.1',
    port: '7860',
    protocol: 'http'
};

const CONFIG = {
    MAPBOX_TOKEN: window.MAPBOX_TOKEN || 'YOUR_MAPBOX_TOKEN_HERE',
    get API_BASE() {
        return `${SERVER_CONFIG.protocol}://${SERVER_CONFIG.host}:${SERVER_CONFIG.port}/api`;
    },
    
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
let isUserMode = false;
let isSimMode = false;
let simStationLocs = null;     // {numeric_base_id: [lng, lat]}
let simSnapshotCache = {};     // {time_index: snapshotData}
let simCurrentTime = 0;
let simTimeSlots = 336;
let simAnimFrameId = null;
let simIsPlaying = false;
let simLayerVisibility = { dots: true, lines: false, heatmap: false, handovers: false };
let simStationIdMap = null;    // {hex_to_numeric: {}, numeric_to_hex: {}}
let simSelectedStationHexId = null;  // currently selected station hex id in sim mode
let simSelectedStationCoords = null; // [lng, lat] of selected station
let userTrajectoryLayer = null;
let userTrajectoryMarkers = [];
let currentUserStats = null;

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

// --- User Data API Functions ---
async function fetchUserStats() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/users/stats`);
        return await res.json();
    } catch (e) {
        console.error('Fetch user stats error:', e);
        return null;
    }
}

async function fetchUsersByBase(baseId) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/users/by_base/${baseId}`);
        return await res.json();
    } catch (e) {
        console.error('Fetch users by base error:', e);
        return { users: [] };
    }
}

async function fetchUserDetail(userId) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/users/${userId}`);
        return await res.json();
    } catch (e) {
        console.error('Fetch user detail error:', e);
        return null;
    }
}

async function fetchUserTrajectory(userId, limit = 200) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/users/${userId}/trajectory?limit=${limit}`);
        return await res.json();
    } catch (e) {
        console.error('Fetch user trajectory error:', e);
        return { records: [] };
    }
}

async function fetchAppModels() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/app_models`);
        return await res.json();
    } catch (e) {
        console.error('Fetch app models error:', e);
        return null;
    }
}

// --- Simulation API Functions ---
async function fetchSimulationSnapshot(timeIndex) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/simulation/snapshot?t=${timeIndex}`);
        return await res.json();
    } catch (e) {
        console.error('Fetch simulation snapshot error:', e);
        return null;
    }
}

async function fetchSimulationStationLocs() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/simulation/station_locs`);
        return await res.json();
    } catch (e) {
        console.error('Fetch simulation station locs error:', e);
        return null;
    }
}

async function fetchSimulationInfo() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/simulation/info`);
        return await res.json();
    } catch (e) {
        console.error('Fetch simulation info error:', e);
        return null;
    }
}

async function fetchSimStationIdMap() {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/simulation/station_id_map`);
        return await res.json();
    } catch (e) {
        console.error('Fetch station id map error:', e);
        return null;
    }
}

async function fetchStationTimeSeries(stationId) {
    try {
        const res = await fetch(`${CONFIG.API_BASE}/simulation/station_time_series/${stationId}`);
        return await res.json();
    } catch (e) {
        console.error('Fetch station time series error:', e);
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
function renderChart(recordData, secondaryData = null, options = {}) {
    const ctx = document.getElementById('energyChart').getContext('2d');
    if (chartInstance) chartInstance.destroy();

    const datasets = [
        { 
            label: options.label1 || 'Traffic', data: recordData, 
            borderColor: options.color1 || '#00cec9', backgroundColor: options.bg1 || 'rgba(0, 206, 201, 0.1)', 
            borderWidth: 1.5, fill: true, pointRadius: 0, tension: 0.3,
            yAxisID: 'y'
        },
        { 
            label: 'Current', data: [], type: 'scatter', 
            pointRadius: 6, pointBackgroundColor: '#ffffff', 
            pointBorderColor: '#e84393', pointBorderWidth: 3,
            yAxisID: 'y'
        }
    ];
    
    const scales = { 
        x: { display: false }, 
        y: { position: 'left', grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', font: {size: 10} } } 
    };

    // Dual-axis: add secondary dataset (e.g. traffic alongside user counts)
    if (secondaryData) {
        datasets.push({
            label: options.label2 || 'Traffic (MB)', data: secondaryData,
            borderColor: options.color2 || '#fdcb6e', backgroundColor: 'transparent',
            borderWidth: 1, fill: false, pointRadius: 0, tension: 0.3, borderDash: [4, 2],
            yAxisID: 'y2'
        });
        scales.y2 = { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: '#fdcb6e', font: {size: 9} } };
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: recordData.map((_, i) => i), datasets },
        options: { 
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: !!secondaryData, labels: { color: '#aaa', font: {size: 9}, boxWidth: 12 } } }, 
            scales
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

        // In simulation mode, show station sim stats
        if (isSimMode) {
            if (currentMarker) currentMarker.remove();
            currentMarker = new mapboxgl.Marker({ color: '#ff6348' }).setLngLat(coordinates).addTo(map);
            map.flyTo({ center: coordinates, zoom: 15, pitch: 0, speed: 1.5 });
            document.getElementById('selected-id').innerText = id;

            // Remember selected station for auto-refresh on timeline change
            simSelectedStationHexId = id;
            simSelectedStationCoords = coordinates;

            // Update station panel with current snapshot
            updateSimStationPanel();

            // Fetch and render time series chart (dual axis: users + traffic)
            const ts = await fetchStationTimeSeries(id);
            if (ts && ts.user_counts) {
                renderChart(ts.user_counts, ts.traffic_totals, {
                    label1: 'Users', color1: '#0984e3', bg1: 'rgba(9,132,227,0.15)',
                    label2: 'Traffic (MB)', color2: '#fdcb6e'
                });
                // Position cursor at current sim time
                updateChartCursor(simCurrentTime);
            }
            return;
        }


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

        // If user mode is on, load associated users
        if (isUserMode) {
            showStationUsers(id, map);
        }

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
        if (isPredictionMode || isControlMode || isSimMode) {
            alert("Please exit AI Mode (Prediction / Energy Control / Simulation) before switching to 3D.");
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
            const userPanel = document.getElementById('user-panel');
            if (userPanel && userPanel.classList.contains('active')) activePanel = userPanel;

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
            setupUserMode(map);         // Initialize User Analytics
            setupSimulationMode(map);   // Initialize Simulation Mode
            setupInteraction(map);      // Initialize standard map clicks/popups
            setupModeToggle(map);       // 2D/3D View switch
            setupDataToggle(map);       // Layer visibility switch
            setupFilterMenu(map, data.stats_color); // Load-stability filters
            setupSearch(map, globalStationData);    // Search bar logic

            // Initialize sidebar collapse/expand controls
            setupPanelToggles(map);

            // Remove Loading Screen
            document.getElementById('loading').style.display = 'none';
            
            // Initialize server settings
            setupServerSettings();
        } catch (e) {
            console.error(e);
            alert('System Initialization Failed. Check Console.');
            document.getElementById('loading').innerHTML = '<h2>Error Loading Data</h2>';
        }
    });
};

// ==========================================
// User Panel Logic
// ==========================================
const ROLE_COLORS = {
    service_worker: '#e84393',
    office_worker: '#0984e3',
    student: '#00cec9',
    factory_worker: '#fdcb6e',
    freelancer: '#6c5ce7',
    healthcare_worker: '#00b894'
};

const ROLE_LABELS = {
    service_worker: 'Service Worker',
    office_worker: 'Office Worker',
    student: 'Student',
    factory_worker: 'Factory Worker',
    freelancer: 'Freelancer',
    healthcare_worker: 'Healthcare'
};

function setupUserMode(map) {
    const userBtn = document.getElementById('user-toggle');
    const userPanel = document.getElementById('user-panel');
    const closeUserBtn = document.getElementById('close-user-btn');
    if (!userBtn) return;

    userBtn.addEventListener('click', async () => {
        if (!isUserMode && isPredictionMode) document.getElementById('predict-toggle').click();
        if (!isUserMode && isControlMode) document.getElementById('control-toggle').click();

        isUserMode = !isUserMode;
        if (isUserMode) {
            userBtn.classList.add('predict-on');
            userBtn.innerHTML = '<span class="icon">👤</span> Users: ON';
            userPanel.classList.add('active');
            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) rightBtn.classList.add('active');
            await loadUserOverview();
            await loadAppModels();
        } else {
            userBtn.classList.remove('predict-on');
            userBtn.innerHTML = '<span class="icon">👤</span> Users';
            userPanel.classList.remove('active');
            userPanel.classList.remove('collapsed');
            const rightBtn = document.getElementById('toggle-right-btn');
            if (rightBtn) {
                rightBtn.innerText = '▶';
                rightBtn.classList.remove('active');
                rightBtn.classList.remove('collapsed');
            }
            clearUserTrajectory(map);
        }
    });

    if (closeUserBtn) closeUserBtn.addEventListener('click', () => userBtn.click());
}

async function loadUserOverview() {
    const statsDiv = document.getElementById('user-stats-content');
    const roleBars = document.getElementById('role-bars');
    const data = await fetchUserStats();
    if (!data || !data.loaded) {
        statsDiv.innerHTML = '<p style="color: #ff6b6b;">User data not available</p>';
        return;
    }
    currentUserStats = data;

    statsDiv.innerHTML = `
        <div class="stat-card">
            <div class="stat-number">${(data.total_users).toLocaleString()}</div>
            <div class="stat-label">Total Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">${(data.total_trajectories / 1e6).toFixed(1)}M</div>
            <div class="stat-label">Trajectories</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">${Object.keys(data.roles).length}</div>
            <div class="stat-label">Role Types</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">${data.users_with_trajectories.toLocaleString()}</div>
            <div class="stat-label">With Trajectory</div>
        </div>`;

    // Role distribution bars
    const maxCount = Math.max(...Object.values(data.roles));
    roleBars.innerHTML = Object.entries(data.roles)
        .sort((a, b) => b[1] - a[1])
        .map(([role, count]) => {
            const pct = (count / maxCount * 100).toFixed(0);
            const color = ROLE_COLORS[role] || '#888';
            const label = ROLE_LABELS[role] || role;
            return `<div class="role-bar-item">
                <span class="role-name">${label}</span>
                <div class="bar-wrapper"><div class="bar-fill" style="width:${pct}%; background:${color};"></div></div>
                <span class="bar-count">${count}</span>
            </div>`;
        }).join('');
}

async function loadAppModels() {
    const container = document.getElementById('app-models-content');
    const data = await fetchAppModels();
    if (!data) { container.innerHTML = '<p style="color:#888">Not available</p>'; return; }

    const modelColors = { video: '#e84393', social: '#0984e3', gaming: '#fdcb6e', browsing: '#00cec9' };
    container.innerHTML = Object.entries(data).map(([key, m]) => {
        const color = modelColors[key] || '#888';
        return `<div class="app-model-card" style="border-left: 3px solid ${color};">
            <div class="model-name" style="color:${color}">${m.name_en}</div>
            <div class="model-desc">${m.description}</div>
            <div class="model-stats">
                <span>↑ ${m.avg_bandwidth_mbps} Mbps</span>
                <span>↓ DL ${(m.downlink_ratio * 100).toFixed(0)}%</span>
                <span>⏱ ${m.latency_sensitivity}</span>
            </div>
            <div style="margin-top:4px; font-size:10px; color:#666;">${m.categories.join(', ')}</div>
        </div>`;
    }).join('');
}

async function showStationUsers(baseId, map) {
    const section = document.getElementById('station-users-section');
    const list = document.getElementById('station-users-list');
    const badge = document.getElementById('station-users-badge');
    if (!isUserMode) return;

    section.style.display = 'block';
    list.innerHTML = '<p style="color:#888; font-size:12px;">Loading...</p>';
    badge.textContent = `Station #${baseId}`;

    const data = await fetchUsersByBase(baseId);
    if (!data.users || data.users.length === 0) {
        list.innerHTML = '<p style="color:#888; font-size:12px;">No users at this station</p>';
        return;
    }

    list.innerHTML = data.users.slice(0, 30).map(u => {
        const color = ROLE_COLORS[u.role] || '#888';
        const label = ROLE_LABELS[u.role] || u.role;
        return `<div class="user-list-item" data-uid="${u.user_id}">
            <span class="user-id">${u.user_id.substring(0, 12)}...</span>
            <span class="role-badge" style="border: 1px solid ${color}; color: ${color};">${label}</span>
        </div>`;
    }).join('') + (data.users.length > 30 ? `<p style="color:#666; font-size:11px; text-align:center; margin-top:8px;">...and ${data.users.length - 30} more</p>` : '');

    // Click user in list
    list.querySelectorAll('.user-list-item').forEach(item => {
        item.addEventListener('click', () => showUserDetail(item.dataset.uid, map));
    });
}

async function showUserDetail(userId, map) {
    const section = document.getElementById('user-detail-section');
    const content = document.getElementById('user-detail-content');
    section.style.display = 'block';
    content.innerHTML = '<p style="color:#888;">Loading user profile...</p>';

    const data = await fetchUserDetail(userId);
    if (!data) { content.innerHTML = '<p style="color:#ff6b6b;">Error loading user</p>'; return; }

    const color = ROLE_COLORS[data.role] || '#888';
    const label = ROLE_LABELS[data.role] || data.role;
    content.innerHTML = `
        <div style="background:rgba(0,0,0,0.3); padding:10px; border-radius:6px; margin-bottom:8px;">
            <p style="font-size:12px; color:#ccc;"><strong style="color:#a29bfe;">ID:</strong> <span style="font-family:monospace;">${data.user_id}</span></p>
            <p style="font-size:12px; color:#ccc;"><strong style="color:#a29bfe;">Role:</strong> <span style="color:${color}">${label}</span></p>
            <p style="font-size:12px; color:#ccc;"><strong style="color:#a29bfe;">Trajectory:</strong> ${(data.trajectory_count || 0).toLocaleString()} records</p>
        </div>
        ${data.app_summary ? `<div style="margin-top:6px;">
            <p style="font-size:11px; color:#888; margin-bottom:4px;">APP USAGE:</p>
            ${Object.entries(data.app_summary).map(([cat, cnt]) => 
                `<span style="display:inline-block; font-size:10px; background:rgba(162,155,254,0.1); border:1px solid rgba(162,155,254,0.2); padding:2px 6px; border-radius:4px; margin:2px; color:#ccc;">${cat}: ${cnt}</span>`
            ).join('')}
        </div>` : ''}`;

    // Setup trajectory button
    const trajBtn = document.getElementById('show-trajectory-btn');
    trajBtn.onclick = async () => {
        trajBtn.innerHTML = '<span class="icon">⏳</span> Loading...';
        await renderUserTrajectory(userId, map);
        trajBtn.innerHTML = '<span class="icon">🗺️</span> Show Trajectory on Map';
    };
}

async function renderUserTrajectory(userId, map) {
    clearUserTrajectory(map);
    const data = await fetchUserTrajectory(userId, 500);
    if (!data.records || data.records.length === 0) return;

    // records: [[timestamp, base_id, lng, lat, app_cat, ...], ...]
    const coords = data.records
        .filter(r => r[2] && r[3])
        .map(r => [r[2], r[3]]);
    
    if (coords.length === 0) return;

    // Add trajectory line
    map.addSource('user-trajectory', {
        type: 'geojson',
        data: {
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: coords }
        }
    });

    map.addLayer({
        id: 'user-trajectory-line',
        type: 'line',
        source: 'user-trajectory',
        paint: {
            'line-color': '#a29bfe',
            'line-width': 2.5,
            'line-opacity': 0.8,
            'line-dasharray': [2, 1]
        }
    });

    // Add start/end markers
    const startEl = document.createElement('div');
    startEl.style.cssText = 'width:12px;height:12px;background:#00b894;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px #00b894;';
    const endEl = document.createElement('div');
    endEl.style.cssText = 'width:12px;height:12px;background:#e84393;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px #e84393;';

    const startMarker = new mapboxgl.Marker(startEl).setLngLat(coords[0]).addTo(map);
    const endMarker = new mapboxgl.Marker(endEl).setLngLat(coords[coords.length - 1]).addTo(map);
    userTrajectoryMarkers.push(startMarker, endMarker);
    userTrajectoryLayer = 'user-trajectory';

    // Fit bounds to trajectory
    const bounds = coords.reduce((b, c) => b.extend(c), new mapboxgl.LngLatBounds(coords[0], coords[0]));
    map.fitBounds(bounds, { padding: 80, maxZoom: 15 });
}

function clearUserTrajectory(map) {
    if (map.getLayer('user-trajectory-line')) map.removeLayer('user-trajectory-line');
    if (map.getSource('user-trajectory')) map.removeSource('user-trajectory');
    userTrajectoryMarkers.forEach(m => m.remove());
    userTrajectoryMarkers = [];
    userTrajectoryLayer = null;
}

// ==========================================
// Simulation Mode (Phase 2)
// ==========================================

function setupSimulationMode(map) {
    const simBtn = document.getElementById('sim-toggle');
    const simControls = document.getElementById('sim-controls');
    const simLegend = document.getElementById('sim-legend');
    if (!simBtn) return;

    simBtn.addEventListener('click', async () => {
        // Exit other modes first
        if (!isSimMode && isPredictionMode) document.getElementById('predict-toggle').click();
        if (!isSimMode && isControlMode) document.getElementById('control-toggle').click();
        if (!isSimMode && isUserMode) document.getElementById('user-toggle').click();

        isSimMode = !isSimMode;

        if (isSimMode) {
            simBtn.classList.add('predict-on');
            simBtn.innerHTML = '<span class="icon">\ud83c\udf10</span> Sim: ON';

            // Switch to 2D
            const pitch = map.getPitch();
            if (pitch > 10) {
                const viewBtn = document.getElementById('view-toggle');
                if (viewBtn) viewBtn.click();
            }

            simControls.style.display = 'block';
            simLegend.style.display = 'block';

            // Load station locs mapping (one-time)
            if (!simStationLocs) {
                const [locs, idMap] = await Promise.all([
                    fetchSimulationStationLocs(),
                    fetchSimStationIdMap()
                ]);
                simStationLocs = locs;
                simStationIdMap = idMap;
                console.log(`[Sim] Station locs loaded: ${Object.keys(simStationLocs || {}).length}`);
            }

            // Get simulation info
            const info = await fetchSimulationInfo();
            if (info && info.time_slots) {
                simTimeSlots = info.time_slots;
            }

            // Update time slider for simulation (7 days, 30-min slots)
            const slider = document.getElementById('time-slider');
            if (slider) {
                slider._originalMax = slider.max;  // Save original
                slider.max = simTimeSlots - 1;
                slider.value = 0;
            }

            // Initialize simulation layers
            initSimulationLayers(map);

            // Load first snapshot
            await updateSimulationSnapshot(map, 0);

            // Setup layer toggle buttons
            setupSimLayerToggles(map);

            // Override time slider for simulation (once)
            if (!map._simTimelineSetup) {
                setupSimTimeline(map);
                setupSimUserPopup(map);
                map._simTimelineSetup = true;
            }

        } else {
            simBtn.classList.remove('predict-on');
            simBtn.innerHTML = '<span class="icon">\ud83c\udf10</span> Simulation';
            simControls.style.display = 'none';
            simLegend.style.display = 'none';

            // Stop playback
            if (simAnimFrameId) { clearTimeout(simAnimFrameId); simAnimFrameId = null; }
            simIsPlaying = false;
            const playBtn = document.getElementById('play-btn');
            if (playBtn) playBtn.innerText = '\u25b6';

            // Restore time slider
            const slider = document.getElementById('time-slider');
            if (slider && slider._originalMax) {
                slider.max = slider._originalMax;
                slider.value = 0;
            }

            // Remove simulation layers
            cleanupSimulationLayers(map);
            if (_simPopup) { _simPopup.remove(); _simPopup = null; }
            simSnapshotCache = {};
            simSelectedStationHexId = null;
            simSelectedStationCoords = null;
        }
    });
}

function initSimulationLayers(map) {
    // --- Station overlay: color stations by user count ---
    if (!map.getSource('sim-station-stats')) {
        map.addSource('sim-station-stats', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] }
        });
    }
    if (!map.getLayer('sim-station-overlay')) {
        map.addLayer({
            id: 'sim-station-overlay',
            type: 'circle',
            source: 'sim-station-stats',
            paint: {
                'circle-radius': [
                    'interpolate', ['linear'], ['get', 'users'],
                    0, 4,
                    5, 6,
                    15, 10,
                    30, 14,
                    60, 20
                ],
                'circle-color': [
                    'interpolate', ['linear'], ['get', 'users'],
                    0, '#2c3e50',
                    3, '#0984e3',
                    10, '#00cec9',
                    25, '#fdcb6e',
                    50, '#e17055',
                    80, '#d63031'
                ],
                'circle-opacity': 0.85,
                'circle-stroke-width': 1.5,
                'circle-stroke-color': 'rgba(255,255,255,0.6)'
            }
        });
    }

    // Dim existing 3D pillars in sim mode
    if (map.getLayer('stations-3d-pillars')) {
        map.setPaintProperty('stations-3d-pillars', 'fill-extrusion-opacity', 0.15);
    }
    if (map.getLayer('stations-heatmap')) {
        map.setLayoutProperty('stations-heatmap', 'visibility', 'none');
    }

    // --- Handover arcs source ---
    if (!map.getSource('sim-handovers')) {
        map.addSource('sim-handovers', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] }
        });
    }
    if (!map.getLayer('sim-handover-arcs')) {
        map.addLayer({
            id: 'sim-handover-arcs',
            type: 'line',
            source: 'sim-handovers',
            paint: {
                'line-color': '#a29bfe',
                'line-width': 2,
                'line-opacity': 0.7,
                'line-dasharray': [3, 2]
            },
            layout: { 'visibility': 'none' },
            minzoom: 12
        });
    }

    // Users points source (MUST be created before layers that reference it)
    if (!map.getSource('sim-users')) {
        map.addSource('sim-users', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] }
        });
    }

    // Handover user highlight dots (uses sim-users source)
    if (!map.getLayer('sim-handover-dots')) {
        map.addLayer({
            id: 'sim-handover-dots',
            type: 'circle',
            source: 'sim-users',
            filter: ['==', ['get', 'handover'], 1],
            paint: {
                'circle-radius': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 3, 13, 5, 16, 8
                ],
                'circle-color': '#a29bfe',
                'circle-opacity': 0.9,
                'circle-stroke-width': 2,
                'circle-stroke-color': '#ffffff'
            },
            minzoom: 11
        });
    }

    // User dots layer - person icons via symbol layer
    if (!map.getLayer('sim-users-dots')) {
        // Generate person icon as raw ImageData for Mapbox (SDF compatible)
        if (!map.hasImage('person-icon')) {
            const sz = 40;
            const data = new Uint8ClampedArray(sz * sz * 4);
            // Helper to set pixel alpha (SDF: white icon on transparent bg)
            function setPixel(x, y, a) {
                if (x < 0 || x >= sz || y < 0 || y >= sz) return;
                const idx = (y * sz + x) * 4;
                data[idx] = 255; data[idx+1] = 255; data[idx+2] = 255; data[idx+3] = a;
            }
            function fillCircle(cx, cy, r) {
                for (let dy = -r; dy <= r; dy++) {
                    for (let dx = -r; dx <= r; dx++) {
                        if (dx*dx + dy*dy <= r*r) setPixel(Math.round(cx+dx), Math.round(cy+dy), 255);
                    }
                }
            }
            function drawLine(x0, y0, x1, y1, w) {
                const steps = Math.max(Math.abs(x1-x0), Math.abs(y1-y0)) * 2;
                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const x = x0 + (x1-x0)*t, y = y0 + (y1-y0)*t;
                    fillCircle(Math.round(x), Math.round(y), w);
                }
            }
            // Person: head, body, arms, legs
            fillCircle(sz/2, sz*0.20, sz*0.10);       // head
            drawLine(sz/2, sz*0.32, sz/2, sz*0.58, 2);  // body
            drawLine(sz*0.28, sz*0.42, sz*0.72, sz*0.42, 1); // arms
            drawLine(sz/2, sz*0.58, sz*0.30, sz*0.85, 1);  // left leg
            drawLine(sz/2, sz*0.58, sz*0.70, sz*0.85, 1);  // right leg
            map.addImage('person-icon', { width: sz, height: sz, data: data }, { sdf: true });
        }

        map.addLayer({
            id: 'sim-users-dots',
            type: 'symbol',
            source: 'sim-users',
            layout: {
                'icon-image': 'person-icon',
                'icon-size': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 0.18,
                    13, 0.4,
                    16, 0.65
                ],
                'icon-allow-overlap': true,
                'icon-ignore-placement': true,
                // Show role label at higher zoom
                'text-field': ['step', ['zoom'], '', 14, ['get', 'role']],
                'text-size': 9,
                'text-offset': [0, 1.2],
                'text-allow-overlap': false,
                'text-optional': true
            },
            paint: {
                'icon-color': [
                    'step', ['get', 'signal'],
                    '#e74c3c',
                    -100, '#f39c12',
                    -80, '#2ecc71'
                ],
                'icon-opacity': 0.85,
                'text-color': '#ffffff',
                'text-halo-color': 'rgba(0,0,0,0.7)',
                'text-halo-width': 1
            }
        });
    }

    // User density heatmap layer (hidden by default)
    if (!map.getLayer('sim-users-heatmap')) {
        map.addLayer({
            id: 'sim-users-heatmap',
            type: 'heatmap',
            source: 'sim-users',
            paint: {
                'heatmap-weight': [
                    'interpolate', ['linear'], ['get', 'traffic'],
                    0, 0.1,
                    5, 0.5,
                    50, 1
                ],
                'heatmap-intensity': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 1, 13, 3
                ],
                'heatmap-color': [
                    'interpolate', ['linear'], ['heatmap-density'],
                    0, 'rgba(0,0,0,0)',
                    0.15, '#2c3e50',
                    0.3, '#8e44ad',
                    0.5, '#e74c3c',
                    0.7, '#f39c12',
                    1, '#ffffff'
                ],
                'heatmap-radius': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 8, 13, 20, 16, 30
                ],
                'heatmap-opacity': 0.8
            },
            layout: { 'visibility': 'none' }
        });
    }

    // Connection lines source + layer
    if (!map.getSource('sim-lines')) {
        map.addSource('sim-lines', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] }
        });
    }

    if (!map.getLayer('sim-lines-layer')) {
        map.addLayer({
            id: 'sim-lines-layer',
            type: 'line',
            source: 'sim-lines',
            paint: {
                'line-color': [
                    'step', ['get', 'signal'],
                    '#e74c3c',
                    -100, '#f39c12',
                    -80, '#2ecc71'
                ],
                'line-width': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 0.5,
                    13, 1.5,
                    16, 3
                ],
                'line-opacity': [
                    'interpolate', ['linear'], ['zoom'],
                    9, 0.1,
                    13, 0.4,
                    16, 0.7
                ]
            },
            layout: { 'visibility': 'none' },
            minzoom: 11
        });
    }
}

function cleanupSimulationLayers(map) {
    const layers = ['sim-users-dots', 'sim-users-heatmap', 'sim-lines-layer', 'sim-station-overlay', 'sim-handover-arcs', 'sim-handover-dots'];
    layers.forEach(id => {
        if (map.getLayer(id)) map.removeLayer(id);
    });
    if (map.getSource('sim-users')) map.removeSource('sim-users');
    if (map.getSource('sim-lines')) map.removeSource('sim-lines');
    if (map.getSource('sim-station-stats')) map.removeSource('sim-station-stats');
    if (map.getSource('sim-handovers')) map.removeSource('sim-handovers');

    // Restore original station layers
    if (map.getLayer('stations-3d-pillars')) {
        map.setPaintProperty('stations-3d-pillars', 'fill-extrusion-opacity', 0.7);
    }
    if (map.getLayer('stations-heatmap')) {
        map.setLayoutProperty('stations-heatmap', 'visibility', 'visible');
    }
}

let _simPopup = null;

function setupSimUserPopup(map) {
    // Click on user dot in sim mode => show info popup
    map.on('click', 'sim-users-dots', (e) => {
        if (!isSimMode || !e.features || !e.features.length) return;
        e.originalEvent.stopPropagation();
        const p = e.features[0].properties;
        const coords = e.features[0].geometry.coordinates.slice();

        const signalColor = p.signal > -80 ? '#2ecc71' : p.signal > -100 ? '#f39c12' : '#e74c3c';
        const signalLabel = p.signal > -80 ? 'Good' : p.signal > -100 ? 'Fair' : 'Poor';
        const moveIcon = p.movement === 'stationary' || p.movement === 'stay' ? '🏠' : p.movement === 'walking' ? '🚶' : p.movement === 'driving' ? '🚗' : '📍';
        const roleLabel = p.role ? p.role.replace(/_/g, ' ') : 'unknown';

        let html = `<div style="font-family:'Courier New',monospace; font-size:11px; min-width:180px;">`;
        html += `<div style="font-weight:bold; color:#a29bfe; border-bottom:1px solid #444; padding-bottom:3px; margin-bottom:4px;">👤 ${p.user_id}</div>`;
        html += `<div style="color:#fdcb6e; margin-bottom:2px;">💼 ${roleLabel}</div>`;
        html += `<div style="color:#888; margin-bottom:2px;">${moveIcon} ${p.movement || 'unknown'}</div>`;
        html += `<div>Signal: <span style="color:${signalColor}; font-weight:bold;">${p.signal} dBm</span> (${signalLabel})</div>`;
        html += `<div>Traffic: <span style="color:#00cec9;">${Number(p.traffic).toFixed(2)} MB</span></div>`;
        if (p.app_name) html += `<div>App: <span style="color:#fdcb6e;">${p.app_name}</span> <span style="color:#888; font-size:10px;">(${p.app_category})</span></div>`;
        else if (p.app_category) html += `<div>App: <span style="color:#fdcb6e;">${p.app_category}</span></div>`;
        if (p.handover === 1 || p.handover === '1') html += `<div style="color:#a29bfe; margin-top:3px;">🔄 Handover occurred</div>`;
        html += `</div>`;

        if (_simPopup) _simPopup.remove();
        _simPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: true, className: 'cyber-popup', maxWidth: '220px' })
            .setLngLat(coords)
            .setHTML(html)
            .addTo(map);
    });

    map.on('mouseenter', 'sim-users-dots', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'sim-users-dots', () => { if (isSimMode) map.getCanvas().style.cursor = ''; });
}

function prefetchAdjacentSnapshots(currentIndex) {
    // Prefetch next 2 snapshots in background for smoother playback
    const toFetch = [currentIndex + 1, currentIndex + 2].filter(i => i < simTimeSlots && !simSnapshotCache[i]);
    toFetch.forEach(i => {
        fetchSimulationSnapshot(i).then(data => {
            if (data && !data.error && !simSnapshotCache[i]) {
                simSnapshotCache[i] = data;
            }
        }).catch(() => {});
    });
}

let _simDebounceTimer = null;

async function updateSimulationSnapshot(map, timeIndex) {
    // Check cache first
    let data = simSnapshotCache[timeIndex];
    if (!data) {
        data = await fetchSimulationSnapshot(timeIndex);
        if (!data || data.error) {
            console.error('[Sim] Snapshot error:', data?.error);
            return;
        }
        // Cache (keep max 20 snapshots)
        simSnapshotCache[timeIndex] = data;
        const keys = Object.keys(simSnapshotCache);
        if (keys.length > 20) {
            delete simSnapshotCache[keys[0]];
        }
        // Prefetch adjacent snapshots in background
        prefetchAdjacentSnapshots(timeIndex);
    }

    simCurrentTime = timeIndex;

    // Build user point features
    const pointFeatures = [];
    const lineFeatures = [];

    for (const u of data.users) {
        // u = [lng, lat, base_id, signal_dbm, traffic_mb, handover_flag, user_id, movement, app_category, role, app_name]
        const lng = u[0], lat = u[1], baseId = u[2], signal = u[3], traffic = u[4], handover = u[5] || 0;
        const userId = u[6] || '', movement = u[7] || '', appCat = u[8] || '';
        const role = u[9] || '', appName = u[10] || '';

        pointFeatures.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lng, lat] },
            properties: { signal, traffic, base_id: baseId, handover, user_id: userId, movement, app_category: appCat, role, app_name: appName }
        });

        // Build connection line if station loc is known
        if (simStationLocs) {
            const stationLoc = simStationLocs[String(baseId)];
            if (stationLoc) {
                lineFeatures.push({
                    type: 'Feature',
                    geometry: {
                        type: 'LineString',
                        coordinates: [[lng, lat], stationLoc]
                    },
                    properties: { signal, base_id: baseId }
                });
            }
        }
    }

    // Build station overlay features (color by user count)
    const stationOverlayFeatures = [];
    if (data.station_stats && globalStationData) {
        const stationLocMap = {};
        globalStationData.forEach(s => { stationLocMap[s.id] = s.loc; });
        for (const [hexId, stats] of Object.entries(data.station_stats)) {
            const loc = stationLocMap[hexId];
            if (loc) {
                stationOverlayFeatures.push({
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: [loc[0], loc[1]] },
                    properties: {
                        id: hexId,
                        users: stats.users,
                        traffic: stats.traffic,
                        avg_signal: stats.avg_signal,
                        cells: stats.cells || 1
                    }
                });
            }
        }
    }

    // Update sources
    const usersGeo = { type: 'FeatureCollection', features: pointFeatures };
    const linesGeo = { type: 'FeatureCollection', features: lineFeatures };
    const stationStatsGeo = { type: 'FeatureCollection', features: stationOverlayFeatures };

    if (map.getSource('sim-users')) map.getSource('sim-users').setData(usersGeo);
    if (map.getSource('sim-lines')) map.getSource('sim-lines').setData(linesGeo);
    if (map.getSource('sim-station-stats')) map.getSource('sim-station-stats').setData(stationStatsGeo);

    // Build handover arc features
    const handoverArcFeatures = [];
    if (data.handovers) {
        for (const ho of data.handovers) {
            // ho = [user_lng, user_lat, old_stn_lng, old_stn_lat, new_stn_lng, new_stn_lat]
            handoverArcFeatures.push({
                type: 'Feature',
                geometry: {
                    type: 'LineString',
                    coordinates: [
                        [ho[2], ho[3]],  // old station
                        [ho[0], ho[1]],  // user (midpoint)
                        [ho[4], ho[5]]   // new station
                    ]
                },
                properties: {}
            });
        }
    }
    const handoverGeo = { type: 'FeatureCollection', features: handoverArcFeatures };
    if (map.getSource('sim-handovers')) map.getSource('sim-handovers').setData(handoverGeo);

    // Update UI
    const timeDisplay = document.getElementById('sim-time-display');
    const userCount = document.getElementById('sim-user-count');
    if (timeDisplay) {
        const day = Math.floor(timeIndex / 48) + 1;
        const slotInDay = timeIndex % 48;
        const hour = Math.floor(slotInDay / 2);
        const min = (slotInDay % 2) * 30;
        timeDisplay.textContent = `Day ${day} ${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
    }
    if (userCount) {
        const hoCount = data.handover_count || 0;
        userCount.textContent = `${data.total_users.toLocaleString()} users` + (hoCount > 0 ? ` | ${hoCount} handovers` : '');
    }

    // Also update the main time display
    const mainDisplay = document.getElementById('time-display');
    if (mainDisplay && isSimMode) {
        const day = Math.floor(timeIndex / 48) + 1;
        const slotInDay = timeIndex % 48;
        const hour = Math.floor(slotInDay / 2);
        const min = (slotInDay % 2) * 30;
        mainDisplay.innerText = `Day ${String(day).padStart(2, '0')} - ${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
    }

    // Auto-refresh station panel if a station is selected
    if (simSelectedStationHexId) {
        updateSimStationPanel();
    }
}

/**
 * Update the left station panel with simulation stats for the currently selected station.
 * Called on station click AND on timeline change.
 */
function updateSimStationPanel() {
    if (!simSelectedStationHexId) return;
    const coords = simSelectedStationCoords;
    const id = simSelectedStationHexId;

    // station_stats now uses hex ID directly (after backend merge)
    const snapshot = simSnapshotCache[simCurrentTime];
    let stStats = null;
    if (snapshot && snapshot.station_stats) {
        stStats = snapshot.station_stats[id];
    }

    // Time label
    const day = Math.floor(simCurrentTime / 48) + 1;
    const slotInDay = simCurrentTime % 48;
    const hour = Math.floor(slotInDay / 2);
    const min = (slotInDay % 2) * 30;
    const timeLabel = `Day ${day} ${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`;

    let html = `<div style="margin-top:10px;">`;
    html += `<p><strong>Longitude:</strong> ${coords[0].toFixed(4)}</p>`;
    html += `<p><strong>Latitude:</strong> ${coords[1].toFixed(4)}</p>`;
    html += `<hr style="border:0; border-top:1px solid #444; margin:5px 0;">`;
    html += `<p style="font-size:11px; color:#888; margin-bottom:6px;">⏱ ${timeLabel}</p>`;
    if (stStats) {
        // PRB utilization estimate: ~2 PRBs per user, 100 total PRBs
        const prbUtil = Math.min(100, Math.round((stStats.users * 2 / 100) * 100));
        const prbColor = prbUtil > 80 ? '#d63031' : prbUtil > 50 ? '#fdcb6e' : '#00b894';
        html += `<p><strong style="color:#ff6348;">Connected Users:</strong> <span style="color:#fff; font-size:16px; font-weight:bold;">${stStats.users}</span></p>`;
        html += `<p><strong style="color:#ff6348;">Total Traffic:</strong> <span style="color:#fff;">${stStats.traffic.toFixed(1)} MB</span></p>`;
        html += `<p><strong style="color:#ff6348;">Avg Signal:</strong> <span style="color:${stStats.avg_signal > -80 ? '#2ecc71' : stStats.avg_signal > -100 ? '#f39c12' : '#e74c3c'};">${stStats.avg_signal} dBm</span></p>`;
        html += `<p><strong style="color:#ff6348;">PRB Utilization:</strong> <span style="color:${prbColor}; font-weight:bold;">${prbUtil}%</span></p>`;
        if (stStats.cells && stStats.cells > 1) {
            html += `<p style="font-size:11px; color:#888; margin-top:4px;">📡 ${stStats.cells} cells at this site</p>`;
        }
    } else {
        html += `<p style="color:#888;">No users connected at this time</p>`;
    }
    html += `</div>`;
    document.getElementById('station-details').innerHTML = html;
}

function setupSimLayerToggles(map) {
    const dotsBtn = document.getElementById('sim-show-dots');
    const linesBtn = document.getElementById('sim-show-lines');
    const heatmapBtn = document.getElementById('sim-show-heatmap');
    const handoverBtn = document.getElementById('sim-show-handovers');

    function toggleLayer(btn, layerIds, key) {
        if (!btn) return;
        btn.onclick = () => {
            simLayerVisibility[key] = !simLayerVisibility[key];
            btn.classList.toggle('active', simLayerVisibility[key]);
            const ids = Array.isArray(layerIds) ? layerIds : [layerIds];
            ids.forEach(id => {
                if (map.getLayer(id)) {
                    map.setLayoutProperty(id, 'visibility', simLayerVisibility[key] ? 'visible' : 'none');
                }
            });
        };
    }

    toggleLayer(dotsBtn, 'sim-users-dots', 'dots');
    toggleLayer(linesBtn, 'sim-lines-layer', 'lines');
    toggleLayer(heatmapBtn, 'sim-users-heatmap', 'heatmap');
    toggleLayer(handoverBtn, ['sim-handover-arcs', 'sim-handover-dots'], 'handovers');
}

function setupSimTimeline(map) {
    const slider = document.getElementById('time-slider');
    const playBtn = document.getElementById('play-btn');
    if (!slider || !playBtn) return;

    // Override slider input for simulation
    const simSliderHandler = (e) => {
        if (!isSimMode) return;
        e.stopPropagation();
        simIsPlaying = false;
        if (simAnimFrameId) { clearTimeout(simAnimFrameId); simAnimFrameId = null; }
        playBtn.innerText = '\u25b6';

        const val = parseInt(e.target.value);
        // Debounce API calls when scrubbing
        if (_simDebounceTimer) clearTimeout(_simDebounceTimer);
        _simDebounceTimer = setTimeout(() => {
            updateSimulationSnapshot(map, val);
        }, 80);
    };

    slider.addEventListener('input', simSliderHandler);

    // Override play button for simulation
    const origPlayClick = playBtn.onclick;
    playBtn.onclick = () => {
        if (!isSimMode) {
            if (origPlayClick) origPlayClick();
            return;
        }

        simIsPlaying = !simIsPlaying;
        playBtn.innerText = simIsPlaying ? '\u23f8' : '\u25b6';

        if (simIsPlaying) {
            const simPlay = async () => {
                if (!simIsPlaying || !isSimMode) return;
                let val = parseInt(slider.value);
                val = (val + 1) % simTimeSlots;
                slider.value = val;
                await updateSimulationSnapshot(map, val);
                if (simIsPlaying && isSimMode) {
                    simAnimFrameId = setTimeout(simPlay, 300);
                }
            };
            simPlay();
        } else {
            if (simAnimFrameId) { clearTimeout(simAnimFrameId); simAnimFrameId = null; }
        }
    };
}

// ==========================================
// Server Settings Functions
// ==========================================
function setupServerSettings() {
    const modal = document.getElementById('settings-modal');
    const settingsBtn = document.getElementById('settings-btn');
    const closeBtn = document.getElementById('close-settings');
    const testBtn = document.getElementById('test-connection');
    const saveBtn = document.getElementById('save-settings');
    
    const hostInput = document.getElementById('server-host');
    const portInput = document.getElementById('server-port');
    const protocolSelect = document.getElementById('server-protocol');
    const currentApiSpan = document.getElementById('current-api');
    const statusDiv = document.getElementById('connection-status');
    
    // Load current settings
    hostInput.value = SERVER_CONFIG.host;
    portInput.value = SERVER_CONFIG.port;
    protocolSelect.value = SERVER_CONFIG.protocol;
    updateCurrentApi();
    
    // Open modal
    settingsBtn.addEventListener('click', () => {
        modal.style.display = 'flex';
        updateCurrentApi();
    });
    
    // Close modal
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
        statusDiv.className = 'status-indicator';
        statusDiv.textContent = '';
    });
    
    // Close on outside click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
            statusDiv.className = 'status-indicator';
            statusDiv.textContent = '';
        }
    });
    
    // Update API display when inputs change
    [hostInput, portInput, protocolSelect].forEach(el => {
        el.addEventListener('input', updateCurrentApi);
    });
    
    function updateCurrentApi() {
        const api = `${protocolSelect.value}://${hostInput.value}:${portInput.value}/api`;
        currentApiSpan.textContent = api;
    }
    
    // Test connection
    testBtn.addEventListener('click', async () => {
        const testConfig = {
            host: hostInput.value,
            port: portInput.value,
            protocol: protocolSelect.value
        };
        const testApi = `${testConfig.protocol}://${testConfig.host}:${testConfig.port}/api`;
        
        statusDiv.className = 'status-indicator';
        statusDiv.textContent = 'Testing...';
        
        try {
            const response = await fetch(`${testApi}/stations/locations`, {
                method: 'GET',
                signal: AbortSignal.timeout(5000)
            });
            
            if (response.ok) {
                statusDiv.className = 'status-indicator success';
                statusDiv.textContent = '✓ Connection successful!';
            } else {
                statusDiv.className = 'status-indicator error';
                statusDiv.textContent = `✗ Server error: ${response.status}`;
            }
        } catch (e) {
            statusDiv.className = 'status-indicator error';
            statusDiv.textContent = `✗ Connection failed: ${e.message}`;
        }
    });
    
    // Save settings
    saveBtn.addEventListener('click', () => {
        const newConfig = {
            host: hostInput.value,
            port: portInput.value,
            protocol: protocolSelect.value
        };
        
        localStorage.setItem('serverConfig', JSON.stringify(newConfig));
        alert('Settings saved! The application will reload to apply changes.');
        window.location.reload();
    });
}