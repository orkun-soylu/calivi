import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css"; // KaTeX fonts are bundled into the Vite build
import { useT } from "../i18n.js";

// Copyable code block with a header (language + Copy). Used for fenced ```...``` blocks.
function CodeBlock({ lang, code }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* no clipboard access — fail silently */
    }
  }
  return (
    <div className="my-2 rounded-lg overflow-hidden bg-neutral-950">
      <div className="flex items-center justify-between px-3 py-1 bg-neutral-800 text-xs text-neutral-400">
        <span>{lang || "code"}</span>
        <button onClick={copy} className="opacity-70 hover:opacity-100 shrink-0">
          {copied ? <span className="text-green-400">{t("common.copied")}</span> : t("common.copy")}
        </button>
      </div>
      <pre className="themed-scroll overflow-x-auto px-3 py-2 text-xs leading-relaxed whitespace-pre text-neutral-100">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// react-markdown element overrides. Tailwind preflight resets heading/list styles, so every
// block element is styled by hand (this repo does not use the prose plugin).
const components = {
  p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
  h1: ({ children }) => <h1 className="mt-3 mb-2 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-3 mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 mb-1.5 text-sm font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-2 mb-1 text-sm font-semibold">{children}</h4>,
  ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent-text underline hover:opacity-80">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-neutral-600 pl-3 text-neutral-400">{children}</blockquote>
  ),
  hr: () => <hr className="my-3 border-neutral-700" />,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto themed-scroll">
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border border-neutral-700 px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border border-neutral-700 px-2 py-1">{children}</td>,
  // A fenced code block arrives as <pre><code>; we pass <pre> through and turn it into CodeBlock.
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const text = String(Array.isArray(children) ? children.join("") : (children ?? "")).replace(/\n$/, "");
    // Has a language class or is multi-line → block; single line & no language → inline.
    if (match || text.includes("\n")) {
      return <CodeBlock lang={match ? match[1] : ""} code={text} />;
    }
    return <code className="rounded bg-neutral-800 px-1.5 py-0.5 text-[0.85em]">{children}</code>;
  },
};

// Renders assistant content as markdown. Copying (the CopyButton in the footer) takes the raw
// m.content, so the screen shows rendered output while the clipboard gets raw markdown.
// singleDollarTextMath: false → single-dollar math is off so that currency pairs like
// "$62 800 – $64 000" are not mistaken for inline math and drawn in the KaTeX font;
// math is only recognised via $$...$$.
export default function Markdown({ content }) {
  return (
    <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
