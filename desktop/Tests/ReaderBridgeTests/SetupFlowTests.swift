import XCTest
@testable import ReaderBridge

final class SetupFlowTests: XCTestCase {
    private func status(online: Bool = false, kindle: Bool = false, xteink: Bool = false, staged: Bool = false, verified: Bool = false) throws -> BridgeStatus {
        try Backend.decode(Data("""
        {"ok":true,"data":{"service":{"installed":true,"healthy":\(online),"port":8084,"mode":"local","archive":"","pending_backup":0},"kindle":{"paired":\(kindle),"connected":false,"mount":""},"xteink":{"paired":\(xteink),"firmware_staged":\(staged),"url":""},"mounts":[],"highlights":[],"highlight_count":0,"progress_verified":\(verified),"endpoint":"http://192.168.1.20:8084","addresses":[],"warnings":[],"library":{"installed":false,"port":8083,"books":""}}}
        """.utf8))
    }

    private func ready(online: Bool = true, kindle: Bool = true, xteink: Bool = true, staged: Bool = false, firmwareConfirmed: Bool = true, verified: Bool = false) throws -> SetupReadiness {
        SetupReadiness(status: try status(online: online, kindle: kindle, xteink: xteink, staged: staged, verified: verified), firmwareConfirmedByUser: firmwareConfirmed)
    }

    func testResumeUsesSavedFactsAndRequiresCustomFirmwareAcknowledgement() throws {
        XCTAssertEqual(try ready(online: false).recommendedStep, .bridge)
        XCTAssertEqual(try ready(kindle: false, xteink: false).recommendedStep, .kindle)
        XCTAssertEqual(try ready(xteink: false).recommendedStep, .xteink)
        // Stock CrossPoint can sync progress: a prior roundtrip is not custom-firmware evidence.
        let oldPairing = try ready(firmwareConfirmed: false, verified: true)
        XCTAssertEqual(oldPairing.recommendedStep, .xteink)
        XCTAssertFalse(oldPairing.canVisit(.progress))
        XCTAssertFalse(oldPairing.canVisit(.complete))
        XCTAssertEqual(try ready().recommendedStep, .progress)
        XCTAssertEqual(try ready(verified: true).recommendedStep, .complete)
    }

    func testStagedFirmwareCannotAdvanceUntilUserConfirmsInstallation() throws {
        var navigation = SetupNavigation()
        let staged = try ready(staged: true, firmwareConfirmed: false)
        navigation.reconcile(staged)
        XCTAssertEqual(navigation.step, .xteink)
        navigation.advance(staged)
        XCTAssertEqual(navigation.step, .xteink)
        navigation.visit(.progress, readiness: staged)
        XCTAssertEqual(navigation.step, .xteink)
        XCTAssertFalse(navigation.canConfirmRoundTrip(staged))
        let acknowledged = try ready(staged: true)
        navigation.advance(acknowledged)
        XCTAssertEqual(navigation.step, .progress)
        XCTAssertFalse(acknowledged.roundTripConfirmedByUser)
    }

    func testAllStepsAreReachableAndPairingResultsWaitForContinue() throws {
        var navigation = SetupNavigation()
        navigation.reconcile(try ready(online: false, kindle: false, xteink: false))
        let online = try ready(kindle: false, xteink: false)
        navigation.reconcile(online)
        XCTAssertEqual(navigation.step, .bridge)
        navigation.advance(online)
        XCTAssertEqual(navigation.step, .kindle)
        navigation.advance(online)
        XCTAssertEqual(navigation.step, .kindle)
        let kindle = try ready(xteink: false)
        navigation.reconcile(kindle)
        XCTAssertEqual(navigation.step, .kindle)
        navigation.advance(kindle)
        XCTAssertEqual(navigation.step, .xteink)
        navigation.advance(try ready())
        XCTAssertEqual(navigation.step, .progress)
        XCTAssertFalse(navigation.canConfirmRoundTrip(try ready()))
        for _ in 0..<4 { navigation.continueProgress(try ready()) }
        XCTAssertEqual(navigation.checkpoint, .returnToXteink)
        XCTAssertTrue(navigation.canConfirmRoundTrip(try ready()))
        navigation.advance(try ready())
        XCTAssertEqual(navigation.step, .progress)
        navigation.advance(try ready(verified: true))
        XCTAssertEqual(navigation.step, .complete)
    }

    func testBacktrackingAndOfflineRecoveryCannotConfirmProgress() throws {
        var navigation = SetupNavigation()
        let online = try ready()
        navigation.reconcile(online)
        navigation.continueProgress(online)
        navigation.continueProgress(online)
        navigation.back(online)
        XCTAssertEqual(navigation.checkpoint, .xteinkAccount)
        navigation.visit(.kindle, readiness: online)
        XCTAssertEqual(navigation.step, .kindle)
        navigation.visit(.progress, readiness: online)
        XCTAssertEqual(navigation.checkpoint, .sameBook)
        for _ in 0..<4 { navigation.continueProgress(online) }
        let offline = try ready(online: false, verified: true)
        XCTAssertTrue(offline.kindlePaired)
        XCTAssertTrue(offline.xteinkPaired)
        XCTAssertTrue(offline.roundTripConfirmedByUser)
        XCTAssertFalse(navigation.canConfirmRoundTrip(offline))
        navigation.reconcile(offline)
        XCTAssertEqual(navigation.step, .bridge)
        navigation.visit(.complete, readiness: offline)
        XCTAssertEqual(navigation.step, .bridge)
    }

    func testExistingCandidateHealthDoesNotRequireNewCollectorToBeRunning() throws {
        var candidate = try status()
        candidate.existingSetup = .init(available: true, connected: false, healthy: true, port: 8084, archive: "")
        XCTAssertFalse(candidate.service.healthy)
        XCTAssertTrue(candidate.offersExistingSetup)
        XCTAssertTrue(SetupInput.existingCollectorOnline(candidate))
        candidate.existingSetup = .init(available: false, connected: true, healthy: true, port: 8084, archive: "")
        XCTAssertFalse(SetupInput.existingCollectorOnline(candidate))
        candidate.service.healthy = true
        XCTAssertTrue(SetupInput.existingCollectorOnline(candidate))
    }

    func testPairingRequiresExactModelAndDeliberateFirmwareChoice() {
        func permitted(online: Bool = true, endpoint: String = "http://192.168.1.20:8084", connection: Bool = true, model: Bool = true, stage: Bool = true, installed: Bool = false) -> Bool {
            SetupInput.canPairXteink(collectorOnline: online, endpoint: endpoint, connectionValid: connection, modelConfirmed: model, stageFirmware: stage, installedFirmwareConfirmed: installed)
        }
        XCTAssertTrue(permitted())
        XCTAssertFalse(permitted(model: false))
        XCTAssertFalse(permitted(online: false))
        XCTAssertFalse(permitted(connection: false))
        XCTAssertFalse(permitted(endpoint: "http://localhost:8084"))
        XCTAssertFalse(permitted(stage: false))
        XCTAssertTrue(permitted(stage: false, installed: true))
    }

    func testAddressesRejectCredentialsPublicHostsAndPaths() {
        for value in ["http://192.168.1.42", "http://10.0.0.20:8084", "http://172.16.1.20", "http://reader.local:8084"] {
            XCTAssertTrue(SetupInput.validLANAddress(value), value)
        }
        for value in ["", "https://192.168.1.42", "http://localhost", "http://127.0.0.1", "http://8.8.8.8", "http://user:secret@192.168.1.42", "http://192.168.1.42/upload", "http://192.168.1.42?token=secret", "http://192.168.1.42:0", "http://192.168.1.42:99999", "http://172.32.1.1", "http://192.168.01.1"] {
            XCTAssertFalse(SetupInput.validLANAddress(value), value)
        }
        XCTAssertTrue(SetupInput.validCollectorPort("8084"))
        XCTAssertFalse(SetupInput.validCollectorPort("80"))
        XCTAssertFalse(SetupInput.validCollectorPort("65536"))
    }

    func testOnlyOneRecognizedMountIsSuggestedAndUserChoiceIsPreserved() {
        let kindle = BridgeStatus.Mount(name: "Kindle", path: "/Volumes/Kindle", kind: "kindle")
        let secondKindle = BridgeStatus.Mount(name: "Other Kindle", path: "/Volumes/Other Kindle", kind: "kindle")
        let card = BridgeStatus.Mount(name: "Reader Card", path: "/Volumes/Reader Card", kind: "xteink")
        XCTAssertEqual(SetupInput.suggestedMount(kind: "kindle", mounts: [kindle, card], current: ""), kindle.path)
        XCTAssertEqual(SetupInput.suggestedMount(kind: "kindle", mounts: [kindle, secondKindle], current: ""), "")
        XCTAssertEqual(SetupInput.suggestedMount(kind: "xteink", mounts: [kindle], current: ""), "")
        XCTAssertEqual(SetupInput.suggestedMount(kind: "kindle", mounts: [kindle], current: secondKindle.path), secondKindle.path)
    }

    func testFirmwareAcknowledgementBelongsToTheCurrentConnection() throws {
        var original = try status(online: true, kindle: true, xteink: true, staged: true)
        let reference = SetupInput.firmwareConfirmationReference(original)
        original.xteink.url = "http://192.168.1.42"
        XCTAssertNotEqual(reference, SetupInput.firmwareConfirmationReference(original))
        original.xteink.url = ""
        original.service.port = 8090
        XCTAssertNotEqual(reference, SetupInput.firmwareConfirmationReference(original))
    }
}
