import XCTest
@testable import ReaderBridge

@MainActor private final class PendingRead {
    var continuation: CheckedContinuation<BridgeStatus, Error>?
    var didStart: (() -> Void)?
    func read() async throws -> BridgeStatus {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            didStart?()
        }
    }
}

final class RefreshTests: XCTestCase {
    private func fixture(healthy: Bool) throws -> BridgeStatus {
        let json = """
        {"ok":true,"data":{"service":{"installed":true,"healthy":\(healthy),"port":8084,"mode":"local","archive":"","pending_backup":0},"kindle":{"paired":false,"connected":false,"mount":""},"xteink":{"paired":false,"firmware_staged":false,"url":""},"mounts":[],"highlights":[],"highlight_count":0,"progress_verified":false,"endpoint":"http://reader.local:8084","addresses":[],"warnings":[],"library":{"installed":false,"port":8083,"books":""}}}
        """
        return try Backend.decode(Data(json.utf8))
    }

    @MainActor func testBackgroundReadDoesNotBlockOrOverwriteUserAction() async throws {
        let offline = try fixture(healthy: false), online = try fixture(healthy: true)
        let pending = PendingRead()
        let started = expectation(description: "Background status request started")
        pending.didStart = { started.fulfill() }
        var commands: [String] = []
        let model = AppModel { command, _ in
            commands.append(command)
            return command == "status" ? try await pending.read() : online
        }
        model.status = offline
        let refresh = Task { await model.refreshStatus() }
        await fulfillment(of: [started], timeout: 2)
        XCTAssertFalse(model.busy)
        XCTAssertTrue(model.refreshing)
        XCTAssertTrue(model.activity.isEmpty)
        await model.perform("connect_existing", success: "Connected")
        XCTAssertEqual(commands, ["status", "connect_existing"])
        pending.continuation?.resume(returning: offline)
        await refresh.value
        XCTAssertEqual(model.status?.service.healthy, true)
        XCTAssertEqual(model.notice, "Connected")
    }

    @MainActor func testAutomaticRefreshPreservesActionErrorUntilUserRetries() async throws {
        let online = try fixture(healthy: true)
        let model = AppModel { command, _ in
            if command != "status" { throw BridgeFailure.message("Connect your Kindle first.") }
            return online
        }
        model.status = online
        await model.perform("pair_kindle")
        await model.refreshStatus()
        XCTAssertEqual(model.error, "Connect your Kindle first.")
        await model.perform("status")
        XCTAssertNil(model.error)
    }

    @MainActor func testOldSearchResultDoesNotReplaceNewQuery() async throws {
        let online = try fixture(healthy: true), offline = try fixture(healthy: false)
        let pending = PendingRead()
        let started = expectation(description: "Search read started")
        pending.didStart = { started.fulfill() }
        let model = AppModel { _, _ in try await pending.read() }
        model.status = online
        model.highlightQuery = "first query"
        let refresh = Task { await model.refreshStatus() }
        await fulfillment(of: [started], timeout: 2)
        model.highlightQuery = "second query"
        pending.continuation?.resume(returning: offline)
        await refresh.value
        XCTAssertEqual(model.status?.service.healthy, true)
    }
    @MainActor func testOldBookReadDoesNotReplaceNewBookSelection() async throws {
        let online = try fixture(healthy: true), offline = try fixture(healthy: false)
        let pending = PendingRead()
        let started = expectation(description: "Book read started")
        pending.didStart = { started.fulfill() }
        var requestedBook = ""
        let model = AppModel { _, parameters in
            requestedBook = parameters["book_id"] as? String ?? ""
            return try await pending.read()
        }
        model.status = online
        model.highlightBookID = "first"
        let refresh = Task { await model.refreshStatus() }
        await fulfillment(of: [started], timeout: 2)
        XCTAssertEqual(requestedBook, "first")
        model.highlightBookID = "second"
        pending.continuation?.resume(returning: offline)
        await refresh.value
        XCTAssertEqual(model.status?.service.healthy, true)
    }

}
