import BookPreviewCard from "./BookPreviewCard";
import BookProgressCard from "./BookProgressCard";
import PaginatedBookList from "./PaginatedBookList";
import HelpCard from "./HelpCard";
import ErrorBoundary from "./ErrorBoundary";

/**
 * Renders a single BDUI element dict returned by the backend.
 *
 * @param {object}   element       - The BDUI element dict.
 * @param {function} onAction      - Called when an action button is clicked: (action, payload) => void
 */
function BduiRenderer({ element, onAction }) {
  if (!element || !element.type) return null;

  switch (element.type) {
    // ---- composite (recursive) ----
    case "composite":
      return (
        <div className="bdui-composite">
          {(element.elements || []).map((child, i) => (
            <ErrorBoundary key={i}>
              <BduiRenderer element={child} onAction={onAction} />
            </ErrorBoundary>
          ))}
        </div>
      );

    // ---- text ----
    case "text": {
      const style = element.style || "default";
      return (
        <div className={`bdui-text bdui-text--${style}`}>
          {renderMarkdown(element.content || "")}
        </div>
      );
    }

    // ---- book_card ----
    case "book_card":
      return <BookPreviewCard data={element.data || {}} />;

    // ---- book_progress ----
    case "book_progress":
      return <BookProgressCard data={element.data || {}} />;

    // ---- book_list (paginated array of books) ----
    case "book_list":
      return <PaginatedBookList books={element.books || []} />;

    // ---- help_card ----
    case "help_card":
      return <HelpCard data={element} onAction={onAction} />;

    // ---- action_buttons ----
    case "action_buttons":
      return (
        <div
          className={`bdui-action-buttons bdui-action-buttons--${element.layout || "horizontal"}`}
        >
          {(element.buttons || []).map((btn, i) => (
            <button
              key={i}
              className={`bdui-action-btn bdui-action-btn--${btn.variant || "primary"}`}
              onClick={() => onAction?.(btn.action, btn.payload || {})}
            >
              {btn.label}
            </button>
          ))}
        </div>
      );

    // ---- status_card ----
    case "status_card":
      return (
        <div
          className={`bdui-status-card bdui-status-card--${element.status || "info"}`}
        >
          <div className="bdui-status-card__header">
            <span
              className={`bdui-status-badge bdui-status-badge--${element.status || "info"}`}
            >
              {element.status}
            </span>
            <span className="bdui-status-card__title">{element.title}</span>
          </div>
          {element.metrics && element.metrics.length > 0 && (
            <div className="bdui-status-card__metrics">
              {element.metrics.map((m, i) => (
                <div key={i} className="bdui-metric">
                  <span className="bdui-metric__label">{m.label}</span>
                  <span className="bdui-metric__value">{m.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      );

    // ---- key_value ----
    case "key_value":
      return (
        <div className="bdui-key-value">
          {element.title && (
            <div className="bdui-key-value__title">{element.title}</div>
          )}
          <div className="bdui-key-value__list">
            {(element.items || []).map((item, i) => (
              <div key={i} className="bdui-kv-row">
                <span className="bdui-kv-row__key">
                  {item.key || item.label}
                </span>
                <span className="bdui-kv-row__value">{item.value}</span>
              </div>
            ))}
          </div>
        </div>
      );

    // ---- progress (loading indicator) ----
    case "progress":
      return (
        <div className="bdui-progress">
          <div className="bdui-progress__spinner" />
          <span className="bdui-progress__message">{element.message}</span>
        </div>
      );

    // ---- table ----
    case "table":
      return (
        <div className="bdui-table-wrapper">
          {element.title && (
            <div className="bdui-table__title">{element.title}</div>
          )}
          <table className="bdui-table">
            <thead>
              <tr>
                {(element.columns || []).map((col, i) => (
                  <th key={i}>
                    {typeof col === "string" ? col : col.label || col.key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(element.rows || []).map((row, ri) => (
                <tr key={ri}>
                  {(element.columns || []).map((col, ci) => {
                    const key = typeof col === "string" ? col : col.key;
                    return <td key={ci}>{row[key] ?? row[ci] ?? ""}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    default:
      return null;
  }
}

/**
 * Lightweight inline-markdown renderer.
 * Handles: **bold**, *italic*, `code`, and [links](url).
 * We intentionally skip full markdown parsing — this is chat UI, not a docs page.
 */
function renderMarkdown(text) {
  if (!text) return null;

  const lines = text.split("\n");

  return lines.map((line, lineIdx) => {
    // tokenise on inline patterns: bold, italic, code, links
    const tokenPattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
    const parts = line.split(tokenPattern);

    const rendered = parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
        return <em key={i}>{part.slice(1, -1)}</em>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={i} className="inline-code">{part.slice(1, -1)}</code>;
      }
      const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        return (
          <a key={i} href={linkMatch[2]} target="_blank" rel="noopener noreferrer">
            {linkMatch[1]}
          </a>
        );
      }
      return <span key={i}>{part}</span>;
    });

    return (
      <span key={lineIdx}>
        {rendered}
        {lineIdx < lines.length - 1 && <br />}
      </span>
    );
  });
}

export default BduiRenderer;
