import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Coins,
  Cpu,
  MessageSquare,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  ScanSearch,
  Sparkles,
  Sun,
  Trash2,
} from 'lucide-react';
import { GeminiChatView } from './components/GeminiChatView';
import { VisionScannerView } from './components/VisionScannerView';
import {
  AgentToolStep,
  ChatMessage,
  ChatSession,
  SaludBackend,
  StudioMode,
} from './types/studio';

const STORAGE_KEY_SESSIONS = 'platica_ai_studio_sessions_v2';
const STORAGE_KEY_THEME = 'platica_ai_studio_theme_v2';
const STORAGE_KEY_MODO = 'platica_ai_studio_modo_v2';

function crearSesionInicial(): ChatSession {
  const ahora = new Date().toISOString();
  return {
    id: `ses_${Date.now()}`,
    titulo: 'Nueva conversación',
    creadaEn: ahora,
    actualizadaEn: ahora,
    mensajes: [],
  };
}

export const App: React.FC = () => {
  // La página principal del proyecto es el Escáner de Refacciones; se recuerda la última pestaña usada.
  const [modo, setModoState] = useState<StudioMode>(() =>
    localStorage.getItem(STORAGE_KEY_MODO) === 'chat' ? 'chat' : 'vision'
  );
  const setModo = (nuevo: StudioMode) => {
    localStorage.setItem(STORAGE_KEY_MODO, nuevo);
    setModoState(nuevo);
  };
  const [sidebarAbierto, setSidebarAbierto] = useState(true);
  const [usarTools, setUsarTools] = useState(true);
  const [temaOscuro, setTemaOscuro] = useState<boolean>(() => {
    const guardado = localStorage.getItem(STORAGE_KEY_THEME);
    return guardado ? guardado === 'dark' : true;
  });

  const [sesiones, setSesiones] = useState<ChatSession[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_SESSIONS);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // fallback
    }
    return [crearSesionInicial()];
  });

  const [sesionActivaId, setSesionActivaId] = useState<string>(() => sesiones[0]?.id || '');
  const [enviando, setEnviando] = useState(false);
  const [salud, setSalud] = useState<SaludBackend | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    if (temaOscuro) {
      root.classList.add('dark');
      localStorage.setItem(STORAGE_KEY_THEME, 'dark');
    } else {
      root.classList.remove('dark');
      localStorage.setItem(STORAGE_KEY_THEME, 'light');
    }
  }, [temaOscuro]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY_SESSIONS, JSON.stringify(sesiones));
    } catch {
      // ignore quota error
    }
  }, [sesiones]);

  useEffect(() => {
    fetch('/api/salud')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setSalud(data);
      })
      .catch(() => {
        setSalud(null);
      });
  }, []);

  const sesionActiva = useMemo(
    () => sesiones.find((s) => s.id === sesionActivaId) || sesiones[0],
    [sesiones, sesionActivaId]
  );

  const telemetriaAcumulada = useMemo(() => {
    let tokens = 0;
    let costo = 0;
    for (const s of sesiones) {
      for (const m of s.mensajes) {
        if (m.usage) {
          tokens += m.usage.total_tokens || 0;
          costo += m.usage.costo_usd || 0;
        }
      }
    }
    return { tokens, costo };
  }, [sesiones]);

  const handleNuevaSesion = () => {
    const nueva = crearSesionInicial();
    setSesiones((prev) => [nueva, ...prev]);
    setSesionActivaId(nueva.id);
    setModo('chat');
  };

  const handleEliminarSesion = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSesiones((prev) => {
      const filtradas = prev.filter((s) => s.id !== id);
      if (filtradas.length === 0) {
        const nueva = crearSesionInicial();
        setSesionActivaId(nueva.id);
        return [nueva];
      }
      if (id === sesionActivaId) {
        setSesionActivaId(filtradas[0].id);
      }
      return filtradas;
    });
  };

  const handleLimpiarSesionActiva = () => {
    if (!sesionActiva) return;
    setSesiones((prev) =>
      prev.map((s) =>
        s.id === sesionActiva.id
          ? {
              ...s,
              titulo: 'Nueva conversación',
              actualizadaEn: new Date().toISOString(),
              mensajes: [],
            }
          : s
      )
    );
  };

  const sesionesRef = useRef<ChatSession[]>(sesiones);
  sesionesRef.current = sesiones;
  const jobActivoRef = useRef<string | null>(null);
  const contadorEventosRef = useRef<number>(0);
  const reanudandoRef = useRef<Set<string>>(new Set());

  const esperar = (ms: number) => new Promise<void>((resolver) => setTimeout(resolver, ms));

  const patchMensaje = (sesionId: string, msgId: string, fn: (m: ChatMessage) => ChatMessage) => {
    setSesiones((prev) =>
      prev.map((s) =>
        s.id !== sesionId
          ? s
          : { ...s, mensajes: s.mensajes.map((m) => (m.id === msgId ? fn(m) : m)) }
      )
    );
  };

  const marcarCorte = (sesionId: string, msgId: string, aviso: string) => {
    patchMensaje(sesionId, msgId, (m) => ({
      ...m,
      isStreaming: false,
      content: (m.content ? `${m.content}\n\n` : '') + aviso,
    }));
  };

  const handleDetenerGeneracion = () => {
    const jobId = jobActivoRef.current;
    if (jobId) {
      fetch(`/api/chat/${jobId}/cancel`, { method: 'POST' }).catch(() => undefined);
    }
    abortControllerRef.current?.abort();
  };

  /** Lee un stream SSE (inicial o reanudado) y aplica cada evento al mensaje del asistente. */
  const consumirStream = async (
    response: Response,
    sesionId: string,
    msgId: string,
    eventosIniciales: number
  ): Promise<boolean> => {
    if (!response.body) throw new Error('La respuesta no trae cuerpo de streaming.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let recibioFin = false;
    contadorEventosRef.current = eventosIniciales;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const eventos = buffer.split('\n\n');
      buffer = eventos.pop() || '';

      for (const ev of eventos) {
        const linea = ev.trim();
        if (!linea.startsWith('data:')) continue;
        const jsonStr = linea.slice(5).trim();
        if (!jsonStr) continue;

        // Cada evento 'data:' cuenta, aunque falle el parseo, para que el índice de reanudación coincida con el servidor
        contadorEventosRef.current += 1;
        const n = contadorEventosRef.current;

        let payload: Record<string, any>;
        try {
          payload = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        if (payload.tipo === 'job') {
          jobActivoRef.current = payload.job_id;
          patchMensaje(sesionId, msgId, (m) => ({ ...m, job_id: payload.job_id, job_eventos: n }));
        } else if (payload.tipo === 'token') {
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            content: m.content + payload.contenido,
            job_eventos: n,
          }));
        } else if (payload.tipo === 'tool_inicio') {
          const nuevoPaso: AgentToolStep = {
            id: payload.id,
            iteracion: payload.iteracion || 1,
            herramienta: payload.herramienta,
            argumentos: payload.argumentos || {},
            estado: 'running',
            resumen: 'Generando código / argumentos...',
          };
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            pasos_herramientas: [...(m.pasos_herramientas || []), nuevoPaso],
            job_eventos: n,
          }));
        } else if (payload.tipo === 'tool_progreso') {
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            job_eventos: n,
            pasos_herramientas: (m.pasos_herramientas || []).map((p) =>
              p.id === payload.id
                ? {
                    ...p,
                    argumentos: payload.ruta_parcial
                      ? { ...p.argumentos, ruta: payload.ruta_parcial }
                      : p.argumentos,
                    resumen: `Escribiendo (${Number(payload.caracteres || 0).toLocaleString()} chars)...`,
                  }
                : p
            ),
          }));
        } else if (payload.tipo === 'tool_fin') {
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            job_eventos: n,
            pasos_herramientas: (m.pasos_herramientas || []).map((p) =>
              p.id === payload.id
                ? {
                    ...p,
                    argumentos: payload.argumentos || p.argumentos,
                    estado: payload.exito ? 'done' : 'error',
                    resumen: payload.resumen,
                    detalle: payload.detalle,
                    duracion_ms: payload.duracion_ms,
                  }
                : p
            ),
          }));
        } else if (payload.tipo === 'fin') {
          recibioFin = true;
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            isStreaming: false,
            latencia_segundos: payload.latencia_segundos,
            usage: payload.usage,
            job_eventos: n,
          }));
        } else if (payload.tipo === 'error') {
          recibioFin = true;
          patchMensaje(sesionId, msgId, (m) => ({
            ...m,
            isStreaming: false,
            error: true,
            job_eventos: n,
            content:
              (m.content ? `${m.content}\n\n` : '') + `> **Error del servidor:** ${payload.error}`,
          }));
        }
      }
    }
    return recibioFin;
  };

  /** Retoma un trabajo del servidor desde `desde`. Devuelve 'ok' | 'perdido' | 'cortado'. */
  const seguirJob = async (
    sesionId: string,
    msgId: string,
    jobId: string,
    desdeInicial: number,
    signal: AbortSignal
  ): Promise<'ok' | 'perdido' | 'cortado'> => {
    let desde = desdeInicial;
    for (let intento = 0; intento < 5; intento++) {
      const resp = await fetch(`/api/chat/${jobId}/stream?desde=${desde}`, { signal });
      if (resp.status === 404) return 'perdido';
      if (!resp.ok) {
        await esperar(1500);
        continue;
      }
      const fin = await consumirStream(resp, sesionId, msgId, desde);
      if (fin) return 'ok';
      desde = contadorEventosRef.current;
      await esperar(1000);
    }
    return 'cortado';
  };

  /** Tras recargar la página: retoma la respuesta que el servidor siguió generando. */
  const retomarJob = async (sesionId: string, msgId: string, jobId: string, desde: number) => {
    if (reanudandoRef.current.has(jobId)) return;
    reanudandoRef.current.add(jobId);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    jobActivoRef.current = jobId;
    setEnviando(true);
    try {
      const resultado = await seguirJob(sesionId, msgId, jobId, desde, controller.signal);
      if (resultado === 'perdido') {
        marcarCorte(
          sesionId,
          msgId,
          '> **Aviso:** El servidor se reinició y perdió el trabajo en curso. Escribe **"continúa"** para retomar.'
        );
      } else if (resultado === 'cortado') {
        marcarCorte(sesionId, msgId, '> **Aviso:** Se perdió la conexión con el servidor. Escribe **"continúa"**.');
      }
    } catch (err: unknown) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      marcarCorte(
        sesionId,
        msgId,
        isAbort ? '*(Generación detenida por el usuario)*' : '> **Aviso:** No se pudo retomar la respuesta.'
      );
    } finally {
      reanudandoRef.current.delete(jobId);
      setEnviando(false);
      abortControllerRef.current = null;
      jobActivoRef.current = null;
    }
  };

  useEffect(() => {
    // Al montar: cualquier respuesta que quedó "en streaming" se retoma desde el servidor (o se cierra si nunca arrancó)
    for (const s of sesionesRef.current) {
      for (const m of s.mensajes) {
        if (m.role !== 'assistant' || !m.isStreaming) continue;
        if (m.job_id) {
          retomarJob(s.id, m.id, m.job_id, m.job_eventos ?? 0);
        } else {
          marcarCorte(s.id, m.id, '*(Respuesta interrumpida antes de iniciar. Vuelve a enviar tu mensaje.)*');
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEnviarMensaje = async (texto: string) => {
    if (!sesionActiva || enviando) return;

    const targetSessionId = sesionActiva.id;
    const idUser = `msg_${Date.now()}_u`;
    const idAssistant = `msg_${Date.now()}_a`;
    const ahora = new Date().toISOString();

    const msgUsuario: ChatMessage = {
      id: idUser,
      role: 'user',
      content: texto,
      timestamp: ahora,
    };

    const msgAsistenteInicial: ChatMessage = {
      id: idAssistant,
      role: 'assistant',
      content: '',
      timestamp: ahora,
      pasos_herramientas: [],
      isStreaming: true,
    };

    const historialParaApi = [...sesionActiva.mensajes, msgUsuario].map((m) => ({
      role: m.role,
      content: m.content,
      acciones_resumen: m.pasos_herramientas
        ?.map((p) => `${p.herramienta}(${p.resumen || ''})`)
        .join('; '),
      acciones_detalle: m.pasos_herramientas
        ?.map((p) => `[${p.herramienta}] ${p.resumen || ''}\n${(p.detalle || '').slice(0, 1800)}`)
        .join('\n---\n'),
    }));

    setSesiones((prev) =>
      prev.map((s) => {
        if (s.id !== targetSessionId) return s;
        const nuevoTitulo =
          s.mensajes.length === 0
            ? texto.slice(0, 38) + (texto.length > 38 ? '...' : '')
            : s.titulo;
        return {
          ...s,
          titulo: nuevoTitulo,
          actualizadaEn: ahora,
          mensajes: [...s.mensajes, msgUsuario, msgAsistenteInicial],
        };
      })
    );

    const controller = new AbortController();
    abortControllerRef.current = controller;
    jobActivoRef.current = null;
    contadorEventosRef.current = 0;
    setEnviando(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mensajes: historialParaApi,
          usar_tools: usarTools,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Error HTTP ${response.status} al conectar con el servidor API.`);
      }

      const recibioFin = await consumirStream(response, targetSessionId, idAssistant, 0);

      if (!recibioFin) {
        // El stream se cortó pero el trabajo sigue en el servidor: retomarlo en vez de abandonar
        const jobId = jobActivoRef.current;
        if (jobId) {
          const resultado = await seguirJob(
            targetSessionId,
            idAssistant,
            jobId,
            contadorEventosRef.current,
            controller.signal
          );
          if (resultado !== 'ok') {
            marcarCorte(
              targetSessionId,
              idAssistant,
              '> **Aviso:** La conexión de streaming se cerró antes de finalizar. Escribe **"continúa"** para retomar.'
            );
          }
        } else {
          marcarCorte(
            targetSessionId,
            idAssistant,
            '> **Aviso:** La conexión de streaming se cerró antes de finalizar. Escribe **"continúa"** para retomar.'
          );
        }
      }
    } catch (err: unknown) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      patchMensaje(targetSessionId, idAssistant, (m) => ({
        ...m,
        isStreaming: false,
        error: !isAbort,
        content: isAbort
          ? m.content || '*(Generación detenida por el usuario)*'
          : `No se pudo conectar con el backend local (\`http://127.0.0.1:8000\`). Verifica que \`python src/api.py\` esté corriendo y reiniciado.\n\nDetalle: ${
              err instanceof Error ? err.message : String(err)
            }`,
      }));
    } finally {
      setEnviando(false);
      abortControllerRef.current = null;
      jobActivoRef.current = null;
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100 relative">
      {/* Resplandor ambiental sutil */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden z-0">
        <div className="absolute -top-48 left-1/3 w-[560px] h-[560px] rounded-full bg-blue-600/[0.07] dark:bg-blue-500/[0.08] blur-3xl" />
      </div>

      {/* Barra Lateral estilo Gemini */}
      <aside
        className={`${
          sidebarAbierto ? 'w-72' : 'w-0 overflow-hidden border-r-0'
        } transition-all duration-200 shrink-0 z-20 flex flex-col bg-slate-100/90 dark:bg-[#111827]/90 backdrop-blur-xl border-r border-slate-200/80 dark:border-white/[0.08]`}
      >
        <div className="h-14 px-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            <span className="font-semibold text-sm tracking-tight">Platica Studio</span>
          </div>

          <button
            type="button"
            onClick={() => setSidebarAbierto(false)}
            title="Contraer barra lateral"
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white hover:bg-slate-200/60 dark:hover:bg-white/10 transition-colors cursor-pointer"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        <div className="px-3 pb-2">
          <button
            type="button"
            onClick={handleNuevaSesion}
            className="w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-full bg-white dark:bg-[#1E293B] hover:bg-blue-50 dark:hover:bg-[#26354D] border border-slate-200/90 dark:border-white/10 text-slate-800 dark:text-slate-100 text-xs font-semibold transition-colors cursor-pointer shadow-sm"
          >
            <Plus className="w-4 h-4 text-blue-500" />
            <span>Nueva conversación</span>
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1">
          <div className="px-2.5 py-1 text-[11px] font-medium text-slate-400 dark:text-slate-500">
            Recientes
          </div>
          {sesiones.map((ses) => {
            const activa = ses.id === sesionActiva?.id;
            return (
              <div
                key={ses.id}
                onClick={() => {
                  setSesionActivaId(ses.id);
                  setModo('chat');
                }}
                className={`group flex items-center justify-between gap-2 px-3 py-2 rounded-full text-xs font-medium transition-colors cursor-pointer ${
                  activa
                    ? 'bg-blue-500/12 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200'
                    : 'text-slate-600 dark:text-slate-300 hover:bg-slate-200/60 dark:hover:bg-white/[0.06]'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-75" />
                  <span className="truncate">{ses.titulo}</span>
                </div>
                <button
                  type="button"
                  onClick={(e) => handleEliminarSesion(ses.id, e)}
                  title="Eliminar conversación"
                  className="opacity-0 group-hover:opacity-100 p-1 rounded-full text-slate-400 hover:text-red-500 hover:bg-red-500/10 transition-all cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>

        {/* Estado compacto del servidor y herramientas */}
        <div className="p-3.5 border-t border-slate-200/80 dark:border-white/[0.08] space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 font-medium text-slate-700 dark:text-slate-300">
              <span
                className={`w-2 h-2 rounded-full ${
                  salud ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'
                }`}
              />
              {salud ? 'Workspace Conectado' : 'API Desconectada'}
            </span>
            <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
              6 tools
            </span>
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate">
            {salud?.modelo || 'grok-4.7'} · SQLite ({salud?.total_repuestos_catalogo ?? 40} OEM)
          </div>
        </div>
      </aside>

      {/* Lienzo Principal */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 z-10">
        {/* Barra Superior Minimalista estilo Gemini */}
        <header className="h-14 px-4 sm:px-6 flex items-center justify-between shrink-0 border-b border-slate-200/60 dark:border-white/[0.06] bg-slate-50/80 dark:bg-[#0B0F19]/80 backdrop-blur-md">
          <div className="flex items-center gap-2.5">
            {!sidebarAbierto && (
              <button
                type="button"
                onClick={() => setSidebarAbierto(true)}
                title="Abrir barra lateral"
                className="p-2 rounded-xl text-slate-600 dark:text-slate-300 hover:bg-slate-200/60 dark:hover:bg-white/10 transition-colors cursor-pointer"
              >
                <PanelLeftOpen className="w-4 h-4" />
              </button>
            )}

            {/* Selector de Modo */}
            <div className="inline-flex flex-row-reverse p-1 rounded-full bg-slate-200/80 dark:bg-[#131B2E] border border-slate-300/60 dark:border-white/10">
              <button
                type="button"
                onClick={() => setModo('chat')}
                className={`inline-flex items-center gap-1.5 px-3.5 py-1 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                  modo === 'chat'
                    ? 'bg-white dark:bg-blue-600 text-slate-900 dark:text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Chat Agente Workspace</span>
              </button>

              <button
                type="button"
                onClick={() => setModo('vision')}
                className={`inline-flex items-center gap-1.5 px-3.5 py-1 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                  modo === 'vision'
                    ? 'bg-white dark:bg-blue-600 text-slate-900 dark:text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <ScanSearch className="w-3.5 h-3.5" />
                <span>Escáner de Refacciones</span>
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="hidden md:flex items-center gap-2.5 px-3 py-1 rounded-full bg-slate-200/60 dark:bg-[#131B2E] border border-slate-300/50 dark:border-white/10 text-[11px] font-mono">
              <span className="inline-flex items-center gap-1 text-slate-600 dark:text-slate-300">
                <Cpu className="w-3.5 h-3.5 text-blue-500" />
                {telemetriaAcumulada.tokens.toLocaleString()} tok
              </span>
              <span className="text-slate-300 dark:text-slate-700">·</span>
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                <Coins className="w-3.5 h-3.5" />${telemetriaAcumulada.costo.toFixed(5)}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setTemaOscuro((v) => !v)}
              aria-label="Cambiar tema claro u oscuro"
              className="p-2 rounded-full hover:bg-slate-200/70 dark:hover:bg-white/10 text-slate-600 dark:text-slate-300 transition-colors cursor-pointer"
            >
              {temaOscuro ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </header>

        {modo === 'chat' ? (
          <GeminiChatView
            mensajes={sesionActiva?.mensajes || []}
            enviando={enviando}
            usarTools={usarTools}
            onToggleTools={() => setUsarTools((v) => !v)}
            onEnviarMensaje={handleEnviarMensaje}
            onDetenerGeneracion={handleDetenerGeneracion}
            onLimpiarChat={handleLimpiarSesionActiva}
            onIrAEscaner={() => setModo('vision')}
          />
        ) : (
          <VisionScannerView />
        )}
      </div>
    </div>
  );
};
