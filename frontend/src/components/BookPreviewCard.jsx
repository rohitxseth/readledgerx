function BookPreviewCard({ data }) {
  return (
    <div className="book-preview-card">
      <div className="book-card-content">
        {data.thumbnail_url && (
          <img
            src={data.thumbnail_url}
            alt={data.title}
            className="book-thumbnail"
          />
        )}
        <div className="book-info">
          <div className="book-title">{data.title}</div>
          {data.subtitle && (
            <div className="book-subtitle">{data.subtitle}</div>
          )}
          <div className="book-authors">
            {data.authors.join(", ")}
          </div>
          {data.published_date && (
            <div className="book-published">
              Published: {data.published_date}
            </div>
          )}
          {data.page_count > 0 && (
            <div className="book-pages">{data.page_count} pages</div>
          )}
          {data.categories && data.categories.length > 0 && (
            <div className="book-categories">{data.categories.join(", ")}</div>
          )}
          {data.description && (
            <div className="book-description">
              {data.description.length > 200
                ? `${data.description.substring(0, 200)}...`
                : data.description}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default BookPreviewCard;
