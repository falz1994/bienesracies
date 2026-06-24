// Variable global para mantener referencia al mapa
let mapaActual = null;

// Basic debug helpers to capture runtime errors and promise rejections
console.log('bienes-raices.js cargado');
window.addEventListener('error', (e) => {
    console.error('Global error caught:', e.message, 'at', `${e.filename}:${e.lineno}:${e.colno}`, e.error || e);
});
window.addEventListener('unhandledrejection', (e) => {
    console.error('Unhandled Promise rejection:', e.reason);
});

// Ajustes por viewport (mobile/desktop)
function ajustarParaViewport() {
    const w = window.innerWidth || document.documentElement.clientWidth;
    const isMobile = w <= 900;
    window._isMobile = isMobile;
    console.log('ajustarParaViewport: isMobile=', isMobile, 'width=', w);

    const mapEl = document.getElementById('mapa');
    if (mapEl) {
        mapEl.style.height = isMobile ? '50vh' : '60vh';
        mapEl.style.minHeight = '280px';
    }

    // If we have properties loaded and a map, recreate heatmap with mobile options
    if (mapaActual && window._propiedades) {
        try {
            crearHeatmap(window._propiedades);
        } catch (e) {
            console.warn('Error al recrear heatmap en ajuste de viewport:', e);
        }
    }

    try { if (mapaActual) mapaActual.invalidateSize(); } catch (e) {}
}

let _resizeTimeout = null;
window.addEventListener('resize', () => {
    if (_resizeTimeout) clearTimeout(_resizeTimeout);
    _resizeTimeout = setTimeout(ajustarParaViewport, 150);
});

// Funciones de utilidad
function formatearPrecioCluster(precio) {
    if (precio >= 1000000) return (precio / 1000000).toFixed(1) + 'M';
    if (precio >= 1000) return (precio / 1000).toFixed(0) + 'K';
    return precio.toFixed(0);
}

function formatearMoneda(valor) {
    return valor.toLocaleString('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    });
}

// Función para actualizar la tabla de fuentes
function actualizarTablaFuentes(sourceStats) {
    const tablaFuentes = document.getElementById('tabla-fuentes');
    if (!tablaFuentes) return;

    const datos = Object.entries(sourceStats)
        .map(([source, count]) => ({ name: source, value: count }))
        .sort((a, b) => b.value - a.value);

    tablaFuentes.innerHTML = datos.map(item => `
        <tr>
            <td>${item.name}</td>
            <td>${item.value.toLocaleString()}</td>
        </tr>
    `).join('');
}

// Función para calcular y mostrar el precio promedio por metro cuadrado
function actualizarPrecioPromedioM2(precioPromedioM2) {
    const elementoPrecioM2 = document.getElementById('precio-promedio-m2');
    if (elementoPrecioM2) {
        elementoPrecioM2.textContent = `$${formatearMoneda(precioPromedioM2)}`;
    }
}

// Fetch CSV text with multiple fallback paths and file-upload fallback
async function fetchCsvTextWithFallback(path) {
    if (window._csvCache && window._csvCache.path === path && window._csvCache.text) {
        return window._csvCache.text;
    }

    // Try candidate URLs (include encoded space variant explicitly)
    const encodedPath = path.replace(/ /g, '%20');
    const candidates = [
        encodedPath,
        path,
        encodeURI(path),
        './' + encodedPath,
        './' + path,
        '/' + encodedPath,
        '/' + path,
        encodedPath + '?_=' + Date.now(),
        path + '?_=' + Date.now()
    ];

    console.info('Attempting CSV load, candidates:', candidates);

    for (const p of candidates) {
        try {
            const res = await fetch(p, { cache: 'no-cache' });
            console.info('fetch', p, 'status', res.status, 'ok', res.ok);
            if (res) {
                const ct = res.headers.get('content-type') || '';
                if (ct.includes('application/json')) {
                    console.warn('Response appears to be JSON (unexpected):', p, ct);
                }
            }
            if (res && res.ok) {
                const txt = await res.text();
                if (txt && txt.trim().length > 10) {
                    const sample = txt.trim().slice(0, 500);
                    const lines = txt.trim().split(/\r?\n/);
                    if (sample.startsWith('<') || sample.startsWith('{') || sample.startsWith('[') || lines.length < 2 || (!lines[0].includes(',') && !lines[0].includes(';'))) {
                        console.warn('Fetched content does not look like CSV, skipping', p, sample.slice(0,200));
                    } else {
                        window._csvCache = { path, text: txt, ts: Date.now() };
                        return txt;
                    }
                } else {
                    console.warn('Fetched text too short or empty for', p);
                }
            }
        } catch (e) {
            console.warn('fetch failed for', p, e);
        }
    }

    // Fallback to prompting the user to upload a local CSV
    try {
        const txt = await promptUserForCsvFile();
        if (txt && txt.trim().length > 0) {
            window._csvCache = { path, text: txt, ts: Date.now() };
            return txt;
        }
    } catch (e) {
        console.warn('No file selected or failed to read file', e);
    }

    // Show user-visible error
    try {
        const errBanner = document.createElement('div');
        errBanner.style.position = 'fixed';
        errBanner.style.left = '50%';
        errBanner.style.top = '8px';
        errBanner.style.transform = 'translateX(-50%)';
        errBanner.style.background = '#b91c1c';
        errBanner.style.color = 'white';
        errBanner.style.padding = '8px 12px';
        errBanner.style.borderRadius = '6px';
        errBanner.style.zIndex = 99999;
        errBanner.textContent = 'Error: no se pudo cargar el CSV. Ver consola para detalles.';
        document.body.appendChild(errBanner);
        setTimeout(() => errBanner.remove(), 8000);
    } catch (e) {}

    console.error('fetchCsvTextWithFallback: no candidate succeeded, candidates:', candidates);
    throw new Error('Could not load CSV from network or file.');
}

function promptUserForCsvFile() {
    return new Promise((resolve, reject) => {
        let input = document.getElementById('csv-file-input');
        if (!input) {
            input = document.createElement('input');
            input.type = 'file';
            input.accept = '.csv,text/csv';
            input.id = 'csv-file-input';
            input.style.position = 'fixed';
            input.style.left = '-9999px';
            document.body.appendChild(input);
        }

        input.onchange = function () {
            const file = input.files && input.files[0];
            if (!file) return reject(new Error('No file selected'));
            const reader = new FileReader();
            reader.onload = function (evt) { resolve(evt.target.result); };
            reader.onerror = function (err) { reject(err); };
            reader.readAsText(file, 'utf-8');
        };

        try {
            const info = document.createElement('div');
            info.textContent = 'Selecciona el CSV local si la carga automática falla.';
            info.style.position = 'fixed';
            info.style.left = '50%';
            info.style.top = '6px';
            info.style.transform = 'translateX(-50%)';
            info.style.background = 'rgba(0,0,0,0.7)';
            info.style.color = '#fff';
            info.style.padding = '6px 10px';
            info.style.borderRadius = '6px';
            info.style.zIndex = 99999;
            document.body.appendChild(info);
            setTimeout(() => info.remove(), 3500);
        } catch (e) {}

        input.click();
    });
}

// Función para crear el mapa y sus marcadores
function crearMapa(propiedadesConCoordenadas) {
    const contenedorMapa = document.getElementById('mapa');
    
    // Si existe un mapa previo, destruirlo
    if (mapaActual) {
        mapaActual.remove();
        mapaActual = null;
    }

    // Crear nuevo mapa
    mapaActual = L.map('mapa').setView([12.1149, -86.2362], 12);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(mapaActual);

    const markers = L.markerClusterGroup({
        iconCreateFunction: function(cluster) {
            const markers = cluster.getAllChildMarkers();
            const precioPromedio = markers.reduce((sum, marker) => 
                sum + (marker.propiedad?.precio || 0), 0) / markers.length;
            
            const precioFormateado = formatearPrecioCluster(precioPromedio);
            let size = markers.length > 50 ? 'large' : markers.length > 20 ? 'medium' : 'small';
            
            return L.divIcon({
                html: `
                    <div class="cluster-icon ${size}">
                        <div class="cluster-price">$${precioFormateado}</div>
                        <div class="cluster-count">${markers.length}</div>
                    </div>
                `,
                className: 'custom-cluster-icon',
                iconSize: L.point(40, 40)
            });
        }
    });

    propiedadesConCoordenadas.forEach(propiedad => {
        const precioFormateado = formatearPrecioCluster(propiedad.precio);
        const marker = L.marker(propiedad.coordenadas, {
            icon: L.divIcon({
                html: `
                    <div class="marker-icon">
                        <i class="fas fa-home"></i>
                        <span>$${precioFormateado}</span>
                    </div>
                `,
                className: 'custom-marker-icon',
                iconSize: [40, 40],
                iconAnchor: [20, 40],
                popupAnchor: [0, -40]
            })
        });
        marker.propiedad = propiedad;
        
        marker.bindPopup(`
            <div class="popup-content">
                <h3>$${formatearMoneda(propiedad.precio)}</h3>
                <p>${propiedad.ubicacion}</p>
                ${propiedad.enlace ? `<a href="${propiedad.enlace}" target="_blank">Visitar Listado</a>` : ''}
            </div>
        `);
        
        markers.addLayer(marker);
    });

    mapaActual.addLayer(markers);
    try { console.log('crearMapa: marcadores añadidos=', markers.getLayers().length); } catch (e) {}
    
    // Forzar un reajuste del tamaño del mapa
    setTimeout(() => {
        mapaActual.invalidateSize();
    }, 100);

    return mapaActual;
}

// Crear heatmap (capa de densidad) basada en los marcadores existentes
function crearHeatmap(propiedades) {
    if (!mapaActual) {
        console.warn('Mapa no inicializado: no se puede crear heatmap');
        return;
    }

    // Remover heat previo si existe
    if (window._heatLayer) {
        try { mapaActual.removeLayer(window._heatLayer); } catch (e) {}
    }

    // Use price as intensity (0 = cheapest -> 1 = most expensive) and apply a non-linear scaling
    const minPrice = (typeof window._precioMin === 'number') ? window._precioMin : 0;
    const maxPrice = (typeof window._precioMax === 'number') ? window._precioMax : 0;
    const range = Math.max(0, maxPrice - minPrice);

    const puntos = propiedades
        .filter(p => Array.isArray(p.coordenadas) && p.coordenadas.length === 2)
        .map(p => {
            const lat = p.coordenadas[0];
            const lng = p.coordenadas[1];
            const precio = Number(p.precio) || 0;
            let peso = 0.0;
            if (range > 0) {
                peso = (precio - minPrice) / range; // 0..1
            }
            // Apply non-linear scaling to emphasize high prices, then clamp to visible range
            peso = Math.pow(Math.max(0, peso), 1.5) * 1.1;
            peso = Math.max(0.05, Math.min(1, peso));
            return [lat, lng, peso];
        });

    if (puntos.length === 0) {
        console.warn('No hay puntos con coordenadas para heatmap');
        return;
    }

    try { console.log('crearHeatmap: puntos=', puntos.length, 'minPrice=', minPrice, 'maxPrice=', maxPrice); } catch(e) {}

    // Reduced radius/blur and slightly higher minOpacity for crisper hotspots
    const mobile = !!window._isMobile;
    const heatOptions = {
        radius: mobile ? 12 : 18,
        blur: mobile ? 6 : 10,
        maxZoom: 17,
        max: 1.0,
        minOpacity: mobile ? 0.32 : 0.28,
        // Gradient: green (cheaper) -> yellow -> red (more expensive)
        gradient: { 0.0: '#2ecc71', 0.5: '#f1c40f', 1.0: '#e74c3c' }
    };

    const heat = L.heatLayer(puntos, heatOptions);

    window._heatLayer = heat;

    if (!mapaActual._heatControlAdded) {
        const overlays = { 'Heatmap (precio)': heat };
        L.control.layers(null, overlays, { collapsed: false }).addTo(mapaActual);
        mapaActual._heatControlAdded = true;
    }

    heat.addTo(mapaActual);
}

// Función para actualizar los elementos de la UI
function actualizarUI(estadisticasGenerales) {
    const ultimaActualizacionElement = document.getElementById('ultima-actualizacion');
    if (ultimaActualizacionElement && estadisticasGenerales.maxDate) {
        const fechaFormateada = estadisticasGenerales.maxDate.toLocaleDateString('es-ES', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
        ultimaActualizacionElement.textContent = fechaFormateada;
    }
}

// Funciones de obtención de datos
async function obtenerEstadisticasSource() {
    try {
        const csvText = await fetchCsvTextWithFallback('casas en venta/combined11-12.csv');
        
        return new Promise((resolve, reject) => {
            Papa.parse(csvText, {
                header: true,
                skipEmptyLines: true,
                complete: (results) => {
                    const sourceStats = {};
                    
                    for (let i = 0; i < results.data.length; i++) {
                        const row = results.data[i];
                        if (!row.source) continue;
                        
                        const source = row.source.trim();
                        if (source) {
                            sourceStats[source] = (sourceStats[source] || 0) + 1;
                        }
                    }
                    
                    resolve(sourceStats);
                    try { console.log('obtenerEstadisticasSource: filas parseadas=', results.data.length, 'fuentes=', Object.keys(sourceStats).length, Object.keys(sourceStats).slice(0,8)); } catch(e) {}
                },
                error: (error) => {
                    console.error('Error parsing CSV:', error);
                    reject(error);
                }
            });
        });
    } catch (error) {
        console.error('Error al obtener estadísticas por source:', error);
        return {};
    }
}

async function obtenerPropiedadesConCoordenadas() {
    try {
        const csvText = await fetchCsvTextWithFallback('casas en venta/combined11-12.csv');
        
        return new Promise((resolve, reject) => {
            Papa.parse(csvText, {
                header: true,
                skipEmptyLines: true,
                complete: (results) => {
                    const propiedades = [];
                    
                    for (let i = 0; i < results.data.length; i++) {
                        const row = results.data[i];
                        if (!row.coordenadas) continue;
                        
                        const coordenadas = row.coordenadas.trim();
                        if (coordenadas && coordenadas.includes(',')) {
                            const [lat, lng] = coordenadas.split(',').map(coord => parseFloat(coord.trim()));
                            if (!isNaN(lat) && !isNaN(lng)) {
                                propiedades.push({
                                    titulo: row.titulo?.trim(),
                                    ubicacion: row.ubicacion?.trim(),
                                    precio: parseFloat(row.precio?.replace(/[^\d.-]/g, '') || 0),
                                    coordenadas: [lat, lng],
                                    enlace: row.enlace?.trim(),
                                    departamento: row.departamento_provincia?.trim() || '',
                                    municipio: row.municipio_ciudad?.trim() || ''
                                });
                            }
                        }
                    }
                    
                    resolve(propiedades);
                    try { console.log('obtenerPropiedadesConCoordenadas: filas parseadas=', results.data.length, 'propiedadesConCoordenadas=', propiedades.length, propiedades[0] || null); } catch(e) {}
                },
                error: (error) => {
                    console.error('Error parsing CSV:', error);
                    reject(error);
                }
            });
        });
    } catch (error) {
        console.error('Error al obtener propiedades con coordenadas:', error);
        return [];
    }
}

async function obtenerEstadisticasGenerales() {
    try {
        const csvText = await fetchCsvTextWithFallback('casas en venta/combined11-12.csv');
        
        return new Promise((resolve, reject) => {
            Papa.parse(csvText, {
                header: true,
                skipEmptyLines: true,
                complete: (results) => {
                    let maxDate = null;
                    let totalPropiedades = 0;
                    let totalPrecio = 0;
                    let totalMetrosCuadrados = 0;
                    let propiedadesConMetros = 0;
                    
                    for (let i = 0; i < results.data.length; i++) {
                        const row = results.data[i];
                        if (!row.precio || !row.source) continue;
                        
                        const precio = parseFloat(row.precio.replace(/[^\d.]/g, ''));
                        const tamanoLote = parseFloat(row.tamano_lote?.replace(/[^\d.]/g, '') || 0);
                        
                        if (!isNaN(precio) && precio > 0) {
                            totalPropiedades++;
                            totalPrecio += precio;
                            
                            if (!isNaN(tamanoLote) && tamanoLote > 0) {
                                totalMetrosCuadrados += tamanoLote;
                                propiedadesConMetros++;
                            }
                        }
                        
                        // Since there's no max_date column, we'll use current date
                        if (!maxDate) {
                            maxDate = new Date();
                        }
                    }
                    
                    const precioPromedioM2 = propiedadesConMetros > 0 ? totalPrecio / totalMetrosCuadrados : 0;
                    
                    mostrarEstadisticasPorDepartamento(results);
                    actualizarPrecioPromedioM2(precioPromedioM2);
                    try { console.log('obtenerEstadisticasGenerales: totalPropiedades=', totalPropiedades, 'precioPromedioM2=', precioPromedioM2); } catch(e) {}
                    
                    resolve({ totalPropiedades, maxDate, precioPromedioM2 });
                },
                error: (error) => {
                    console.error('Error parsing CSV:', error);
                    reject(error);
                }
            });
        });
    } catch (error) {
        console.error('Error al obtener estadísticas generales:', error);
        return { totalPropiedades: 0, maxDate: null, precioPromedioM2: 0 };
    }
}

// Función principal
async function inicializarMapa() {
    try {
        console.log('Iniciando carga de datos...');
        
        const [sourceStats, propiedadesConCoordenadas, estadisticasGenerales] = await Promise.all([
            obtenerEstadisticasSource(),
            obtenerPropiedadesConCoordenadas(),
            obtenerEstadisticasGenerales()
        ]);

        console.log('Datos cargados, actualizando interfaz...');

        try {
            console.log('sourceStats keys:', Object.keys(sourceStats).slice(0,12));
            console.log('propiedadesConCoordenadas count:', propiedadesConCoordenadas.length, propiedadesConCoordenadas[0] || null);
            console.log('estadisticasGenerales:', estadisticasGenerales);
        } catch (e) {}

        // Compute global price range for color scaling (used by clusters and zone layer)
        const precios = propiedadesConCoordenadas.map(p => Number(p.precio)).filter(v => !isNaN(v) && v > 0);
        const precioMin = precios.length ? Math.min(...precios) : 0;
        const precioMax = precios.length ? Math.max(...precios) : 0;
        window._precioMin = precioMin;
        window._precioMax = precioMax;

        // Keep a global reference for recreating heatmap when viewport changes
        window._propiedades = propiedadesConCoordenadas;

        actualizarTablaFuentes(sourceStats);
        // Override last extraction date as requested
        try {
            estadisticasGenerales.maxDate = new Date('2026-01-29');
        } catch (e) {}
        actualizarUI(estadisticasGenerales);
        // Ensure the exact format requested
        const ultimaEl = document.getElementById('ultima-actualizacion');
        if (ultimaEl) ultimaEl.textContent = '1/29/2026';

        if (propiedadesConCoordenadas.length === 0) {
            console.log('No hay propiedades con coordenadas para mostrar');
            return;
        }

        console.log(`Creando mapa con ${propiedadesConCoordenadas.length} propiedades...`);
        crearMapa(propiedadesConCoordenadas);
        // Añadir heatmap (capa de densidad) sin modificar marcadores o clusters
        try {
            crearHeatmap(propiedadesConCoordenadas);
        } catch (e) {
            console.warn('Error al crear heatmap:', e);
        }

        // Ajustes finales según viewport (mobile tweaks)
        try { ajustarParaViewport(); } catch (e) {}

        console.log('Mapa inicializado correctamente');

    } catch (error) {
        console.error('Error al inicializar el mapa:', error);
    }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM cargado, iniciando aplicación...');
    inicializarMapa();
});

function mostrarInfo(id) {
    const popup = document.getElementById(id);
    if (popup) {
        popup.style.display = popup.style.display === 'block' ? 'none' : 'block';
    }
}

function mostrarEstadisticasPorDepartamento(results) {
    console.log('Iniciando procesamiento de estadísticas por departamento');
    console.log('Datos recibidos:', results.data.length, 'filas');
    console.log('Primera fila de ejemplo:', results.data[0]);
    
    const departamentos = {};
    
    // Procesar datos
    for (let i = 0; i < results.data.length; i++) {
        const row = results.data[i];
        
        // Usar la estructura actual del CSV
        const departamento = row.departamento_provincia?.replace(/\n/g, '').trim() || 'No especificado';
        const sector = row.municipio_ciudad?.trim() || 'No especificado';
        const precioStr = row.precio?.trim();
        const tamanoLoteStr = row.tamano_lote?.trim();
        
        if (!precioStr) continue;
        
        const precio = parseFloat(precioStr.replace(/[^\d.]/g, ''));
        const tamanoLote = parseFloat(tamanoLoteStr?.replace(/[^\d.]/g, '') || 0);
        
        if (!isNaN(precio) && precio > 0) {
            // Inicializar departamento si no existe
            if (!departamentos[departamento]) {
                departamentos[departamento] = {
                    conteo: 0,
                    total: 0,
                    min: Infinity,
                    max: -Infinity,
                    totalMetrosCuadrados: 0,
                    sectores: {}
                };
            }
            
            // Inicializar sector si no existe
            if (!departamentos[departamento].sectores[sector]) {
                departamentos[departamento].sectores[sector] = {
                    conteo: 0,
                    total: 0,
                    totalMetrosCuadrados: 0
                };
            }
            
            // Actualizar estadísticas del departamento
            departamentos[departamento].conteo++;
            departamentos[departamento].total += precio;
            departamentos[departamento].min = Math.min(departamentos[departamento].min, precio);
            departamentos[departamento].max = Math.max(departamentos[departamento].max, precio);
            
            if (!isNaN(tamanoLote) && tamanoLote > 0) {
                departamentos[departamento].totalMetrosCuadrados += tamanoLote;
            }
            
            // Actualizar estadísticas del sector
            departamentos[departamento].sectores[sector].conteo++;
            departamentos[departamento].sectores[sector].total += precio;
            
            if (!isNaN(tamanoLote) && tamanoLote > 0) {
                departamentos[departamento].sectores[sector].totalMetrosCuadrados += tamanoLote;
            }
        }
    }
    
    console.log('Departamentos procesados:', Object.keys(departamentos));

    const tablaDepartamentos = document.getElementById('tabla-departamentos');
    if (!tablaDepartamentos) {
        console.error('No se encontró el elemento tabla-departamentos');
        return;
    }
    // Expose departamentos for modal usage
    window._departamentosData = departamentos;
    window._departamentosModalMap = window._departamentosModalMap || {};

    const html = Object.entries(departamentos)
        .sort((a, b) => b[1].conteo - a[1].conteo)
        .map(([depto, stats]) => {
            const promedio = stats.total / stats.conteo;
            const precioPorM2 = stats.totalMetrosCuadrados > 0 ? stats.total / stats.totalMetrosCuadrados : 0;

            // Generar HTML para los sectores
            const sectoresHtml = Object.entries(stats.sectores)
                .sort((a, b) => b[1].conteo - a[1].conteo)
                .map(([sector, sectorStats]) => {
                    const promedioSector = sectorStats.total / sectorStats.conteo;
                    const precioPorM2Sector = sectorStats.totalMetrosCuadrados > 0 ? sectorStats.total / sectorStats.totalMetrosCuadrados : 0;
                    return `
                        <tr class="sector-row">
                            <td>${sector}</td>
                            <td>${sectorStats.conteo.toLocaleString()}</td>
                            <td>$${formatearMoneda(promedioSector)}</td>
                            <td>${precioPorM2Sector > 0 ? '$' + formatearMoneda(precioPorM2Sector) : 'N/A'}</td>
                        </tr>
                    `;
                }).join('');

            const safeId = 'sectores-' + depto.replace(/[^a-z0-9]/gi, '_');
            // store mapping for modal lookups
            window._departamentosModalMap[safeId] = { name: depto, stats };

            return `
                <tr class="departamento-row">
                    <td>
                        <div class="departamento-header" onclick="toggleSectores('${safeId}')">
                            <strong>${depto}</strong>
                        </div>
                    </td>
                    <td>${stats.conteo.toLocaleString()}</td>
                    <td>$${formatearMoneda(promedio)}</td>
                    <td>${precioPorM2 > 0 ? '$' + formatearMoneda(precioPorM2) : 'N/A'}</td>
                    <td>$${formatearMoneda(isFinite(stats.min) ? stats.min : 0)}</td>
                    <td>$${formatearMoneda(isFinite(stats.max) ? stats.max : 0)}</td>
                </tr>
                <tr id="${safeId}" class="sectores-container" style="display:none;">
                    <td colspan="6">
                        <table class="sectores-table">
                            <thead>
                                <tr>
                                    <th>Sector</th>
                                    <th>Listados</th>
                                    <th>Precio Promedio</th>
                                    <th>Precio por m²</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${sectoresHtml || '<tr><td colspan="4">No hay datos</td></tr>'}
                            </tbody>
                        </table>
                    </td>
                </tr>
            `;
        }).join('');

    tablaDepartamentos.innerHTML = html;

    // Define toggle function (desktop inline expansion) and mobile modal behavior
    window.toggleSectores = function(id) {
        // If on mobile, open modal instead of inline expansion
        if (window._isMobile) {
            try { openDepartmentModal(id); return; } catch (e) { console.warn('openDepartmentModal failed', e); }
        }

        const el = document.getElementById(id);
        if (!el) return;
        if (el.style.display === 'none' || el.style.display === '') {
            el.style.display = 'table-row';
        } else {
            el.style.display = 'none';
        }
    };

    // Modal helpers
    window.openDepartmentModal = function(safeId) {
        const map = window._departamentosModalMap || {};
        const data = map[safeId];
        if (!data) return console.warn('No hay datos para', safeId);

        const overlay = document.getElementById('modal-overlay');
        const titleEl = document.getElementById('modal-title');
        const bodyEl = document.getElementById('modal-body');
        const backBtn = document.getElementById('modal-back');

        titleEl.textContent = `${data.name} — Sectores`;
        backBtn.style.display = 'none';

        const sectores = data.stats.sectores || {};
        const rows = Object.entries(sectores)
            .sort((a,b)=>b[1].conteo - a[1].conteo)
            .map(([sector, sStats])=>{
                const promedioSector = sStats.total / sStats.conteo;
                const precioPorM2Sector = sStats.totalMetrosCuadrados > 0 ? sStats.total / sStats.totalMetrosCuadrados : 0;
                const escSector = sector.replace(/'/g, "\\'");
                return `
                    <tr class="sector-row" onclick="openSectorDetail('${safeId}','${escSector}')">
                        <td>${sector}</td>
                        <td>${sStats.conteo.toLocaleString()}</td>
                        <td>$${formatearMoneda(promedioSector)}</td>
                        <td>${precioPorM2Sector > 0 ? '$' + formatearMoneda(precioPorM2Sector) : 'N/A'}</td>
                    </tr>
                `;
            }).join('') || '<tr><td colspan="4">No hay datos</td></tr>';

        bodyEl.innerHTML = `
            <table class="sectores-table">
                <thead>
                    <tr>
                        <th>Sector</th>
                        <th>Listados</th>
                        <th>Precio Promedio</th>
                        <th>Precio por m²</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;

        overlay.style.display = 'flex';
        document.body.classList.add('modal-open');

        document.getElementById('modal-close').onclick = closeModal;
        document.getElementById('modal-back').onclick = function(){ openDepartmentModal(safeId); };
    }

    window.openSectorDetail = function(safeId, sectorName) {
        const map = window._departamentosModalMap || {};
        const data = map[safeId];
        if (!data) return console.warn('No dept data for', safeId);
        const sStats = data.stats.sectores && data.stats.sectores[sectorName];
        if (!sStats) return console.warn('No sector stats for', sectorName);

        const overlay = document.getElementById('modal-overlay');
        const titleEl = document.getElementById('modal-title');
        const bodyEl = document.getElementById('modal-body');
        const backBtn = document.getElementById('modal-back');

        backBtn.style.display = 'inline-block';
        titleEl.textContent = `${sectorName} — Detalle`;

        const promedioSector = sStats.total / sStats.conteo;
        const precioPorM2Sector = sStats.totalMetrosCuadrados > 0 ? sStats.total / sStats.totalMetrosCuadrados : 0;

        bodyEl.innerHTML = `
            <div class="sector-detail">
                <p><strong>Listados:</strong> ${sStats.conteo.toLocaleString()}</p>
                <p><strong>Precio Promedio:</strong> $${formatearMoneda(promedioSector)}</p>
                <p><strong>Precio por m²:</strong> ${precioPorM2Sector > 0 ? '$' + formatearMoneda(precioPorM2Sector) : 'N/A'}</p>
                <p class="muted">Haz clic en "Atrás" para volver a la lista de sectores.</p>
            </div>
        `;

        overlay.style.display = 'flex';
        document.body.classList.add('modal-open');

        document.getElementById('modal-close').onclick = closeModal;
        document.getElementById('modal-back').onclick = function(){ openDepartmentModal(safeId); };
    }

    window.closeModal = function() {
        const overlay = document.getElementById('modal-overlay');
        if (!overlay) return;
        overlay.style.display = 'none';
        document.body.classList.remove('modal-open');
        const bodyEl = document.getElementById('modal-body');
        if (bodyEl) bodyEl.innerHTML = '';
    }

}
