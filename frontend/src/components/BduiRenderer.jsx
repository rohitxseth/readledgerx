import BookProgressCard from "./BookProgressCard";
import PaginatedBookList from "./PaginatedBookList";
import HelpCard from "./HelpCard";
import ErrorBoundary from "./ErrorBoundary";

function BduiRenderer({ element, onAction }) {
  if (!element || !element.type) return null;

  switch (element.type) {
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

    case "text": {
      const style = element.style || "default";
      return (
        <div className={`bdui-text bdui-text--${style}`}>
          {renderMarkdown(element.content || "")}
        </div>
      );
    }

    case "book_progress":
      return <BookProgressCard data={element.data || {}} />;

    case "book_list":
      return <PaginatedBookList books={element.books || []} />;

    case "help_card":
      return <HelpCard data={element} onAction={onAction} />;

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

    case "progress":
      return (
        <div className="bdui-progress">
          <div className="bdui-progress__spinner" />
          <span className="bdui-progress__message">{element.message}</span>
        </div>
      );

    default:
      return null;
  }
}

// Inline markdown only (**bold**, *italic*, `code`, [links](url)): chat
// messages don't need a full markdown parser.
function renderMarkdown(text) {
  if (!text) return null;

  const lines = text.split("\n");

  return lines.map((line, lineIdx) => {
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
