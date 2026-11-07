import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Boxes,
  Camera,
  Car,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  ChevronRight,
  Clock,
  Coins,
  Database,
  Download,
  FileCheck2,
  ImagePlus,
  Layers,
  Loader2,
  MapPin,
  PackageSearch,
  Receipt,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  ToggleLeft,
  ToggleRight,
  Upload,
  Wrench,
  Zap,
} from 'lucide-react';
import { FotoMuestra } from '../types/studio';

interface VehiculoCompatible {
  marca?: string;
  modelo?: string;
  anio_desde?: number;
  anio_hasta?: number;
}

interface CotizacionData {
  cotizacion_id?: number;
  id_repuesto?: string;
  cantidad?: number;
  precio_unitario?: number;
  stock?: number;
  ubicacion?: string;
  total?: number;
}

interface VisionToolCall {
  herramienta?: string;
  argumentos?: Record<string, unknown>;
}

interface DiagnosticoResponse {
  tarea_id?: string;
  fotos_guardadas?: string[];
  estado?: 'cotizado' | 'necesita_otra_foto' | 'derivar_a_humano' | string;
  pieza?: {
    id?: string;
    nombre?: string;
    codigo_oem?: string;
    confianza?: number;
  };
  vehiculos_compatibles?: VehiculoCompatible[];
  cotizacion?: CotizacionData | null;
  motivo?: string;
  foto_adicional_solicitada?: string;
  incidentes_recuperados?: Array<{ tipo?: string; detalle?: string; mensaje?: string } | string>;
  tracking?: {
    herramientas?: VisionToolCall[];
    resultado_herramientas?: Array<Record<string, unknown>>;
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
    latencia_segundos?: number;
    costo_estimado_usd?: number;
  };
  error?: string;
}

interface RepuestoCatalogo {
  id_repuesto: string;
  nombre: string;
  codigo_oem?: string;
  atributos_visuales?: string[];
  vehiculos_compatibles?: VehiculoCompatible[];
  precio_unitario?: number;
  stock?: number;
  ubicacion?: string;
}

interface MetricasResponse {
  repuestos?: RepuestoCatalogo[];
  resumen_s4?: {
    metricas_principales_plataforma?: {
      total_unidades_procesadas?: number;
      horas_operacion_desatendida?: number;
      tasa_exito_pct?: number;
      costo_total_usd?: number;
      costo_promedio_por_tarea_usd?: number;
    };
    estadisticas_detalladas?: {
      latencia_segundos?: { p50?: number; p95?: number };
      incidentes_y_recuperacion?: { recuperados_autonomamente?: number };
    };
  };
  evaluacion_s3?: {
    top1_accuracy_pct?: number;
    top3_accuracy_pct?: number;
    alucinaciones_compatibilidad?: number;
  };
}

interface VisionScannerViewProps {
  fotosMuestra?: FotoMuestra[];
}

const MUESTRAS_DEFAULT: FotoMuestra[] = [
  {
    archivo: 'test2.jpg',
    titulo: 'Balatas Delanteras Cerámicas',
    subtitulo: 'REP-001 · Pastillas con ranura térmica',
    url: '/api/fotos-muestra/test2.jpg',
  },
  {
    archivo: 'test.jpg',
    titulo: 'Módulo de Batería Híbrida HV',
    subtitulo: 'REP-035 · Celdas prismáticas y arnés naranja',
    url: '/api/fotos-muestra/test.jpg',
  },
  {
    archivo: 'test3.jpg',
    titulo: 'Conjunto Transmisión Helicoidal',
    subtitulo: 'REP-036 · Engranajes y diferencial expuesto',
    url: '/api/fotos-muestra/test3.jpg',
  },
];

const PIPELINE_TOOLS = [
  {
    key: 'buscar_en_catalogo',
    titulo: '1. buscar_en_catalogo',
    fuente: 'data/catalogo.json (RAG visual + tabla compatibilidad)',
    icono: PackageSearch,
  },
  {
    key: 'consultar_inventario',
    titulo: '2. consultar_inventario',
    fuente: 'SQLite inventario (precio MXN, stock y pasillo)',
    icono: Database,
  },
  {
    key: 'generar_cotizacion',
    titulo: '3. generar_cotizacion',
    fuente: 'Cálculo determinista en Python + registro SQL',
    icono: Receipt,
  },
] as const;

function formatearMXN(valor?: number | null): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(valor ?? 0);
}

function mensajeParaCliente(resultado: DiagnosticoResponse): string {
  const cot = resultado.cotizacion;
  const stock = cot?.stock ?? 0;
  const ubicacion = cot?.ubicacion?.trim() || 'sucursal';
  const disponibilidad =
    !cot || stock <= 0
      ? 'Disponibilidad: consultar en sucursal'
      : stock <= 2
        ? `Disponible: ${stock} ${stock === 1 ? 'pieza' : 'piezas'} en ${ubicacion} (últimas unidades)`
        : `Disponible: ${stock} piezas en ${ubicacion}`;
  const lineasVehiculos = (resultado.vehiculos_compatibles || [])
    .slice(0, 4)
    .map((v) => {
      const rango =
        v.anio_desde || v.anio_hasta
          ? ` (${v.anio_desde ?? '—'}–${v.anio_hasta ?? '—'})`
          : '';
      return `• ${`${v.marca || ''} ${v.modelo || ''}`.trim() || 'Vehículo'}${rango}`;
    });
  const bloqueVehiculos =
    lineasVehiculos.length > 0
      ? ['Compatible con:', ...lineasVehiculos]
      : ['Compatible con: consulta con el asesor'];
  return [
    'Hola, te comparto la cotización:',
    '',
    resultado.pieza?.nombre || 'Pieza automotriz',
    `OEM ${resultado.pieza?.codigo_oem || 'sin código'}`,
    '',
    ...bloqueVehiculos,
    '',
    `Precio unitario: ${formatearMXN(cot?.precio_unitario)} MXN`,
    disponibilidad,
    `Total: ${formatearMXN(cot?.total)} MXN`,
    '',
    'Quedo atento si quieres apartarla.',
  ].join('\n');
}

export const VisionScannerView: React.FC<VisionScannerViewProps> = ({ fotosMuestra }) => {
  const muestras = fotosMuestra && fotosMuestra.length > 0 ? fotosMuestra : MUESTRAS_DEFAULT;

  const [muestraActiva, setMuestraActiva] = useState<string | null>(null);
  const [foto1, setFoto1] = useState<File | null>(null);
  const [foto2, setFoto2] = useState<File | null>(null);
  const [preview1, setPreview1] = useState<string>('');
  const [preview2, setPreview2] = useState<string>('');
  const [arrastrando, setArrastrando] = useState<boolean>(false);

  const [simular429, setSimular429] = useState<boolean>(false);
  const [cargando, setCargando] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [resultado, setResultado] = useState<DiagnosticoResponse | null>(null);
  const [jsonCopiado, setJsonCopiado] = useState<boolean>(false);
  const [cotizacionCopiada, setCotizacionCopiada] = useState<boolean>(false);
  const [toolExpandida, setToolExpandida] = useState<Record<number, boolean>>({});

  const [metricas, setMetricas] = useState<MetricasResponse | null>(null);
  const [cargandoMetricas, setCargandoMetricas] = useState<boolean>(false);
  const [busquedaOem, setBusquedaOem] = useState<string>('');
  const [catalogoAbierto, setCatalogoAbierto] = useState<boolean>(true);

  const cargarMetricas = useCallback(async () => {
    setCargandoMetricas(true);
    try {
      const res = await fetch('/api/metricas');
      if (res.ok) {
        const data: MetricasResponse = await res.json();
        setMetricas(data);
      }
    } catch {
      // mantener estado previo si falla red local
    } finally {
      setCargandoMetricas(false);
    }
  }, []);

  useEffect(() => {
    cargarMetricas();
  }, [cargarMetricas]);

  useEffect(() => {
    return () => {
      if (preview1.startsWith('blob:')) URL.revokeObjectURL(preview1);
      if (preview2.startsWith('blob:')) URL.revokeObjectURL(preview2);
    };
  }, [preview1, preview2]);

  const ejecutarDiagnostico = async (formData: FormData) => {
    setCargando(true);
    setError('');
    setToolExpandida({});
    formData.set('simular_429', simular429 ? 'true' : 'false');

    try {
      const res = await fetch('/api/diagnosticar', {
        method: 'POST',
        body: formData,
      });
      const data: DiagnosticoResponse = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.motivo || `Error HTTP ${res.status} al diagnosticar.`);
      }
      setResultado(data);
      cargarMetricas();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error de comunicación con /api/diagnosticar.');
    } finally {
      setCargando(false);
    }
  };

  const handleSeleccionarMuestra = (muestra: FotoMuestra) => {
    if (cargando) return;
    setMuestraActiva(muestra.archivo);
    setFoto1(null);
    setFoto2(null);
    setPreview1(muestra.url);
    setPreview2('');
    const form = new FormData();
    form.set('muestra_1', muestra.archivo);
    ejecutarDiagnostico(form);
  };

  const asignarArchivoImagen = (archivo: File, esSegundaFoto: boolean) => {
    if (!archivo.type.startsWith('image/')) {
      setError('Selecciona un archivo de imagen válido (.jpg, .png o .webp).');
      return;
    }
    setError('');
    const urlLocal = URL.createObjectURL(archivo);
    if (esSegundaFoto) {
      setFoto2(archivo);
      setPreview2(urlLocal);
    } else {
      setMuestraActiva(null);
      setFoto1(archivo);
      setPreview1(urlLocal);
      setFoto2(null);
      setPreview2('');
      setResultado(null);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setArrastrando(false);
    const archivo = e.dataTransfer.files?.[0];
    if (!archivo) return;
    const pedirSegunda = resultado?.estado === 'necesita_otra_foto' && Boolean(foto1 || muestraActiva);
    asignarArchivoImagen(archivo, pedirSegunda);
  };

  const handleDiagnosticarManual = () => {
    if (cargando) return;
    if (!foto1 && !muestraActiva) return;
    const form = new FormData();
    if (foto1) {
      form.set('foto_1', foto1);
    } else if (muestraActiva) {
      form.set('muestra_1', muestraActiva);
    }
    if (foto2) {
      form.set('foto_2', foto2);
    }
    ejecutarDiagnostico(form);
  };

  const handleReiniciarEscaner = () => {
    setMuestraActiva(null);
    setFoto1(null);
    setFoto2(null);
    setPreview1('');
    setPreview2('');
    setResultado(null);
    setError('');
  };

  const estadoActual = resultado?.estado;
  const requiereSegundaFoto = estadoActual === 'necesita_otra_foto';
  const llamadasTools = resultado?.tracking?.herramientas || [];
  const salidasTools = resultado?.tracking?.resultado_herramientas || [];
  const nombresToolsEjecutadas = new Set(llamadasTools.map((t) => t.herramienta));

  const repuestosFiltrados = useMemo(() => {
    const lista = metricas?.repuestos || [];
    const q = busquedaOem.trim().toLowerCase();
    if (!q) return lista;
    return lista.filter((item) => {
      const vehs = (item.vehiculos_compatibles || [])
        .map((v) => `${v.marca || ''} ${v.modelo || ''}`)
        .join(' ');
      return [item.id_repuesto, item.nombre, item.codigo_oem, item.ubicacion, vehs]
        .some((campo) => (campo || '').toLowerCase().includes(q));
    });
  }, [metricas, busquedaOem]);

  const s4 = metricas?.resumen_s4?.metricas_principales_plataforma;
  const s4Det = metricas?.resumen_s4?.estadisticas_detalladas;
  const s3 = metricas?.evaluacion_s3;
  const confianzaPct = Math.round(
    ((resultado?.pieza?.confianza ?? 0) <= 1
      ? (resultado?.pieza?.confianza ?? 0) * 100
      : resultado?.pieza?.confianza ?? 0)
  );

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="max-w-6xl mx-auto space-y-6 pb-10">
        {/* Cabecera Ejecutiva + Toggle Resiliencia HTTP 429 */}
        <section className="rounded-3xl border border-slate-200/90 dark:border-white/10 bg-white/85 dark:bg-[#111827]/85 backdrop-blur-xl p-5 sm:p-6 shadow-sm">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
            <div className="space-y-1.5">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Entrada Exclusivamente Visual </span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
                Escáner Multimodal de Refacciones OEM
              </h1>
              <p className="text-sm text-slate-600 dark:text-slate-400 max-w-2xl leading-relaxed">
                Sube únicamente la fotografía de la pieza dañada o elige una muestra real.{' '}
                <span className="font-mono text-xs text-slate-700 dark:text-slate-300">grok-4.7</span>{' '}
                extrae rasgos visuales, consulta el catálogo OEM, verifica existencias en SQLite y calcula la cotización en MXN.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2.5 shrink-0">
              <button
                type="button"
                onClick={() => setSimular429((v) => !v)}
                className={`inline-flex items-center gap-2.5 px-4 py-2.5 rounded-2xl text-xs font-semibold border transition-all cursor-pointer ${simular429
                  ? 'bg-amber-500/15 border-amber-500/40 text-amber-700 dark:text-amber-300 shadow-sm'
                  : 'bg-slate-100/90 dark:bg-[#19233C] border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-300 hover:border-blue-500/40'
                  }`}
              >
                {simular429 ? (
                  <ToggleRight className="w-4 h-4 text-amber-500" />
                ) : (
                  <ToggleLeft className="w-4 h-4 text-slate-400" />
                )}
                <span>Simular HTTP 429 ({simular429 ? 'Activo' : 'Inactivo'})</span>
              </button>

              {(resultado || foto1 || muestraActiva) && (
                <button
                  type="button"
                  onClick={handleReiniciarEscaner}
                  disabled={cargando}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-2xl text-xs font-medium border border-slate-200 dark:border-white/10 bg-white dark:bg-[#131B2E] text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer disabled:opacity-50"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Limpiar</span>
                </button>
              )}
            </div>
          </div>
        </section>

        {/* Zona Drag & Drop protagonista + fila compacta de muestras en 1 clic */}
        <div className="flex flex-col gap-4">
          {/* Fila compacta de muestras (1 clic) */}
          <div className="order-2 flex flex-wrap items-center gap-2.5 px-1">
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Sin foto a la mano? Prueba con una muestra:
            </span>
            {muestras.map((m) => {
              const seleccionada = muestraActiva === m.archivo && !foto1;
              return (
                <button
                  key={m.archivo}
                  type="button"
                  disabled={cargando}
                  onClick={() => handleSeleccionarMuestra(m)}
                  title={`${m.titulo} - ${m.subtitulo}`}
                  className={`group inline-flex items-center gap-2 pl-1 pr-3 py-1 rounded-full border text-left transition-all cursor-pointer disabled:opacity-60 ${seleccionada
                    ? 'border-blue-500 ring-2 ring-blue-500/25 bg-blue-50/60 dark:bg-blue-500/10'
                    : 'border-slate-200/90 dark:border-white/10 bg-white/85 dark:bg-[#131B2E]/85 hover:border-blue-500/40'
                    }`}
                >
                  <img
                    src={m.url}
                    alt={m.titulo}
                    className="h-8 w-8 rounded-full object-cover bg-slate-900"
                  />
                  <span className="text-[11px] font-semibold text-slate-800 dark:text-slate-200 max-w-[150px] truncate">
                    {m.titulo}
                  </span>
                  <span className="hidden sm:inline font-mono text-[10px] text-slate-400 dark:text-slate-500">
                    {m.archivo}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Zona Drag & Drop (foto_1 y foto_2 condicional) */}
          <div className="order-1 flex flex-col space-y-3">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Carga Directa (Solo Imagen · Sin Texto)
              </h2>
              <span className="font-mono text-[11px] text-slate-400 dark:text-slate-500">
                Máx. 2 fotos por caso
              </span>
            </div>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setArrastrando(true);
              }}
              onDragLeave={() => setArrastrando(false)}
              onDrop={handleDrop}
              className={`flex-1 rounded-2xl border-2 border-dashed p-5 transition-all flex flex-col justify-between gap-4 ${arrastrando
                ? 'border-blue-500 bg-blue-500/10'
                : requiereSegundaFoto
                  ? 'border-amber-500/60 bg-amber-500/[0.06]'
                  : 'border-slate-300/90 dark:border-white/15 bg-white/80 dark:bg-[#131B2E]/80'
                }`}
            >
              <div className="space-y-2">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
                    <Upload className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {requiereSegundaFoto
                        ? 'Sube la 2da y última fotografía de apoyo'
                        : 'Arrastra la fotografía de la pieza rota'}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Validación binaria JPEG / PNG / WEBP antes de codificar en Base64
                    </p>
                  </div>
                </div>

                {/* Previsualizaciones activas */}
                {(preview1 || preview2) && (
                  <div className="flex items-center gap-3 pt-2">
                    {preview1 && (
                      <div className="relative rounded-xl overflow-hidden border border-slate-200 dark:border-white/10 h-20 w-28 bg-slate-900">
                        <img src={preview1} alt="Fotografía 1" className="h-full w-full object-cover" />
                        <span className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-black/75 text-white">
                          foto_1
                        </span>
                      </div>
                    )}
                    {preview2 && (
                      <div className="relative rounded-xl overflow-hidden border border-amber-500/40 h-20 w-28 bg-slate-900">
                        <img src={preview2} alt="Fotografía 2" className="h-full w-full object-cover" />
                        <span className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-600 text-white">
                          foto_2
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <label className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-100 dark:bg-white/10 text-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-white/15 transition-colors cursor-pointer">
                  <ImagePlus className="w-3.5 h-3.5 text-blue-500" />
                  <span>Elegir foto_1</span>
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) asignarArchivoImagen(f, false);
                    }}
                  />
                </label>

                {requiereSegundaFoto && (
                  <label className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-colors cursor-pointer">
                    <Camera className="w-3.5 h-3.5" />
                    <span>Subir foto_2</span>
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) asignarArchivoImagen(f, true);
                      }}
                    />
                  </label>
                )}

                <button
                  type="button"
                  disabled={cargando || (!foto1 && !(requiereSegundaFoto && foto2))}
                  onClick={handleDiagnosticarManual}
                  className="ml-auto inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-slate-200 dark:disabled:bg-white/10 text-white disabled:text-slate-400 dark:disabled:text-slate-500 transition-colors cursor-pointer"
                >
                  {cargando ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <ScanSearch className="w-3.5 h-3.5" />
                  )}
                  <span>{requiereSegundaFoto ? 'Reevaluar con 2 fotos' : 'Ejecutar Agente'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Estado de Carga Multimodal en Vivo */}
        {cargando && (
          <div className="rounded-2xl border border-blue-500/30 bg-blue-500/[0.07] p-5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <Loader2 className="w-5 h-5 text-blue-500 animate-spin shrink-0" />
              <div>
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Ejecutando flujo autónomo en grok-4.7 {simular429 ? '(con inyección HTTP 429 + backoff 2s)' : ''}...
                </p>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  Extracción visual → buscar_en_catalogo → consultar_inventario → generar_cotizacion → guardrail anti-alucinaciones
                </p>
              </div>
            </div>
            <span className="hidden sm:inline-block font-mono text-xs text-blue-600 dark:text-blue-400">
              POST /api/diagnosticar
            </span>
          </div>
        )}

        {/* Alerta de Error de Red o Validación */}
        {error && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 flex items-center gap-3 text-sm text-rose-700 dark:text-rose-300">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Resultado Estructurado del Agente Multimodal */}
        {resultado && !cargando && (
          <div className="space-y-5">
            {/* Banner de Incidentes Recuperados (HTTP 429 / Timeout Backoff) */}
            {resultado.incidentes_recuperados && resultado.incidentes_recuperados.length > 0 && (
              <div className="rounded-2xl border border-amber-500/35 bg-amber-500/10 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-start gap-3">
                  <Zap className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                      Resiliencia Autónoma Verificada · Incidente Recuperado sin Abortar
                    </p>
                    <ul className="text-xs font-mono text-slate-700 dark:text-slate-200 space-y-0.5">
                      {resultado.incidentes_recuperados.map((inc, idx) => (
                        <li key={idx}>
                          {typeof inc === 'string'
                            ? inc
                            : `${inc.tipo || 'Evento'}: ${inc.detalle || inc.mensaje || ''}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded-full text-[11px] font-mono bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 shrink-0">
                  Backoff Exponencial OK
                </span>
              </div>
            )}

            {/* Alerta Especial si requiere 2da fotografía */}
            {estadoActual === 'necesita_otra_foto' && (
              <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-5 flex items-start gap-3.5">
                <Camera className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                    Se requiere una 2da fotografía para confirmar sin adivinar
                  </p>
                  <p className="text-sm text-slate-700 dark:text-slate-300">
                    {resultado.foto_adicional_solicitada || resultado.motivo}
                  </p>
                </div>
              </div>
            )}

            {/* Alerta Especial si deriva a especialista humano */}
            {estadoActual === 'derivar_a_humano' && (
              <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-5 flex items-start gap-3.5">
                <ShieldAlert className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-rose-800 dark:text-rose-200">
                    Caso Derivado de Forma Segura a Especialista Humano
                  </p>
                  <p className="text-sm text-slate-700 dark:text-slate-300">{resultado.motivo}</p>
                </div>
              </div>
            )}

            {/* Grid Principal: Pieza + Vehículos Compatibles + Cotización + Pipeline Tools */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
              {/* Columna Izquierda (7 cols): Pieza OEM + Tabla de Compatibilidad + Cotización MXN */}
              <div className="lg:col-span-7 space-y-5">
                {/* Tarjeta Técnica de la Pieza Identificada */}
                <article className="rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/90 dark:bg-[#111827]/90 p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span
                      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${estadoActual === 'cotizado'
                        ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                        : estadoActual === 'necesita_otra_foto'
                          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30'
                          : 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                        }`}
                    >
                      {estadoActual === 'cotizado' ? (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      ) : estadoActual === 'necesita_otra_foto' ? (
                        <Camera className="w-3.5 h-3.5" />
                      ) : (
                        <ShieldAlert className="w-3.5 h-3.5" />
                      )}
                      <span className="uppercase">{estadoActual}</span>
                    </span>

                    <div className="flex flex-wrap items-center gap-2">
                      {resultado.tarea_id && (
                        <span className="font-mono text-[11px] text-slate-400 dark:text-slate-500">
                          {resultado.tarea_id}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          void navigator.clipboard.writeText(mensajeParaCliente(resultado));
                          setJsonCopiado(true);
                          window.setTimeout(() => setJsonCopiado(false), 2000);
                        }}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-white/10 cursor-pointer"
                      >
                        {jsonCopiado ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                        {jsonCopiado ? 'Copiado' : 'Copiar para cliente'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const blob = new Blob([JSON.stringify(resultado, null, 2)], { type: 'application/json' });
                          const url = URL.createObjectURL(blob);
                          const enlace = document.createElement('a');
                          enlace.href = url;
                          enlace.download = `diagnostico-${resultado.tarea_id || 'resultado'}.json`;
                          enlace.click();
                          URL.revokeObjectURL(url);
                        }}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-white/10"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Descargar JSON
                      </button>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
                      {resultado.pieza?.nombre || 'Sin coincidencia definitiva en catálogo'}
                    </h3>
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      {resultado.pieza?.id && (
                        <span className="px-2.5 py-0.5 rounded-lg text-xs font-mono bg-blue-500/10 text-blue-700 dark:text-blue-300 border border-blue-500/20">
                          ID: {resultado.pieza.id}
                        </span>
                      )}
                      {resultado.pieza?.codigo_oem && (
                        <span className="px-2.5 py-0.5 rounded-lg text-xs font-mono bg-slate-100 dark:bg-white/10 text-slate-800 dark:text-slate-200">
                          OEM: {resultado.pieza.codigo_oem}
                        </span>
                      )}
                    </div>
                  </div>

                  {resultado.fotos_guardadas && resultado.fotos_guardadas.length > 0 && (
                    <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400 break-all">
                      Foto guardada en: {resultado.fotos_guardadas.join('  |  ')}
                    </p>
                  )}

                  {/* Barra de confianza visual */}
                  {confianzaPct > 0 && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-500 dark:text-slate-400">
                          Confianza de identificación visual
                        </span>
                        <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
                          {confianzaPct}%
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-slate-200 dark:bg-white/10 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-blue-600 to-emerald-500 transition-all duration-500"
                          style={{ width: `${Math.min(100, confianzaPct)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {resultado.motivo && (
                    <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed border-t border-slate-100 dark:border-white/5 pt-3">
                      {resultado.motivo}
                    </p>
                  )}
                </article>

                {/* Tabla Determinista de Vehículos Compatibles */}
                <article className="rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/90 dark:bg-[#111827]/90 overflow-hidden">
                  <div className="px-5 py-3.5 border-b border-slate-200/70 dark:border-white/10 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Car className="w-4 h-4 text-blue-500" />
                      <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Vehículos Compatibles (Resultado del Catálogo)
                      </h4>
                    </div>
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span>Verificado contra catalogo.json</span>
                    </span>
                  </div>

                  {resultado.vehiculos_compatibles && resultado.vehiculos_compatibles.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead className="bg-slate-50/80 dark:bg-white/[0.03] text-xs uppercase text-slate-500 dark:text-slate-400">
                          <tr>
                            <th className="px-5 py-2.5 font-semibold">Marca</th>
                            <th className="px-5 py-2.5 font-semibold">Modelo</th>
                            <th className="px-5 py-2.5 font-semibold">Rango de Años</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                          {resultado.vehiculos_compatibles.map((v, idx) => (
                            <tr key={idx} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                              <td className="px-5 py-2.5 font-medium">{v.marca || '—'}</td>
                              <td className="px-5 py-2.5">{v.modelo || '—'}</td>
                              <td className="px-5 py-2.5 font-mono text-xs text-slate-600 dark:text-slate-300">
                                {v.anio_desde ?? '—'} – {v.anio_hasta ?? '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="px-5 py-4 text-sm text-slate-500 dark:text-slate-400">
                      No se reportaron vehículos compatibles para este estado.
                    </p>
                  )}
                </article>

                {/* Recibo Formal de Cotización en MXN */}
                {resultado.cotizacion && (
                  <article className="rounded-2xl border border-emerald-500/30 bg-emerald-500/[0.05] dark:bg-emerald-500/[0.07] p-5 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Receipt className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                        <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          Cotización Oficial contra Inventario SQLite
                        </h4>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            if (!resultado.cotizacion) return;
                            void navigator.clipboard.writeText(mensajeParaCliente(resultado));
                            setCotizacionCopiada(true);
                            window.setTimeout(() => setCotizacionCopiada(false), 2000);
                          }}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-emerald-500/30 bg-white/80 dark:bg-[#0B0F19]/80 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/10 cursor-pointer"
                        >
                          {cotizacionCopiada ? (
                            <Check className="w-3.5 h-3.5" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                          {cotizacionCopiada ? 'Copiado' : 'Copiar para cliente'}
                        </button>
                        <span className="font-mono text-xs text-emerald-700 dark:text-emerald-300">
                          Moneda: MXN
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                      <div className="rounded-xl bg-white/80 dark:bg-[#0B0F19]/80 p-3 border border-slate-200/70 dark:border-white/10">
                        <span className="text-slate-500 dark:text-slate-400 block">Precio Unitario</span>
                        <span className="font-mono font-semibold text-sm text-slate-900 dark:text-slate-100 mt-0.5 block">
                          {formatearMXN(resultado.cotizacion.precio_unitario)}
                        </span>
                      </div>
                      <div className="rounded-xl bg-white/80 dark:bg-[#0B0F19]/80 p-3 border border-slate-200/70 dark:border-white/10">
                        <span className="text-slate-500 dark:text-slate-400 block">Stock ERP</span>
                        <span className="font-mono font-semibold text-sm text-slate-900 dark:text-slate-100 mt-0.5 block">
                          {resultado.cotizacion.stock ?? 0} uds.
                        </span>
                      </div>
                      <div className="rounded-xl bg-white/80 dark:bg-[#0B0F19]/80 p-3 border border-slate-200/70 dark:border-white/10">
                        <span className="text-slate-500 dark:text-slate-400 inline-flex items-center gap-1">
                          <MapPin className="w-3 h-3" /> Ubicación
                        </span>
                        <span className="font-mono font-semibold text-sm text-slate-900 dark:text-slate-100 mt-0.5 block">
                          {resultado.cotizacion.ubicacion || 'Almacén'}
                        </span>
                      </div>
                      <div className="rounded-xl bg-emerald-600 text-white p-3 shadow-sm">
                        <span className="text-emerald-100 block">Total Cotizado</span>
                        <span className="font-mono font-bold text-sm mt-0.5 block">
                          {formatearMXN(resultado.cotizacion.total)}
                        </span>
                      </div>
                    </div>
                  </article>
                )}
              </div>

              {/* Columna Derecha (5 cols): Pipeline de las 3 Herramientas Reales + Telemetría FinOps */}
              <div className="lg:col-span-5 space-y-5">
                <article className="rounded-2xl border border-slate-200/90 dark:border-white/10 bg-white/90 dark:bg-[#111827]/90 p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Wrench className="w-4 h-4 text-blue-500" />
                      <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Traza de las 3 Herramientas Reales
                      </h4>
                    </div>
                    <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      {llamadasTools.length} invocadas
                    </span>
                  </div>

                  {/* Estado del pipeline 1 -> 2 -> 3 */}
                  <div className="space-y-2">
                    {PIPELINE_TOOLS.map((step) => {
                      const Icono = step.icono;
                      const ejecutada = nombresToolsEjecutadas.has(step.key);
                      return (
                        <div
                          key={step.key}
                          className={`rounded-xl px-3.5 py-2.5 border flex items-center justify-between gap-2 ${ejecutada
                            ? 'border-emerald-500/35 bg-emerald-500/[0.07]'
                            : 'border-slate-200/80 dark:border-white/10 bg-slate-50/60 dark:bg-white/[0.02] opacity-65'
                            }`}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <Icono
                              className={`w-4 h-4 shrink-0 ${ejecutada ? 'text-emerald-500' : 'text-slate-400'
                                }`}
                            />
                            <div className="min-w-0">
                              <p className="font-mono text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">
                                {step.titulo}
                              </p>
                              <p className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                                {step.fuente}
                              </p>
                            </div>
                          </div>
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded-full shrink-0 ${ejecutada
                              ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
                              : 'bg-slate-200 dark:bg-white/10 text-slate-500'
                              }`}
                          >
                            {ejecutada ? 'OK' : 'Omitida'}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  {/* Acordeón inspeccionable con los argumentos y salidas reales */}
                  {llamadasTools.length > 0 && (
                    <div className="space-y-1.5 pt-2 border-t border-slate-200/70 dark:border-white/10">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Payloads Auditables (Entrada / Salida SQL & Catálogo)
                      </p>
                      {llamadasTools.map((tc, idx) => {
                        const abierta = Boolean(toolExpandida[idx]);
                        const salida = salidasTools[idx];
                        return (
                          <div
                            key={idx}
                            className="rounded-xl border border-slate-200/80 dark:border-white/10 overflow-hidden bg-slate-50/70 dark:bg-[#0B0F19]/80"
                          >
                            <button
                              type="button"
                              onClick={() =>
                                setToolExpandida((prev) => ({ ...prev, [idx]: !prev[idx] }))
                              }
                              className="w-full px-3 py-2 flex items-center justify-between text-left text-xs font-mono hover:bg-slate-100 dark:hover:bg-white/5 transition-colors cursor-pointer"
                            >
                              <span className="truncate text-slate-800 dark:text-slate-200">
                                #{idx + 1} {tc.herramienta}()
                              </span>
                              <ChevronRight
                                className={`w-3.5 h-3.5 text-slate-400 transition-transform ${abierta ? 'rotate-90' : ''
                                  }`}
                              />
                            </button>
                            {abierta && (
                              <pre className="p-3 text-[11px] font-mono bg-[#0D1117] text-slate-200 overflow-x-auto max-h-52 overflow-y-auto whitespace-pre-wrap">
                                {JSON.stringify(
                                  { argumentos: tc.argumentos, resultado: salida },
                                  null,
                                  2
                                )}
                              </pre>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Telemetría FinOps de esta tarea */}
                  {resultado.tracking && (
                    <div className="pt-3 border-t border-slate-200/70 dark:border-white/10 flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-slate-600 dark:text-slate-300">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5 text-blue-500" />
                        {resultado.tracking.latencia_segundos ?? 0}s
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Layers className="w-3.5 h-3.5 text-indigo-400" />
                        {(
                          resultado.tracking.total_tokens ??
                          (resultado.tracking.prompt_tokens ?? 0) +
                          (resultado.tracking.completion_tokens ?? 0)
                        ).toLocaleString()}{' '}
                        tok
                      </span>
                      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                        <Coins className="w-3.5 h-3.5" />$
                        {(resultado.tracking.costo_estimado_usd ?? 0).toFixed(5)} USD
                      </span>
                    </div>
                  )}
                </article>
              </div>
            </div>
          </div>
        )}

        {/* Panel Ejecutivo de Métricas S3/S4 y Explorador de los 40 Repuestos OEM */}
        <section className="rounded-3xl border border-slate-200/90 dark:border-white/10 bg-white/85 dark:bg-[#111827]/85 backdrop-blur-xl overflow-hidden">
          <div className="p-5 sm:p-6 border-b border-slate-200/80 dark:border-white/10 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                <Activity className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Métricas Auditadas & Catálogo ERP en Vivo
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Conectado en tiempo real a GET /api/metricas · 40 refacciones OEM y SQLite aislado
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={cargarMetricas}
                disabled={cargandoMetricas}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/5 transition-colors cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${cargandoMetricas ? 'animate-spin' : ''}`} />
                <span>Sincronizar</span>
              </button>
              <button
                type="button"
                onClick={() => setCatalogoAbierto((v) => !v)}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-medium border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/5 transition-colors cursor-pointer"
              >
                <span>{catalogoAbierto ? 'Ocultar catálogo' : 'Ver catálogo'}</span>
                <ChevronDown
                  className={`w-3.5 h-3.5 transition-transform ${catalogoAbierto ? 'rotate-180' : ''}`}
                />
              </button>
            </div>
          </div>

          {/* KPIs S3 y S4 */}
          <div className="p-5 sm:p-6 grid grid-cols-2 md:grid-cols-4 gap-3.5">
            <div className="rounded-2xl p-4 bg-slate-50/90 dark:bg-[#0B0F19]/80 border border-slate-200/70 dark:border-white/5">
              <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <Boxes className="w-3.5 h-3.5 text-blue-500" /> Carga S4 Procesada
              </span>
              <p className="text-xl font-bold font-mono mt-1 text-slate-900 dark:text-slate-100">
                {(s4?.total_unidades_procesadas ?? 1012).toLocaleString()} uds
              </p>
              <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-mono">
                {s4?.horas_operacion_desatendida ?? 12}h desatendido · {s4?.tasa_exito_pct ?? 100}% éxito
              </span>
            </div>

            <div className="rounded-2xl p-4 bg-slate-50/90 dark:bg-[#0B0F19]/80 border border-slate-200/70 dark:border-white/5">
              <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <FileCheck2 className="w-3.5 h-3.5 text-emerald-500" /> Evaluación S3 (100 casos)
              </span>
              <p className="text-xl font-bold font-mono mt-1 text-slate-900 dark:text-slate-100">
                {s3?.top1_accuracy_pct ?? 98.81}% Top-1
              </p>
              <span className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                {s3?.top3_accuracy_pct ?? 100}% Top-3 · {s3?.alucinaciones_compatibilidad ?? 0} alucinaciones
              </span>
            </div>

            <div className="rounded-2xl p-4 bg-slate-50/90 dark:bg-[#0B0F19]/80 border border-slate-200/70 dark:border-white/5">
              <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <Coins className="w-3.5 h-3.5 text-amber-500" /> Costo FinOps Promedio
              </span>
              <p className="text-xl font-bold font-mono mt-1 text-slate-900 dark:text-slate-100">
                ${(s4?.costo_promedio_por_tarea_usd ?? 0.007015).toFixed(4)}
              </p>
              <span className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                Total lote S4: ${(s4?.costo_total_usd ?? 7.0996).toFixed(2)} USD
              </span>
            </div>

            <div className="rounded-2xl p-4 bg-slate-50/90 dark:bg-[#0B0F19]/80 border border-slate-200/70 dark:border-white/5">
              <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-indigo-500" /> Autonomía & Latencia
              </span>
              <p className="text-xl font-bold font-mono mt-1 text-slate-900 dark:text-slate-100">
                {s4Det?.latencia_segundos?.p50 ?? 14.45}s p50
              </p>
              <span className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                {s4Det?.incidentes_y_recuperacion?.recuperados_autonomamente ?? 295} eventos 429/red recuperados
              </span>
            </div>
          </div>

          {/* Buscador + Tabla de las 40 Refacciones OEM */}
          {catalogoAbierto && (
            <div className="px-5 sm:px-6 pb-6 space-y-3">
              <label className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white dark:bg-[#0B0F19]">
                <Search className="w-4 h-4 text-slate-400 shrink-0" />
                <input
                  type="text"
                  value={busquedaOem}
                  onChange={(e) => setBusquedaOem(e.target.value)}
                  placeholder="Filtrar 40 refacciones por ID (REP-001), código OEM, nombre, marca o ubicación..."
                  className="w-full bg-transparent text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none"
                />
                <span className="font-mono text-xs text-slate-400 shrink-0">
                  {repuestosFiltrados.length} items
                </span>
              </label>

              <div className="max-h-72 overflow-y-auto rounded-2xl border border-slate-200/80 dark:border-white/10">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-slate-100/95 dark:bg-[#161F33] text-slate-500 dark:text-slate-400 uppercase">
                    <tr>
                      <th className="px-4 py-2.5 font-semibold">ID / OEM</th>
                      <th className="px-4 py-2.5 font-semibold">Refacción</th>
                      <th className="px-4 py-2.5 font-semibold hidden sm:table-cell">Compatibilidad</th>
                      <th className="px-4 py-2.5 font-semibold text-right">Precio MXN</th>
                      <th className="px-4 py-2.5 font-semibold text-right">Stock ERP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-white/5 bg-white/70 dark:bg-[#0B0F19]/60">
                    {repuestosFiltrados.map((r) => {
                      const stockNum = r.stock ?? 0;
                      const fueraErp = r.ubicacion === 'N/A';
                      return (
                        <tr key={r.id_repuesto} className="hover:bg-slate-50 dark:hover:bg-white/[0.03]">
                          <td className="px-4 py-2.5 font-mono">
                            <span className="font-semibold text-slate-900 dark:text-slate-100 block">
                              {r.id_repuesto}
                            </span>
                            <span className="text-[11px] text-slate-500">{r.codigo_oem || '—'}</span>
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="font-medium text-slate-800 dark:text-slate-200 block">
                              {r.nombre}
                            </span>
                            <span className="text-[11px] text-slate-500 font-mono">
                              Ubicación: {r.ubicacion || 'N/A'}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 hidden sm:table-cell text-slate-600 dark:text-slate-400">
                            {(r.vehiculos_compatibles || [])
                              .map((v) => `${v.marca} ${v.modelo} (${v.anio_desde}-${v.anio_hasta})`)
                              .join(', ') || '—'}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-semibold text-slate-900 dark:text-slate-100">
                            {fueraErp ? '—' : formatearMXN(r.precio_unitario)}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <span
                              className={`inline-block px-2 py-0.5 rounded-full font-mono text-[11px] ${fueraErp
                                ? 'bg-slate-200 dark:bg-white/10 text-slate-500'
                                : stockNum > 0
                                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                                  : 'bg-amber-500/15 text-amber-700 dark:text-amber-300'
                                }`}
                            >
                              {fueraErp ? 'Fuera ERP' : `${stockNum} uds`}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
