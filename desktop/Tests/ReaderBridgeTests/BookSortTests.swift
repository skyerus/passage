import XCTest
@testable import ReaderBridge

final class BookSortTests: XCTestCase {
    private func book(_ id: String, title: String, author: String = "Writer", count: Int = 1, date: Double? = nil) -> BookSummary {
        BookSummary(id: id, title: title, author: author, count: count, latestHighlightAt: date)
    }

    func testRecentUsesDatesWithUndatedBooksLast() {
        let books = [book("undated", title: "A book"), book("old", title: "B book", date: -10),
                     book("latest", title: "Z book", date: 100), book("epoch", title: "C book", date: 0)]
        XCTAssertEqual(BookSort.recent.sorted(books).map(\.id), ["latest", "epoch", "old", "undated"])
    }

    func testEqualDatesAndUndatedBooksHaveStableAlphabeticalOrder() {
        let books = [book("z", title: "Zulu", date: 10), book("a", title: "Alpha", date: 10),
                     book("u-z", title: "Zebra"), book("u-a", title: "Aardvark")]
        let expected = ["a", "z", "u-a", "u-z"]
        XCTAssertEqual(BookSort.recent.sorted(books).map(\.id), expected)
        XCTAssertEqual(BookSort.recent.sorted(Array(books.reversed())).map(\.id), expected)
    }

    func testTitleAuthorAndHighlightSortsRemainIndependentOfDates() {
        let books = [book("a", title: "Alpha", author: "Zoe", count: 2, date: 10),
                     book("b", title: "Bravo", author: "Amy", count: 4),
                     book("c", title: "Charlie", author: "", count: 4, date: 100)]
        XCTAssertEqual(BookSort.title.sorted(books).map(\.id), ["a", "b", "c"])
        XCTAssertEqual(BookSort.author.sorted(books).map(\.id), ["b", "a", "c"])
        XCTAssertEqual(BookSort.highlights.sorted(books).map(\.id), ["b", "c", "a"])
    }

    func testAlphabeticalTiesUseAuthorThenStableIdentity() {
        let books = [book("z", title: "Book", author: "Zoe"), book("b", title: "Book", author: "Amy"),
                     book("a", title: "Book", author: "Amy")]
        XCTAssertEqual(BookSort.title.sorted(books).map(\.id), ["a", "b", "z"])
    }
}
