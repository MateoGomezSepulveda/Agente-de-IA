import React, { useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileCode2,
  FilePenLine,
  FilePlus2,
  FolderTree,
  Loader2,
  SearchCode,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import { AgentToolStep } from '../types/studio';

interface AgentToolsDrawerProps {
  pasos: AgentToolStep[];
  isStreaming?: boolean;
}

const META_HERRAMIENTAS: Record<
  string,
  { etiqueta: string; icono: React.ElementType; color: string }
> = {
  listar_directorio: {
    etiqueta: 'Explorar directorio',
    icono: FolderTree,
    color: 'text-amber-500 dark:text-amber-400',
  },
  leer_archivo: {
    etiqueta: 'Leer líneas de código',
    icono: FileCode2,
    color: 'text-blue-500 dark:text-blue-400',
  },
  escribir_archivo: {
    etiqueta: 'Crear / Escribir archivo',
    icono: FilePlus2,
    color: 'text-emerald-500 dark:text-emerald-400',
  },
  editar_archivo: {
    etiqueta: 'Editar bloque de código',
    icono: FilePenLine,
    color: 'text-indigo-500 dark:text-indigo-400',
  },
  buscar_en_codigo: {
    etiqueta: 'Buscar en el repositorio',
    icono: SearchCode,
    color: 'text-cyan-500 dark:text-cyan-400',
  },
  ejecutar_comando: {
    etiqueta: 'Ejecutar en PowerShell',
    icono: TerminalSquare,
    color: 'text-purple-500 dark:text-purple-400',
  },
};

function formatearArgumentoPrincipal(herramienta: string, args: Record<string, unknown>): string {
  if (herramienta === 'listar_directorio') {
    return String(args.ruta || '.');
  }
  if (herramienta === 'leer_archivo') {
    const ruta = String(args.ruta || '');
    const ini = args.linea_inicio ? `L${args.linea_inicio}` : '';
    const fin = args.linea_fin ? `-L${args.linea_fin}` : '';
    return ini ? `${ruta} (${ini}${fin})` : ruta;
  }
  if (herramienta === 'escribir_archivo' || herramienta === 'editar_archivo') {
    return String(args.ruta || '');
  }
  if (herramienta === 'buscar_en_codigo') {
    return `"${String(args.patron || '')}"`;
  }
  if (herramienta === 'ejecutar_comando') {
    return String(args.comando || '');
  }
  return JSON.stringify(args);
}

export const AgentToolsDrawer: React.FC<AgentToolsDrawerProps> = ({ pasos, isStreaming }) => {
  const hayCorriendo = pasos.some((p) => p.estado === 'running');
  const [abierto, setAbierto] = useState<boolean>(true);
  const [pasoExpandido, setPasoExpandido] = useState<Record<string, boolean>>({});

  if (!pasos || pasos.length === 0) return null;

  const pasoActual = pasos.find((p) => p.estado === 'running') || pasos[pasos.length - 1];
  const tiempoTotalMs = pasos.reduce((acc, p) => acc + (p.duracion_ms || 0), 0);

  const toggleDetalle = (id: string) => {
    setPasoExpandido((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="my-2.5 rounded-2xl border border-slate-200/90 dark:border-white/10 bg-slate-100/75 dark:bg-[#111827]/80 backdrop-blur-md overflow-hidden">
      {/* Cabecera tipo "Pensamiento / Acciones de Gemini" */}
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-slate-200/50 dark:hover:bg-white/[0.04] transition-colors duration-200 cursor-pointer"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {hayCorriendo || (isStreaming && pasos.some((p) => p.estado === 'running')) ? (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin shrink-0" />
          ) : pasos.some((p) => p.estado === 'error') ? (
            <AlertCircle className="w-4 h-4 text-amber-500 shrink-0" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
          )}

          <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
            {hayCorriendo
              ? `Ejecutando ${
                  META_HERRAMIENTAS[pasoActual.herramienta]?.etiqueta.toLowerCase() ||
                  pasoActual.herramienta
                }...`
              : `${pasos.length} ${
                  pasos.length === 1 ? 'acción ejecutada' : 'acciones ejecutadas'
                } en el workspace`}
          </span>

          {!hayCorriendo && tiempoTotalMs > 0 && (
            <span className="hidden sm:inline-block font-mono text-[11px] text-slate-500 dark:text-slate-400">
              · {tiempoTotalMs} ms
            </span>
          )}
        </div>

        <ChevronDown
          className={`w-4 h-4 text-slate-400 transition-transform duration-200 shrink-0 ${
            abierto ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* Lista de pasos ejecutados por el agente */}
      {abierto && (
        <div className="px-3 pb-3 pt-1 space-y-1.5 border-t border-slate-200/70 dark:border-white/5">
          {pasos.map((paso) => {
            const meta = META_HERRAMIENTAS[paso.herramienta] || {
              etiqueta: paso.herramienta,
              icono: Wrench,
              color: 'text-slate-400',
            };
            const Icono = meta.icono;
            const argTexto = formatearArgumentoPrincipal(paso.herramienta, paso.argumentos);
            const verDetalle = Boolean(pasoExpandido[paso.id]);

            return (
              <div
                key={paso.id}
                className="rounded-xl bg-white/85 dark:bg-[#0B0F19]/80 border border-slate-200/70 dark:border-white/5 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggleDetalle(paso.id)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-slate-100/70 dark:hover:bg-white/[0.03] transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {paso.estado === 'running' ? (
                      <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />
                    ) : (
                      <Icono className={`w-3.5 h-3.5 shrink-0 ${meta.color}`} />
                    )}

                    <span className="text-xs font-medium text-slate-700 dark:text-slate-300 shrink-0">
                      {meta.etiqueta}
                    </span>

                    <code className="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-100 dark:bg-white/5 text-slate-700 dark:text-slate-300 truncate">
                      {argTexto}
                    </code>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {paso.resumen && (
                      <span
                        className={`hidden md:inline text-[11px] truncate max-w-[240px] ${
                          paso.estado === 'error'
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-slate-500 dark:text-slate-400'
                        }`}
                      >
                        {paso.resumen.replace(/`/g, '')}
                      </span>
                    )}
                    <ChevronRight
                      className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-150 ${
                        verDetalle ? 'rotate-90' : ''
                      }`}
                    />
                  </div>
                </button>

                {verDetalle && paso.detalle && (
                  <div className="px-3 pb-3 pt-1 border-t border-slate-100 dark:border-white/5 bg-[#0D1117] text-slate-200">
                    <div className="flex items-center justify-between py-1 text-[10px] font-mono text-slate-400">
                      <span>Salida de `{paso.herramienta}`</span>
                      {paso.duracion_ms !== undefined && <span>{paso.duracion_ms} ms</span>}
                    </div>
                    <pre className="text-[11px] font-mono leading-relaxed overflow-x-auto max-h-60 overflow-y-auto whitespace-pre-wrap text-slate-200">
                      {paso.detalle}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
