function HelpCard({ data, onSend }) {
  // Examples are sent exactly as if the user had typed them.
  const sendExample = (example) => onSend(example.replace(/^"|"$/g, ""));

  return (
    <div className="bdui-help-card">
      <h3 className="bdui-help-card__title">{data.title}</h3>
      <div className="bdui-help-card__grid">
        {(data.features || []).map((feature, idx) => (
          <div key={idx} className="bdui-help-feature">
            <div className="bdui-help-feature__header">
              <span className="bdui-help-feature__icon">
                {renderIcon(feature.icon)}
              </span>
              <h4 className="bdui-help-feature__title">{feature.title}</h4>
            </div>
            <p className="bdui-help-feature__desc">{feature.description}</p>
            <div
              className="bdui-help-feature__example"
              onClick={() => sendExample(feature.example)}
              title="Click to try this command!"
            >
              <span className="bdui-help-feature__example-label">Try:</span>
              <code className="bdui-help-feature__example-text">
                {feature.example}
              </code>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function renderIcon(name) {
  switch (name) {
    case "book-open":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg>
      );
    case "bookmark":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>
      );
    case "pen-tool":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19l7-7 3 3-7 7-3-3z"></path><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"></path><path d="M2 2l7.586 7.586"></path><circle cx="11" cy="11" r="2"></circle></svg>
      );
    case "trending-up":
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>
      );
    default:
      return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
      );
  }
}

export default HelpCard;
