import XCTest
@testable import ReaderBridge

final class SetupFlowTests: XCTestCase {
    private func status(online: Bool = false, kindle: Bool = false, xteink: Bool = false, staged: Bool = false, verified: Bool = false) throws -> BridgeStatus {
        try Backend.decode(Data("""
        {"ok":true,"data":{"service":{"installed":true,"healthy":\(online),"port":8084,"mode":"local","archive":"","pending_backup":0},"kindle":{"paired":\(kindle),"connected":false,"mount":""},"xteink":{"paired":\(xteink),"firmware_staged":\(staged),"url":""},"mounts":[],"highlights":[],"highlight_count":0,"progress_verified":\(verified),"endpoint":"http://192.168.1.20:8084","addresses":[],"warnings":[],"library":{"installed":false,"port":8083,"books":""}}}
        """.utf8))
    }

    private func ready(online: Bool = true, kindle: Bool = true, xteink: Bool = true, staged: Bool = false, firmwareConfirmed: Bool = true, verified: Bool = false, progressPaired: Bool = false) throws -> SetupReadiness {
        var saved = try status(online: online, kindle: kindle, xteink: xteink, staged: staged, verified: verified)
        if progressPaired {
            saved.localProgress = .init(enabled: true, healthy: true, endpoint: "http://reader.local:8085", port: 8085, kindlePaired: true, xteinkPaired: true, bookCount: 0, uploads: [], error: "", verified: false)
        }
        return SetupReadiness(status: saved, firmwareConfirmedByUser: firmwareConfirmed)
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
        XCTAssertEqual(try ready(verified: true).recommendedStep, .progress)
        XCTAssertEqual(try ready(progressPaired: true).recommendedStep, .complete)
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
        let acknowledged = try ready(staged: true)
        navigation.advance(acknowledged)
        XCTAssertEqual(navigation.step, .progress)
        XCTAssertFalse(acknowledged.progressConfigured)
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
        navigation.advance(try ready())
        XCTAssertEqual(navigation.step, .progress)
        // Pairing completes setup without a test checkbox or fabricated sync traffic.
        navigation.advance(try ready(progressPaired: true))
        XCTAssertEqual(navigation.step, .complete)
    }

    func testBacktrackingAndOfflineRecoveryPreservePairings() throws {
        var navigation = SetupNavigation()
        let online = try ready()
        navigation.reconcile(online)
        navigation.back(online)
        XCTAssertEqual(navigation.step, .xteink)
        navigation.visit(.kindle, readiness: online)
        XCTAssertEqual(navigation.step, .kindle)
        navigation.visit(.progress, readiness: online)
        XCTAssertEqual(navigation.step, .progress)
        let offline = try ready(online: false, progressPaired: true)
        XCTAssertTrue(offline.kindlePaired)
        XCTAssertTrue(offline.xteinkPaired)
        XCTAssertTrue(offline.progressConfigured)
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
    func testNewUserChoosesReadersBeforeStartingAnySetup() throws {
        let fresh = try status()
        XCTAssertNil(SetupDeviceChoice.resolved(saved: "", status: fresh))
        let readiness = SetupReadiness(status: fresh, firmwareConfirmedByUser: false, deviceChoice: nil)
        XCTAssertEqual(readiness.recommendedStep, .readers)
        XCTAssertEqual(readiness.visibleSteps, [.readers])
        XCTAssertFalse(readiness.canVisit(.bridge))
        var navigation = SetupNavigation()
        navigation.reconcile(readiness)
        navigation.advance(readiness)
        XCTAssertEqual(navigation.step, .readers)
    }

    func testKindleOnlyPathSkipsCrossPointAndCanFinishWithoutPositions() throws {
        let unpaired = SetupReadiness(status: try status(online: true), firmwareConfirmedByUser: false, deviceChoice: .kindle)
        XCTAssertEqual(unpaired.steps, [.readers, .bridge, .kindle, .progress, .complete])
        XCTAssertEqual(unpaired.recommendedStep, .kindle)
        XCTAssertFalse(unpaired.canVisit(.xteink))
        var navigation = SetupNavigation()
        navigation.reconcile(unpaired)
        let paired = SetupReadiness(status: try status(online: true, kindle: true), firmwareConfirmedByUser: false, deviceChoice: .kindle)
        navigation.advance(paired)
        XCTAssertEqual(navigation.step, .progress)
        navigation.advance(paired)
        XCTAssertEqual(navigation.step, .progress)
        let later = SetupReadiness(status: try status(online: true, kindle: true), firmwareConfirmedByUser: false, deviceChoice: .kindle, positionChoice: .later)
        navigation.advance(later)
        XCTAssertEqual(navigation.step, .complete)
        XCTAssertEqual(later.recommendedStep, .complete)
        XCTAssertFalse(later.xteinkPaired)
    }

    func testCrossPointOnlyPathNeverRequiresKindlePairing() throws {
        let unpaired = SetupReadiness(status: try status(online: true), firmwareConfirmedByUser: false, deviceChoice: .crosspoint)
        XCTAssertEqual(unpaired.steps, [.readers, .bridge, .xteink, .progress, .complete])
        XCTAssertEqual(unpaired.recommendedStep, .xteink)
        XCTAssertTrue(unpaired.canVisit(.xteink))
        XCTAssertFalse(unpaired.canVisit(.kindle))
        let staged = SetupReadiness(status: try status(online: true, xteink: true, staged: true), firmwareConfirmedByUser: false, deviceChoice: .crosspoint)
        XCTAssertFalse(staged.canVisit(.progress))
        let confirmed = SetupReadiness(status: try status(online: true, xteink: true, staged: true), firmwareConfirmedByUser: true, deviceChoice: .crosspoint, positionChoice: .later)
        XCTAssertEqual(confirmed.recommendedStep, .complete)
        XCTAssertTrue(confirmed.canVisit(.complete))
        XCTAssertFalse(confirmed.kindlePaired)
    }

    func testEachSelectedReaderCanConfigurePositionsIndependently() throws {
        var saved = try status(online: true, kindle: true, xteink: true)
        saved.localProgress = .init(enabled: true, healthy: true, endpoint: "http://reader.local:8085", port: 8085, kindlePaired: true, xteinkPaired: false, bookCount: 0, uploads: [], error: "", verified: false)
        XCTAssertTrue(SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .kindle).progressConfigured)
        XCTAssertFalse(SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .both).progressConfigured)
        saved.localProgress?.kindlePaired = false
        saved.localProgress?.xteinkPaired = true
        XCTAssertTrue(SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .crosspoint).progressConfigured)
        XCTAssertFalse(SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .both).progressConfigured)
        saved.localProgress?.error = "Reader settings need updating."
        XCTAssertFalse(SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .crosspoint).progressConfigured)
    }

    func testChoiceAndLaterDecisionResumeAfterRestartAndCanAddSecondReader() throws {
        let suite = "Passage.SetupFlowTests.\(UUID().uuidString)"
        let preferences = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { preferences.removePersistentDomain(forName: suite) }
        preferences.set(SetupDeviceChoice.kindle.rawValue, forKey: "setup.devices")
        preferences.set(SetupPositionChoice.later.rawValue, forKey: "setup.positions")
        let restarted = try XCTUnwrap(UserDefaults(suiteName: suite))
        let saved = try status(online: true, kindle: true)
        let choice = SetupDeviceChoice.resolved(saved: restarted.string(forKey: "setup.devices") ?? "", status: saved)
        let decision = SetupPositionChoice(rawValue: restarted.string(forKey: "setup.positions") ?? "") ?? .undecided
        let resumed = SetupReadiness(status: saved, firmwareConfirmedByUser: false, deviceChoice: choice, positionChoice: decision)
        XCTAssertEqual(resumed.recommendedStep, .complete)
        var navigation = SetupNavigation()
        navigation.reconcile(resumed)
        XCTAssertEqual(navigation.step, .complete)
        let secondReader = SetupReadiness(status: saved, firmwareConfirmedByUser: false, deviceChoice: .both, positionChoice: decision)
        navigation.reconcile(secondReader)
        XCTAssertEqual(navigation.step, .xteink)
        XCTAssertTrue(secondReader.kindlePaired)
        XCTAssertEqual(secondReader.positionChoice, .later)
    }

    func testLegacyPairingsInferChoiceAndExplicitChoiceWins() throws {
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "", status: try status(kindle: true)), .kindle)
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "", status: try status(xteink: true)), .crosspoint)
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "", status: try status(kindle: true, xteink: true)), .both)
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "kindle", status: try status(kindle: true, xteink: true)), .kindle)
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "unknown", status: try status(xteink: true)), .crosspoint)
        var progressOnly = try status()
        progressOnly.localProgress = .init(enabled: true, healthy: true, endpoint: "", port: 8085, kindlePaired: false, xteinkPaired: true, bookCount: 0, uploads: [], error: "", verified: false)
        XCTAssertEqual(SetupDeviceChoice.resolved(saved: "", status: progressOnly), .crosspoint)
    }

    func testSelectedModelCannotReuseAnotherModelsPairingOrFirmwareAcknowledgement() throws {
        var saved = try status(online: true, xteink: true)
        saved.xteink.model = "xteink_x4_pro"
        saved.supportedDevices = [BridgeStatus.SupportedDevice.legacyX4Pro, .init(id: "xteink_x4", name: "Xteink X4", capabilities: .init(highlights: true, progress: true, touch: false), pairingSupported: true, firmwareAvailable: false, firmwareFilename: nil, setupUrl: nil, firmwareUpdateInstructions: nil, supportNote: nil)]
        saved.localProgress = .init(enabled: true, healthy: true, endpoint: "", port: 8085, kindlePaired: false, xteinkPaired: true, bookCount: 0, uploads: [], error: "", verified: false, xteinkModel: "xteink_x4_pro")
        let other = SetupReadiness(status: saved, firmwareConfirmedByUser: true, deviceChoice: .crosspoint, crosspointModel: "xteink_x4")
        XCTAssertFalse(other.xteinkPaired)
        XCTAssertFalse(other.progressConfigured)
        XCTAssertEqual(other.recommendedStep, .xteink)
        let reference = SetupInput.firmwareConfirmationReference(saved)
        saved.xteink.model = "xteink_x4"
        XCTAssertNotEqual(reference, SetupInput.firmwareConfirmationReference(saved))
    }

    func testCapabilityAndFirmwareAvailabilityControlPairingRequirements() throws {
        XCTAssertFalse(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: true, installedFirmwareConfirmed: false, firmwareAvailable: false))
        XCTAssertTrue(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: false, installedFirmwareConfirmed: true, firmwareAvailable: false))
        XCTAssertTrue(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: false, installedFirmwareConfirmed: false, highlightsSupported: false, firmwareAvailable: false))
        XCTAssertFalse(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: false, installedFirmwareConfirmed: true, pairingSupported: false))
        var saved = try status(online: true, xteink: true)
        saved.xteink.model = "progress_only"
        saved.supportedDevices = [.init(id: "progress_only", name: "Position reader", capabilities: .init(highlights: false, progress: true, touch: false), pairingSupported: true, firmwareAvailable: false, firmwareFilename: nil, setupUrl: nil, firmwareUpdateInstructions: nil, supportNote: nil)]
        let progressOnly = SetupReadiness(status: saved, firmwareConfirmedByUser: false, deviceChoice: .crosspoint, crosspointModel: "progress_only")
        XCTAssertFalse(progressOnly.firmwareNeedsConfirmation)
        XCTAssertTrue(progressOnly.canVisit(.progress))
    }

    func testBothReadersMayPairCrossPointFirstAndContinueToMissingKindle() throws {
        var navigation = SetupNavigation()
        let fresh = SetupReadiness(status: try status(online: true), firmwareConfirmedByUser: false)
        navigation.reconcile(fresh)
        navigation.visit(.xteink, readiness: fresh)
        XCTAssertEqual(navigation.step, .xteink)
        let crosspointPaired = SetupReadiness(status: try status(online: true, xteink: true), firmwareConfirmedByUser: true, positionChoice: .later)
        XCTAssertEqual(crosspointPaired.nextStep(after: .xteink), .kindle)
        navigation.advance(crosspointPaired)
        XCTAssertEqual(navigation.step, .kindle)
        let bothPaired = SetupReadiness(status: try status(online: true, kindle: true, xteink: true), firmwareConfirmedByUser: true, positionChoice: .later)
        navigation.visit(.xteink, readiness: bothPaired)
        navigation.advance(bothPaired)
        XCTAssertEqual(navigation.step, .complete)
    }

    func testLegacyX4ProAcknowledgementRemainsValidAndInstallLinksAreSafe() throws {
        var legacy = try status(online: true, xteink: true)
        let reference = SetupInput.firmwareConfirmationReference(legacy)
        legacy.xteink.model = BridgeStatus.SupportedDevice.legacyX4Pro.id
        XCTAssertEqual(reference, SetupInput.firmwareConfirmationReference(legacy))
        XCTAssertEqual(SetupInput.installationURL("not a URL").host, "crosspointreader.com")
        XCTAssertEqual(SetupInput.installationURL("javascript:alert(1)").scheme, "https")
        XCTAssertEqual(SetupInput.installationURL("https://crosspointreader.com/#flash-tools").fragment, "flash-tools")
    }

    func testUnavailableFirmwareUsesAlreadyInstalledPathEvenWithStalePrepareChoice() {
        var device = BridgeStatus.SupportedDevice.legacyX4Pro
        device.firmwareAvailable = true
        XCTAssertTrue(SetupInput.shouldPrepareFirmware(requested: true, device: device))
        device.firmwareAvailable = false
        let prepare = SetupInput.shouldPrepareFirmware(requested: true, device: device)
        XCTAssertFalse(prepare)
        XCTAssertTrue(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: prepare, installedFirmwareConfirmed: true, firmwareAvailable: device.firmwareAvailable))
        XCTAssertFalse(SetupInput.canPairXteink(collectorOnline: true, endpoint: "http://reader.local:8084", connectionValid: true, modelConfirmed: true, stageFirmware: prepare, installedFirmwareConfirmed: false, firmwareAvailable: device.firmwareAvailable))
    }

}
