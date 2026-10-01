import XCTest
@testable import ReaderBridge

final class ModelTests: XCTestCase {
    func fixture(healthy: Bool = false, kindle: Bool = false, xteink: Bool = false, verified: Bool = false) -> Data {
        Data("""
        {"ok":true,"data":{"service":{"installed":true,"healthy":\(healthy),"port":8084,"mode":"local","archive":"","pending_backup":2},"kindle":{"paired":\(kindle),"connected":false,"mount":""},"xteink":{"paired":\(xteink),"firmware_staged":true,"url":""},"mounts":[],"highlights":[{"id":"a","title":"A Book","author":"Ursula","text":"A sentence worth keeping","source":"kindle","created_at":"2026-10-01"}],"highlight_count":1,"progress_verified":\(verified),"endpoint":"http://192.168.1.10:8084","addresses":[],"warnings":[],"library":{"installed":false,"port":8083,"books":""}}}
        """.utf8)
    }
    func testBackendContractDecodesSnakeCase() throws {
        let status = try Backend.decode(fixture())
        XCTAssertEqual(status.service.pendingBackup, 2)
        XCTAssertEqual(status.highlightCount, 1)
        XCTAssertTrue(status.xteink.firmwareStaged)
        XCTAssertEqual(status.highlights.first?.createdAt, "2026-10-01")
    }
    func testSetupRequiresHealthAndExplicitRoundtrip() throws {
        XCTAssertEqual(try Backend.decode(fixture()).setupStep, 1)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true)).setupStep, 2)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true)).setupStep, 3)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true, xteink: true)).setupStep, 4)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true, xteink: true, verified: true)).setupStep, 5)
        XCTAssertEqual(try Backend.decode(fixture(kindle: true, xteink: true, verified: true)).setupStep, 1)
    }
    func testSearchMatchesBookAuthorAndText() throws {
        let highlight = try XCTUnwrap(Backend.decode(fixture()).highlights.first)
        XCTAssertTrue(highlight.matches("BOOK")); XCTAssertTrue(highlight.matches("ursula")); XCTAssertTrue(highlight.matches("worth")); XCTAssertFalse(highlight.matches("unrelated"))
    }
    func testFailureResponseCannotBecomeSuccess() {
        XCTAssertThrowsError(try Backend.decode(Data(#"{"ok":false,"error":"Connect your reader first."}"#.utf8))) { error in XCTAssertEqual(error.localizedDescription, "Connect your reader first.") }
        XCTAssertThrowsError(try Backend.decode(Data(#"{"ok":true}"#.utf8)))
    }
    func testExistingSetupDoesNotImplyProgressWasVerified() throws {
        var response = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture(healthy: true, kindle: true, xteink: true)) as? [String: Any])
        var data = try XCTUnwrap(response["data"] as? [String: Any])
        data["existing_setup"] = ["available": true, "connected": false, "healthy": true, "port": 8084, "archive": "reader/quotes"] as [String: Any]
        response["data"] = data
        let candidate = try Backend.decode(JSONSerialization.data(withJSONObject: response))
        XCTAssertTrue(candidate.offersExistingSetup)
        XCTAssertFalse(candidate.usesExistingSetup)
        data["existing_setup"] = ["available": false, "connected": true, "healthy": false, "port": 8084, "archive": "reader/quotes"] as [String: Any]
        response["data"] = data
        let connected = try Backend.decode(JSONSerialization.data(withJSONObject: response))
        XCTAssertTrue(connected.usesExistingSetup)
        XCTAssertFalse(connected.offersExistingSetup)
        XCTAssertFalse(connected.progressVerified)
        XCTAssertEqual(connected.setupStep, 4)
        XCTAssertNil(try Backend.decode(fixture()).existingSetup)
    }
}
