export type StudioMode = 'chat' | 'vision';

export interface UsageTelemetry {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  costo_usd: number;
}

export interface AgentToolStep {
  id: string;
  iteracion: number;
  herramienta: string;
  argumentos: Record<string, unknown>;
  estado: 'running' | 'done' | 'error';
  resumen?: string;
  detalle?: string;
  duracion_ms?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  pasos_herramientas?: AgentToolStep[];
  latencia_segundos?: number;
  usage?: UsageTelemetry;
  isStreaming?: boolean;
  error?: boolean;
  job_id?: string;
  job_eventos?: number;
}

export interface ChatSession {
  id: string;
  titulo: string;
  creadaEn: string;
  actualizadaEn: string;
  mensajes: ChatMessage[];
}

export interface FotoMuestra {
  archivo: string;
  titulo: string;
  subtitulo: string;
  url: string;
}

export interface SaludBackend {
  estado: string;
  modelo: string;
  endpoint: string;
  herramientas_chat?: string[];
  total_repuestos_catalogo: number;
  unidades_stock_erp: number;
  cotizaciones_generadas: number;
  fotos_muestra?: FotoMuestra[];
}
