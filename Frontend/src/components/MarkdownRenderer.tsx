import React, { useState } from 'react';
import { Check, Copy, Terminal } from 'lucide-react';

interface MarkdownRendererProps {
  content: string;
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copiado, setCopiado] = useState(false);

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1800);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="my-4 rounded-2xl overflow-hidden border border-slate-200 dark:border-white/10 bg-[#0D1117] shadow-sm">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900/95 border-b border-white/10 text-xs text-slate-300 font-mono">
        <span className="inline-flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-blue-400" />
          <span>{language || 'texto'}</span>
        </span>
        <button
          type="button"
          onClick={copiar}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-slate-300 hover:text-white hover:bg-white/10 transition-colors duration-200 cursor-pointer"
        >
          {copiado ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-emerald-400">Copiado</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copiar</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-4 text-xs sm:text-[13px] font-mono text-slate-100 overflow-x-auto leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function renderInlineFormatting(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code
          key={idx}
          className="px-1.5 py-0.5 mx-0.5 rounded-md font-mono text-[0.86em] bg-slate-200/75 text-slate-900 dark:bg-white/10 dark:text-blue-200"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={idx} className="font-semibold text-slate-900 dark:text-white">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={idx} className="italic text-slate-700 dark:text-slate-300">
          {part.slice(1, -1)}
        </em>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

function parseTableCells(row: string): string[] {
  const trimmed = row.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((c) => c.trim());
}

function isTableSeparator(row: string): boolean {
  const trimmed = row.trim();
  if (!trimmed.includes('|') || !trimmed.includes('-')) return false;
  const cells = parseTableCells(trimmed);
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}

function renderProseBlock(block: string, blockKey: number): React.ReactNode {
  const lines = block.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    // Detectar tabla Markdown (encabezado + separador)
    if (
      trimmed.includes('|') &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const headers = parseTableCells(trimmed);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().includes('|')) {
        rows.push(parseTableCells(lines[i]));
        i += 1;
      }
      elements.push(
        <div
          key={`tbl_${blockKey}_${i}`}
          className="my-4 overflow-x-auto rounded-2xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/50"
        >
          <table className="w-full text-left border-collapse text-xs sm:text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-white/10 bg-slate-100/80 dark:bg-white/5">
                {headers.map((h, hIdx) => (
                  <th
                    key={hIdx}
                    className="px-4 py-2.5 font-semibold text-slate-900 dark:text-slate-100"
                  >
                    {renderInlineFormatting(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200/70 dark:divide-white/5">
              {rows.map((r, rIdx) => (
                <tr
                  key={rIdx}
                  className="hover:bg-slate-100/50 dark:hover:bg-white/[0.03] transition-colors"
                >
                  {headers.map((_, cIdx) => (
                    <td key={cIdx} className="px-4 py-2.5 text-slate-700 dark:text-slate-300">
                      {renderInlineFormatting(r[cIdx] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      elements.push(
        <hr
          key={`hr_${blockKey}_${i}`}
          className="my-4 border-slate-200 dark:border-white/10"
        />
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('#### ')) {
      elements.push(
        <h4
          key={`h4_${blockKey}_${i}`}
          className="text-sm sm:text-base font-semibold text-slate-900 dark:text-white pt-2"
        >
          {renderInlineFormatting(trimmed.slice(5))}
        </h4>
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('### ')) {
      elements.push(
        <h3
          key={`h3_${blockKey}_${i}`}
          className="text-base sm:text-lg font-bold text-slate-900 dark:text-white pt-3"
        >
          {renderInlineFormatting(trimmed.slice(4))}
        </h3>
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('## ')) {
      elements.push(
        <h2
          key={`h2_${blockKey}_${i}`}
          className="text-lg sm:text-xl font-bold text-slate-900 dark:text-white pt-4 pb-1 border-b border-slate-200/80 dark:border-white/10"
        >
          {renderInlineFormatting(trimmed.slice(3))}
        </h2>
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('# ')) {
      elements.push(
        <h1
          key={`h1_${blockKey}_${i}`}
          className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-white pt-4"
        >
          {renderInlineFormatting(trimmed.slice(2))}
        </h1>
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('> ')) {
      elements.push(
        <blockquote
          key={`bq_${blockKey}_${i}`}
          className="pl-4 py-1 my-2 border-l-2 border-blue-500 text-slate-600 dark:text-slate-300 italic"
        >
          {renderInlineFormatting(trimmed.slice(2))}
        </blockquote>
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const indent = rawLine.search(/\S|$/);
      elements.push(
        <div
          key={`ul_${blockKey}_${i}`}
          style={{ paddingLeft: `${Math.min(indent * 6, 28)}px` }}
          className="flex items-start gap-2.5 py-0.5"
        >
          <span className="mt-2.5 w-1.5 h-1.5 rounded-full bg-blue-500 dark:bg-blue-400 shrink-0" />
          <span className="flex-1 leading-7">{renderInlineFormatting(trimmed.slice(2))}</span>
        </div>
      );
      i += 1;
      continue;
    }

    const numberedMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (numberedMatch) {
      elements.push(
        <div key={`ol_${blockKey}_${i}`} className="flex items-start gap-2.5 py-0.5">
          <span className="font-mono text-xs font-semibold text-blue-600 dark:text-blue-400 mt-1.5 shrink-0 min-w-[1.25rem]">
            {numberedMatch[1]}.
          </span>
          <span className="flex-1 leading-7">{renderInlineFormatting(numberedMatch[2])}</span>
        </div>
      );
      i += 1;
      continue;
    }

    elements.push(
      <p key={`p_${blockKey}_${i}`} className="leading-7">
        {renderInlineFormatting(rawLine)}
      </p>
    );
    i += 1;
  }

  return (
    <div key={blockKey} className="space-y-2.5">
      {elements}
    </div>
  );
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  if (!content) return null;

  const segments = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="space-y-3 text-[15px] leading-7 text-slate-800 dark:text-slate-200">
      {segments.map((segment, index) => {
        if (segment.startsWith('```') && segment.endsWith('```')) {
          const lines = segment.slice(3, -3).split('\n');
          const firstLine = (lines[0] || '').trim();
          const code = lines.slice(1).join('\n');
          return <CodeBlock key={index} language={firstLine} code={code} />;
        }
        return renderProseBlock(segment, index);
      })}
    </div>
  );
};
