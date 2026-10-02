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
    func testSetupUsesPairingsInsteadOfManualTestConfirmation() throws {
        XCTAssertEqual(try Backend.decode(fixture()).setupStep, 1)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true)).setupStep, 2)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true)).setupStep, 3)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true, xteink: true)).setupStep, 4)
        XCTAssertEqual(try Backend.decode(fixture(healthy: true, kindle: true, xteink: true, verified: true)).setupStep, 4)
        var paired = try Backend.decode(fixture(healthy: true, kindle: true, xteink: true))
        paired.localProgress = .init(enabled: true, healthy: true, endpoint: "http://reader.local:8085", port: 8085, kindlePaired: true, xteinkPaired: true, bookCount: 0, uploads: [], error: "", verified: false)
        XCTAssertEqual(paired.setupStep, 5)
        XCTAssertFalse(paired.progressVerified)
        XCTAssertEqual(paired.localProgress?.uploads.count, 0)
        paired.localProgress?.xteinkPaired = false
        XCTAssertEqual(paired.setupStep, 4)
        paired.localProgress?.xteinkPaired = true
        paired.localProgress?.error = "Reconnect Kindle to update its plugin."
        XCTAssertEqual(paired.setupStep, 4)
        paired.localProgress?.error = ""
        paired.localProgress?.enabled = false
        XCTAssertEqual(paired.setupStep, 4)
        XCTAssertEqual(try Backend.decode(fixture(kindle: true, xteink: true, verified: true)).setupStep, 1)
    }
    func testSearchMatchesBookAuthorAndText() throws {
        let highlight = try XCTUnwrap(Backend.decode(fixture()).highlights.first)
        XCTAssertTrue(highlight.matches("BOOK")); XCTAssertTrue(highlight.matches("ursula")); XCTAssertTrue(highlight.matches("worth")); XCTAssertFalse(highlight.matches("unrelated"))
    }
    func testFolderBackupDecodesIndependentlyOfGitHubMode() throws {
        var response = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture()) as? [String: Any])
        var data = try XCTUnwrap(response["data"] as? [String: Any])
        data["cloud_backup"] = ["enabled": true, "provider": "icloud", "folder": "/fixture/backups", "saved_at": "2026-10-01T12:39:00Z", "error": "", "cloud_upload_verified": false] as [String: Any]
        response["data"] = data
        let status = try Backend.decode(JSONSerialization.data(withJSONObject: response))
        XCTAssertEqual(status.service.mode, "local")
        XCTAssertEqual(status.cloudBackup?.provider, "icloud")
        XCTAssertEqual(status.cloudBackup?.enabled, true)
        XCTAssertEqual(status.cloudBackup?.cloudUploadVerified, false)
        XCTAssertNil(try Backend.decode(fixture()).cloudBackup)
    }
    func testPrimaryBackupReflectsICloudEvenWithLegacyGitHubCollector() throws {
        var status = try Backend.decode(fixture())
        status.service.mode = "github"
        status.cloudBackup = .init(enabled: true, provider: "icloud", folder: "/fixture", savedAt: "", error: "", cloudUploadVerified: false)
        XCTAssertEqual(status.backupSummary, "iCloud backup on")
        status.cloudBackup?.error = "Drive unavailable"
        XCTAssertEqual(status.backupSummary, "iCloud backup needs attention")
        status.cloudBackup?.enabled = false
        XCTAssertEqual(status.backupSummary, "GitHub backup on")
    }

    func testLocalProgressIsSeparateFromOldExternalConfirmation() throws {
        var response = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture(verified: true)) as? [String: Any])
        var data = try XCTUnwrap(response["data"] as? [String: Any])
        data["local_progress"] = ["enabled": true, "healthy": true, "endpoint": "http://192.168.1.20:8085", "port": 8085, "kindle_paired": true, "xteink_paired": false, "book_count": 2, "uploads": [["device": "Kindle", "received_at": 1790900000, "count": 1]], "error": "", "verified": false] as [String: Any]
        response["data"] = data
        let status = try Backend.decode(JSONSerialization.data(withJSONObject: response))
        XCTAssertTrue(status.progressVerified)
        XCTAssertEqual(status.localProgress?.verified, false)
        XCTAssertEqual(status.localProgress?.xteinkPaired, false)
        XCTAssertEqual(status.localProgress?.bookCount, 2)
        XCTAssertEqual(status.localProgress?.uploads.first?.device, "Kindle")
        XCTAssertNil(try Backend.decode(fixture()).localProgress)
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
    func testCoverAndBookMetadataDecodeWithoutBreakingOlderArchives() throws {
        var response = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture()) as? [String: Any])
        var data = try XCTUnwrap(response["data"] as? [String: Any])
        var highlights = try XCTUnwrap(data["highlights"] as? [[String: Any]])
        highlights[0]["cover_path"] = "/private/tmp/cover.png"
        highlights[0]["cover_url"] = "https://m.media-amazon.com/images/I/cover.jpg"
        highlights[0]["book_id"] = "book-key"
        data["highlights"] = highlights
        data["books"] = [["id": "book-key", "title": "Book", "author": "Writer", "count": 8, "cover_path": "/private/tmp/cover.png"]]
        response["data"] = data
        let decoded = try Backend.decode(JSONSerialization.data(withJSONObject: response))
        XCTAssertEqual(decoded.highlights[0].coverPath, "/private/tmp/cover.png")
        XCTAssertEqual(decoded.highlights[0].bookId, "book-key")
        XCTAssertEqual(decoded.books?.first?.count, 8)
        XCTAssertEqual(decoded.books?.first?.matches("writer"), true)
        XCTAssertNil(try Backend.decode(fixture()).highlights[0].coverPath)
    }

}
