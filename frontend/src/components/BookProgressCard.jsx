function BookProgressCard({ data }) {
  const getDateLabel = () => {
    if (data.progress_percentage === 0) {
      return "Started tracking";
    } else if (data.progress_percentage === 100) {
      return "Completed";
    } else {
      return "Last read";
    }
  };

  return (
    <div className="book-progress-card">
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
          <div className="book-authors">
            {Array.isArray(data.authors)
              ? data.authors.join(", ")
              : data.authors || "Unknown Author"}
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${data.progress_percentage}%` }}
            ></div>
          </div>
          <div className="progress-text">
            {data.pages_read} of {data.total_pages} pages (
            {data.progress_percentage}%)
          </div>
          <div className="last-read">
            {getDateLabel()}:{" "}
            {new Date(data.last_read_date).toLocaleDateString()}
          </div>
        </div>
      </div>
    </div>
  );
}

export default BookProgressCard;
