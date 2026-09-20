import { useState } from "react";
import BookPreviewCard from "./BookPreviewCard";
import BookProgressCard from "./BookProgressCard";

function PaginatedBookList({ books, type = "preview" }) {
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 3;

  if (!books || books.length === 0) return null;

  const totalPages = Math.ceil(books.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const currentBooks = books.slice(startIndex, startIndex + itemsPerPage);

  const handlePrev = () => {
    setCurrentPage((p) => Math.max(1, p - 1));
  };

  const handleNext = () => {
    setCurrentPage((p) => Math.min(totalPages, p + 1));
  };

  return (
    <div className="bdui-paginated-list">
      <div className="bdui-paginated-list__items">
        {currentBooks.map((book, idx) => (
          <div key={idx} className="bdui-paginated-list__item">
            {type === "progress" || book.progress_percentage !== undefined ? (
              <BookProgressCard data={book} />
            ) : (
              <BookPreviewCard data={book} />
            )}
          </div>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="bdui-pagination-controls">
          <button
            className="bdui-pagination-btn"
            onClick={handlePrev}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span className="bdui-pagination-info">
            Page {currentPage} of {totalPages}
          </span>
          <button
            className="bdui-pagination-btn"
            onClick={handleNext}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export default PaginatedBookList;
