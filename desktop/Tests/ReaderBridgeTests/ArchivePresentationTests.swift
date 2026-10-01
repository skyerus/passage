import XCTest
@testable import ReaderBridge

final class ArchivePresentationTests: XCTestCase {
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
