import XCTest
@testable import ReaderBridge

final class ArchivePresentationTests: XCTestCase {
    func testOrderingDescriptionDistinguishesUndatedArchives() {
        XCTAssertEqual(HighlightPresentation.orderDescription("book_title", undated: 284), "By book · dates unavailable")
        XCTAssertEqual(HighlightPresentation.orderDescription("newest_first", undated: 0), "Newest first")
        XCTAssertEqual(HighlightPresentation.orderDescription("newest_first", undated: 12), "Newest first · undated by book")
    }
    func testOlderBackendDoesNotInventAnOrderingClaim() {
        XCTAssertNil(HighlightPresentation.orderDescription(nil, undated: nil))
        XCTAssertNil(HighlightPresentation.orderDescription("unknown", undated: nil))
    }
    func testPollingDoesNotMoveTheReadersSelection() {
        XCTAssertEqual(HighlightPresentation.selection(current: "chosen", visibleIDs: ["new", "chosen", "older"]), "chosen")
        XCTAssertEqual(HighlightPresentation.selection(current: "chosen", visibleIDs: ["older", "chosen"]), "chosen")
    }
    func testChangingSearchCannotLeaveAnInvisibleSelection() {
        XCTAssertEqual(HighlightPresentation.selection(current: "hidden", visibleIDs: ["match", "other"]), "match")
        XCTAssertNil(HighlightPresentation.selection(current: "hidden", visibleIDs: []))
    }
    func testUnknownMetadataIsPreservedWithoutInventingASourceOrDate() {
        XCTAssertEqual(HighlightPresentation.source("new-reader"), "new-reader")
        XCTAssertEqual(HighlightPresentation.source(""), "Source not recorded")
        XCTAssertEqual(HighlightPresentation.date("saved offline"), "saved offline")
    }
    func testRecordedWallDatesFormatWithoutInventingTimezone() {
        let day = HighlightPresentation.date("2024-04-07")
        XCTAssertNotEqual(day, "2024-04-07")
        XCTAssertEqual(HighlightPresentation.date("2024-04-07T00:01:00"), day)
        XCTAssertEqual(HighlightPresentation.date("2024-04-07 23:59:59"), day)
        XCTAssertEqual(HighlightPresentation.date("2024-02-31 12:00:00"), "2024-02-31 12:00:00")
    }
}
