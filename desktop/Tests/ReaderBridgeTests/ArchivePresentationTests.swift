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
}
