import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowUp,
  Check,
  Clock,
  Coins,
  Copy,
  FileCode2,
  FilePenLine,
  FolderTree,
  Layers,
  RotateCcw,
  SearchCode,
  Sparkles,
  Square,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import { ChatMessage } from '../types/studio';
import { AgentToolsDrawer } from './AgentToolsDrawer';
import { MarkdownRenderer } from './MarkdownRenderer';

interface GeminiChatViewProps {
  mensajes: ChatMessage[];
  enviando: boolean;
  usarTools: boolean;
  onToggleTools: () => void;
  onEnviarMensaje: (texto: string) => void;
  onDetenerGeneracion: () => void;
  onLimpiarChat: () => void;
  onIrAEscaner?: () => void;
}

const TARJETAS_WORKSPACE = [
  {
    titulo: 'Explorar estructura del proyecto',
    subtitulo: 'Usa listar_directorio sobre la raíz y src/',
    prompt:
      'Explora la raíz del proyecto y la carpeta src/, y dame una tabla clara con el propósito de cada archivo.',
    icono: FolderTree,
    color: 'text-amber-500 dark:text-amber-400 bg-amber-500/10',
  },
  {
    titulo: 'Leer e inspeccionar código real',
    subtitulo: 'Usa leer_archivo con rango exacto de líneas',
    prompt:
      'Lee las líneas 60 a 100 de src/agent.py y explícame paso a paso cómo funciona el guardrail validar_respuesta.',
    icono: FileCode2,
    color: 'text-blue-500 dark:text-blue-400 bg-blue-500/10',
  },
  {
    titulo: 'Ejecutar pytest en PowerShell',
    subtitulo: 'Usa ejecutar_comando en tiempo real',
    prompt:
      'Ejecuta `python -m pytest -q` en la terminal y dime cuántas pruebas pasaron y el tiempo de ejecución.',
    icono: TerminalSquare,
    color: 'text-purple-500 dark:text-purple-400 bg-purple-500/10',
  },
  {
    titulo: 'Buscar y auditar funciones',
    subtitulo: 'Usa buscar_en_codigo en todo el repositorio',
    prompt:
      'Busca en el código dónde se usa `guardar_lote_checkpoints` y explícame cómo protege el progreso en SQLite.',
    icono: SearchCode,
    color: 'text-emerald-500 dark:text-emerald-400 bg-emerald-500/10',
  },
];

const CHIPS_HERRAMIENTAS = [
  { nombre: 'Explorar archivos', icono: FolderTree, prefijo: 'Lista los archivos de la carpeta ' },
  { nombre: 'Leer líneas', icono: FileCode2, prefijo: 'Lee el archivo ' },
  { nombre: 'Editar código', icono: FilePenLine, prefijo: 'Edita el archivo ' },
  { nombre: 'Correr comando', icono: TerminalSquare, prefijo: 'Ejecuta en la terminal el comando: ' },
];

export const GeminiChatView: React.FC<GeminiChatViewProps> = ({
  mensajes,
  enviando,
  usarTools,
  onToggleTools,
  onEnviarMensaje,
  onDetenerGeneracion,
  onLimpiarChat,
}) => {
  const [input, setInput] = useState('');
  const [copiadoId, setCopiadoId] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensajes]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [input]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const limpio = input.trim();
    if (!limpio || enviando) return;
    setInput('');
    onEnviarMensaje(limpio);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const insertarPrefijo = (prefijo: string) => {
    setInput(prefijo);
    textareaRef.current?.focus();
  };

  const copiarRespuesta = async (id: string, texto: string) => {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiadoId(id);
      setTimeout(() => setCopiadoId(null), 1800);
    } catch {
      // ignore
    }
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Área desplazable limpia estilo Google Gemini (min-h-0 evita solapamientos) */}
      <div
        ref={scrollContainerRef}
        className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 lg:px-8"
      >
        <div className="max-w-3xl mx-auto min-h-full flex flex-col">
          {mensajes.length === 0 ? (
            /* Estado inicial centrado al estilo Gemini Advanced */
            <div className="flex-1 flex flex-col justify-center py-10 space-y-9">
              <div className="space-y-3">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Agente de Código & Chat · Mismas capacidades de chat.py + UI Gemini</span>
                </div>

                <h1 className="text-3xl sm:text-5xl font-semibold tracking-tight leading-[1.15]">
                  <span className="bg-gradient-to-r from-blue-500 via-indigo-400 to-cyan-400 bg-clip-text text-transparent">
                    Hola, Mateo
                  </span>
                  <span className="block text-slate-700 dark:text-slate-300 mt-1 font-normal text-2xl sm:text-4xl">
                    ¿En qué parte del proyecto trabajamos?
                  </span>
                </h1>

                <p className="text-sm text-slate-600 dark:text-slate-400 max-w-2xl leading-relaxed pt-1">
                  Este chat tiene conectadas tus herramientas reales del workspace: puede{' '}
                  <strong className="font-medium text-slate-800 dark:text-slate-200">
                    explorar carpetas, leer rangos de líneas, crear o editar archivos y ejecutar comandos en PowerShell
                  </strong>{' '}
                  directamente sobre tu proyecto.
                </p>
              </div>

              {/* 4 Tarjetas limpias estilo Gemini */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {TARJETAS_WORKSPACE.map((item, idx) => {
                  const Icono = item.icono;
                  return (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => onEnviarMensaje(item.prompt)}
                      className="group text-left p-4 rounded-2xl bg-white/80 dark:bg-[#131B2E]/80 hover:bg-white dark:hover:bg-[#19233C] border border-slate-200/80 dark:border-white/[0.08] hover:border-blue-500/40 transition-all duration-200 cursor-pointer flex items-start justify-between gap-3"
                    >
                      <div className="space-y-1 min-w-0">
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                          {item.titulo}
                        </h3>
                        <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                          {item.subtitulo}
                        </p>
                      </div>
                      <div className={`p-2.5 rounded-xl shrink-0 ${item.color}`}>
                        <Icono className="w-4 h-4" />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            /* Conversación fluida sin cajas pesadas (auténtico estilo Gemini) */
            <div className="py-6 space-y-8">
              {mensajes.map((msg) =>
                msg.role === 'user' ? (
                  <div key={msg.id} className="flex justify-end">
                    <div className="max-w-[88%] sm:max-w-[78%] rounded-3xl rounded-tr-md px-5 py-3.5 bg-slate-200/85 dark:bg-[#1E293B] text-slate-900 dark:text-slate-100 border border-slate-300/60 dark:border-white/[0.07] text-[15px] leading-relaxed">
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  </div>
                ) : (
                  <div key={msg.id} className="flex items-start gap-4">
                    {/* Ícono estrella Gemini */}
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${msg.isStreaming
                        ? 'bg-gradient-to-tr from-blue-600 via-indigo-500 to-cyan-400 text-white animate-pulse shadow-md shadow-blue-500/25'
                        : 'bg-gradient-to-tr from-blue-600/20 to-indigo-500/20 text-blue-600 dark:text-blue-400 border border-blue-500/25'
                        }`}
                    >
                      <Sparkles className="w-4 h-4" />
                    </div>

                    <div className="flex-1 min-w-0 space-y-2">
                      {/* Nombre + Estado */}
                      <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span className="font-semibold text-slate-800 dark:text-slate-200">
                          Platica Agent
                        </span>
                        <span className="font-mono text-[11px] opacity-80">grok-4.7</span>
                      </div>

                      {/* Acordeón interactivo de herramientas ejecutadas (listar, leer, editar, comando) */}
                      {msg.pasos_herramientas && msg.pasos_herramientas.length > 0 && (
                        <AgentToolsDrawer
                          pasos={msg.pasos_herramientas}
                          isStreaming={msg.isStreaming}
                        />
                      )}

                      {/* Respuesta en Markdown directo sobre el lienzo (sin caja artificial) */}
                      {msg.content ? (
                        <div className="pt-1">
                          <MarkdownRenderer content={msg.content} />
                        </div>
                      ) : msg.isStreaming &&
                        (!msg.pasos_herramientas || msg.pasos_herramientas.length === 0) ? (
                        <div className="py-2 flex items-center gap-2.5 text-sm text-slate-500 dark:text-slate-400">
                          <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />
                          <span>Pensando...</span>
                        </div>
                      ) : null}

                      {/* Barra sutil de acciones y telemetría FinOps */}
                      {!msg.isStreaming && (msg.content || (msg.pasos_herramientas?.length ?? 0) > 0) && (
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                          <div className="flex items-center gap-1">
                            {msg.content && (
                              <button
                                type="button"
                                onClick={() => copiarRespuesta(msg.id, msg.content)}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-200/60 dark:hover:bg-white/10 transition-colors cursor-pointer"
                              >
                                {copiadoId === msg.id ? (
                                  <>
                                    <Check className="w-3.5 h-3.5 text-emerald-500" />
                                    <span className="text-emerald-500">Copiado</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="w-3.5 h-3.5" />
                                    <span>Copiar</span>
                                  </>
                                )}
                              </button>
                            )}
                          </div>

                          {msg.usage && (
                            <div className="flex flex-wrap items-center gap-2.5 text-[11px] font-mono text-slate-500 dark:text-slate-400">
                              {msg.latencia_segundos !== undefined && (
                                <span className="inline-flex items-center gap-1">
                                  <Clock className="w-3 h-3 text-slate-400" />
                                  {msg.latencia_segundos}s
                                </span>
                              )}
                              <span>·</span>
                              <span className="inline-flex items-center gap-1">
                                <Layers className="w-3 h-3 text-slate-400" />
                                {msg.usage.total_tokens.toLocaleString()} tok
                              </span>
                              <span>·</span>
                              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                                <Coins className="w-3 h-3" />${msg.usage.costo_usd.toFixed(5)}
                              </span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>
      </div>

      {/* Compositor inferior fijo (shrink-0) estilo Gemini 2.0 */}
      <div className="shrink-0 px-4 sm:px-6 pb-4 pt-2 bg-slate-50/90 dark:bg-[#0B0F19]/90 backdrop-blur-md">
        <div className="max-w-3xl mx-auto space-y-2">
          {/* Atajos rápidos de herramientas cuando Tools está activo */}
          {usarTools && (
            <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 no-scrollbar">
              {CHIPS_HERRAMIENTAS.map((chip, idx) => {
                const Icono = chip.icono;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => insertarPrefijo(chip.prefijo)}
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-medium bg-white dark:bg-[#131B2E] text-slate-600 dark:text-slate-300 border border-slate-200/90 dark:border-white/10 hover:border-blue-500/40 hover:text-blue-600 dark:hover:text-blue-400 transition-colors shrink-0 cursor-pointer"
                  >
                    <Icono className="w-3 h-3" />
                    <span>{chip.nombre}</span>
                  </button>
                );
              })}
            </div>
          )}

          <form
            onSubmit={handleSubmit}
            className="rounded-3xl bg-white dark:bg-[#131B2E] border border-slate-300/90 dark:border-white/15 shadow-lg shadow-slate-900/5 dark:shadow-black/30 focus-within:border-blue-500 dark:focus-within:border-blue-400 transition-colors px-4 pt-3 pb-2.5"
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                usarTools
                  ? 'Pídeme explorar carpetas, leer líneas, crear/editar archivos o correr comandos...'
                  : 'Escribe una consulta para grok-4.7...'
              }
              aria-label="Mensaje para Platica Agent"
              disabled={enviando}
              className="w-full resize-none bg-transparent text-[15px] text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none max-h-44 leading-relaxed"
            />

            {/* Barra inferior interna de la cápsula Gemini */}
            <div className="flex items-center justify-between gap-2 pt-2 mt-1 border-t border-slate-100 dark:border-white/[0.06]">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onToggleTools}
                  title="Activar o desactivar herramientas sobre archivos y terminal"
                  className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer border ${usarTools
                    ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30'
                    : 'bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400 border-transparent'
                    }`}
                >
                  <Wrench className="w-3.5 h-3.5" />
                  <span>Agente Workspace {usarTools ? 'ON' : 'OFF'}</span>
                </button>

                {mensajes.length > 0 && !enviando && (
                  <button
                    type="button"
                    onClick={onLimpiarChat}
                    title="Limpiar mensajes de esta conversación"
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/10 transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Reiniciar</span>
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                {enviando ? (
                  <button
                    type="button"
                    onClick={onDetenerGeneracion}
                    title="Detener respuesta"
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-full bg-red-500/15 hover:bg-red-500/25 text-red-600 dark:text-red-400 text-xs font-semibold transition-colors cursor-pointer"
                  >
                    <Square className="w-3.5 h-3.5 fill-current" />
                    <span>Detener</span>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    aria-label="Enviar mensaje"
                    className="p-2.5 rounded-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-200 dark:disabled:bg-white/10 text-white disabled:text-slate-400 dark:disabled:text-slate-600 transition-colors cursor-pointer"
                  >
                    <ArrowUp className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          </form>

          <p className="text-center text-[11px] text-slate-400 dark:text-slate-500">
            Platica AI Studio · <span className="font-mono">grok-4.7</span> con acceso real a archivos y PowerShell local
          </p>
        </div>
      </div>
    </div>
  );
};
