import XCTest
@testable import ReaderBridge

final class ImportFlowTests: XCTestCase {
    private func fixture(healthy: Bool = false) throws -> BridgeStatus {
        try Backend.decode(Data("""
        {"ok":true,"data":{"service":{"installed":false,"healthy":\(healthy),"port":8084,"mode":"local","archive":"","pending_backup":0},"kindle":{"paired":false,"connected":false,"mount":""},"xteink":{"paired":false,"firmware_staged":false,"url":""},"mounts":[],"highlights":[],"highlight_count":0,"progress_verified":false,"endpoint":"http://reader.local:8084","addresses":[],"warnings":[],"library":{"installed":false,"port":8083,"books":""}}}
        """.utf8))
    }

    @MainActor func testFreshImportStartsOnlyTheArchiveAndKeepsHighlightsSelected() async throws {
        let fresh = try fixture(), online = try fixture(healthy: true)
        var commands: [String] = []
        var requestedPort: Int?
        let model = AppModel { command, parameters in
            commands.append(command)
            requestedPort = parameters["port"] as? Int
            return online
        }
        model.status = fresh
        let ready = await model.prepareArchiveForImport(port: 8097)
        XCTAssertTrue(ready)
        XCTAssertEqual(commands, ["start_collector"])
        XCTAssertEqual(requestedPort, 8097)
        XCTAssertEqual(model.selection, .highlights)
        XCTAssertFalse(try XCTUnwrap(model.status).kindle.paired)
        XCTAssertFalse(try XCTUnwrap(model.status).xteink.paired)
        XCTAssertNil(model.status?.localProgress)
    }

    @MainActor func testRunningArchiveNeedsNoSetupCommand() async throws {
        var commands: [String] = []
        let online = try fixture(healthy: true)
        let model = AppModel { command, _ in commands.append(command); return online }
        model.status = online
        let ready = await model.prepareArchiveForImport(port: 8097)
        XCTAssertTrue(ready)
        XCTAssertTrue(commands.isEmpty)
    }

    @MainActor func testExistingArchiveIsConnectedInsteadOfStartingAnotherService() async throws {
        var candidate = try fixture(), connected = try fixture(healthy: true)
        candidate.existingSetup = .init(available: true, connected: false, healthy: true, port: 8094, archive: "")
        connected.existingSetup = .init(available: false, connected: true, healthy: true, port: 8094, archive: "")
        var commands: [String] = []
        let model = AppModel { command, _ in commands.append(command); return connected }
        model.status = candidate
        let ready = await model.prepareArchiveForImport(port: 8097)
        XCTAssertTrue(ready)
        XCTAssertEqual(commands, ["connect_existing"])
        XCTAssertTrue(try XCTUnwrap(model.status).usesExistingSetup)
    }

    @MainActor func testPausedExistingArchiveIsOnlyRefreshed() async throws {
        var paused = try fixture()
        paused.existingSetup = .init(available: false, connected: true, healthy: false, port: 8094, archive: "")
        let result = paused
        var commands: [String] = []
        let model = AppModel { command, _ in commands.append(command); return result }
        model.status = paused
        let ready = await model.prepareArchiveForImport(port: 8097)
        XCTAssertFalse(ready)
        XCTAssertEqual(commands, ["status"])
        XCTAssertFalse(try XCTUnwrap(model.status).service.healthy)
    }

    @MainActor func testOccupiedPortStopsImportPreparationAndRetainsTheError() async throws {
        let model = AppModel { _, _ in throw BridgeFailure.message("That port is occupied. Choose an unused port.") }
        model.status = try fixture()
        let ready = await model.prepareArchiveForImport(port: 8084)
        XCTAssertFalse(ready)
        XCTAssertEqual(model.error, "That port is occupied. Choose an unused port.")
        XCTAssertFalse(try XCTUnwrap(model.status).service.healthy)
        XCTAssertFalse(model.busy)
    }

    @MainActor func testHelperSuccessWithoutHealthyServiceCannotOpenImport() async throws {
        let stopped = try fixture()
        let model = AppModel { _, _ in stopped }
        model.status = stopped
        let ready = await model.prepareArchiveForImport(port: 8084)
        XCTAssertFalse(ready)
        XCTAssertNil(model.error)
    }
}
