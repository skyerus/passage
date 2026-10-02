import Foundation

enum SetupDeviceChoice: String, CaseIterable, Identifiable {
    case kindle, crosspoint, both
    var id: String { rawValue }
    var includesKindle: Bool { self != .crosspoint }
    var includesCrossPoint: Bool { self != .kindle }
    var title: String {
        switch self {
        case .kindle: return "Kindle"
        case .crosspoint: return "CrossPoint reader"
        case .both: return "Both readers"
        }
    }
    var detail: String {
        switch self {
        case .kindle: return "Save highlights from KOReader."
        case .crosspoint: return "Connect the CrossPoint model you own."
        case .both: return "Bring your highlights and reading places together."
        }
    }
    /// Existing pairings remain usable when upgrading from the two-reader wizard.
    static func resolved(saved: String, status: BridgeStatus) -> Self? {
        if let choice = Self(rawValue: saved) { return choice }
        let kindle = status.kindle.paired || status.localProgress?.kindlePaired == true
        let crosspoint = status.xteink.paired || status.localProgress?.xteinkPaired == true
        if kindle && crosspoint { return .both }
        if kindle { return .kindle }
        if crosspoint { return .crosspoint }
        return nil
    }
}

enum SetupPositionChoice: String {
    case undecided = "", enabled, later
}

enum SetupStep: Int, CaseIterable, Identifiable {
    case readers, bridge, kindle, xteink, progress, complete
    var id: Int { rawValue }
    var title: String {
        switch self {
        case .readers: return "Readers"
        case .bridge: return "Mac"
        case .kindle: return "Kindle"
        case .xteink: return "CrossPoint"
        case .progress: return "Positions"
        case .complete: return "Done"
        }
    }
}

/// Backend facts stay separate from the user's firmware acknowledgement.
/// Neither a pairing file nor a staged binary proves the reader is reachable.
struct SetupReadiness: Equatable {
    var deviceChoice: SetupDeviceChoice?
    var collectorOnline: Bool
    var kindlePaired: Bool
    var xteinkPaired: Bool
    var firmwareStaged: Bool
    var firmwareConfirmedByUser: Bool
    var firmwareRequired: Bool
    var progressConfigured: Bool
    var positionChoice: SetupPositionChoice
    var progressAvailable: Bool

    init(status: BridgeStatus, firmwareConfirmedByUser: Bool, deviceChoice: SetupDeviceChoice? = .both, positionChoice: SetupPositionChoice = .undecided, crosspointModel: String? = nil) {
        self.deviceChoice = deviceChoice
        self.positionChoice = positionChoice
        collectorOnline = status.service.healthy
        kindlePaired = status.kindle.paired
        let model = crosspointModel ?? status.xteink.model ?? BridgeStatus.SupportedDevice.legacyX4Pro.id
        let profile = status.crossPointDevices.first { $0.id == model }
        xteinkPaired = status.xteink.paired && (status.xteink.model ?? BridgeStatus.SupportedDevice.legacyX4Pro.id) == model
        firmwareStaged = status.xteink.firmwareStaged
        self.firmwareConfirmedByUser = firmwareConfirmedByUser
        firmwareRequired = profile?.capabilities.highlights == true
        progressAvailable = deviceChoice?.includesCrossPoint != true || profile?.capabilities.progress == true
        progressConfigured = status.localProgress?.isConfigured(for: deviceChoice ?? .both, crosspointModel: deviceChoice?.includesCrossPoint == true ? model : nil) == true
    }

    var firmwareNeedsConfirmation: Bool { xteinkPaired && firmwareRequired && !firmwareConfirmedByUser }
    var readerPairingComplete: Bool {
        guard let deviceChoice else { return false }
        return (!deviceChoice.includesKindle || kindlePaired) && (!deviceChoice.includesCrossPoint || (xteinkPaired && !firmwareNeedsConfirmation))
    }
    var steps: [SetupStep] {
        guard let deviceChoice else { return [.readers] }
        var result: [SetupStep] = [.readers, .bridge]
        if deviceChoice.includesKindle { result.append(.kindle) }
        if deviceChoice.includesCrossPoint { result.append(.xteink) }
        if progressAvailable { result.append(.progress) }
        return result + [.complete]
    }
    var visibleSteps: [SetupStep] { steps.filter { $0 != .complete } }
    var recommendedStep: SetupStep {
        guard let deviceChoice else { return .readers }
        if !collectorOnline { return .bridge }
        if deviceChoice.includesKindle && !kindlePaired { return .kindle }
        if deviceChoice.includesCrossPoint && (!xteinkPaired || firmwareNeedsConfirmation) { return .xteink }
        if progressAvailable && !progressConfigured && positionChoice != .later { return .progress }
        return .complete
    }

    func nextStep(after step: SetupStep) -> SetupStep? {
        guard let index = steps.firstIndex(of: step), index + 1 < steps.count else { return nil }
        var next = steps[index + 1]
        if next == .progress && positionChoice == .later { next = .complete }
        return canVisit(next) ? next : recommendedStep
    }

    func canVisit(_ step: SetupStep) -> Bool {
        guard steps.contains(step) else { return false }
        switch step {
        case .readers: return true
        case .bridge: return deviceChoice != nil
        case .kindle, .xteink: return collectorOnline
        case .progress: return collectorOnline && readerPairingComplete
        case .complete: return recommendedStep == .complete
        }
    }

    func isComplete(_ step: SetupStep) -> Bool {
        switch step {
        case .readers: return deviceChoice != nil
        case .bridge: return collectorOnline
        case .kindle: return kindlePaired
        case .xteink: return xteinkPaired && !firmwareNeedsConfirmation
        case .progress: return progressConfigured || positionChoice == .later
        case .complete: return recommendedStep == .complete
        }
    }
}

struct SetupNavigation {
    private(set) var step = SetupStep.readers
    private var resumed = false

    mutating func reconcile(_ readiness: SetupReadiness) {
        if !resumed || !readiness.canVisit(step) {
            step = readiness.recommendedStep
        }
        resumed = true
    }

    mutating func visit(_ destination: SetupStep, readiness: SetupReadiness) {
        guard readiness.canVisit(destination) else { return }
        step = destination
    }

    mutating func advance(_ readiness: SetupReadiness) {
        guard readiness.isComplete(step), let next = readiness.nextStep(after: step) else { return }
        visit(next, readiness: readiness)
    }

    mutating func back(_ readiness: SetupReadiness) {
        guard let index = readiness.steps.firstIndex(of: step), index > 0 else { return }
        visit(readiness.steps[index - 1], readiness: readiness)
    }
}

enum SetupInput {
    static func existingCollectorOnline(_ status: BridgeStatus) -> Bool {
        status.offersExistingSetup ? status.existingSetup?.healthy == true : status.service.healthy
    }

    static func shouldPrepareFirmware(requested: Bool, device: BridgeStatus.SupportedDevice?) -> Bool {
        requested && device?.capabilities.highlights == true && device?.firmwareAvailable == true
    }

    static func canPairXteink(collectorOnline: Bool, endpoint: String, connectionValid: Bool, modelConfirmed: Bool, stageFirmware: Bool, installedFirmwareConfirmed: Bool, highlightsSupported: Bool = true, pairingSupported: Bool = true, firmwareAvailable: Bool = true) -> Bool {
        collectorOnline && validLANAddress(endpoint) && connectionValid && modelConfirmed && pairingSupported && (!stageFirmware || firmwareAvailable) && (!highlightsSupported || stageFirmware || installedFirmwareConfirmed)
    }

    static func validCollectorPort(_ text: String) -> Bool {
        Int(text).map { (1024...65535).contains($0) } ?? false
    }

    /// Match the backend's accepted address shape; authentication is still checked there.
    static func validLANAddress(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed == value, let parts = URLComponents(string: trimmed),
              parts.scheme == "http", parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path.allSatisfy({ $0 == "/" }),
              let host = parts.host, (1...65535).contains(parts.port ?? 80) else { return false }
        if host.range(of: "^[A-Za-z0-9-]+\\.local$", options: .regularExpression) != nil { return true }
        let octets = host.split(separator: ".", omittingEmptySubsequences: false)
        guard octets.count == 4 else { return false }
        let numbers = octets.compactMap { piece -> Int? in
            guard !piece.isEmpty, piece.allSatisfy({ $0.isASCII && $0.isNumber }),
                  piece.count == 1 || piece.first != "0", let number = Int(piece), (0...255).contains(number) else { return nil }
            return number
        }
        guard numbers.count == 4 else { return false }
        return numbers[0] == 10 || (numbers[0] == 172 && (16...31).contains(numbers[1])) || (numbers[0] == 192 && numbers[1] == 168)
    }

    static func suggestedMount(kind: String, mounts: [BridgeStatus.Mount], current: String) -> String {
        let candidates = mounts.filter { $0.kind == kind }
        // A user selection is never silently replaced, and ambiguous devices require a choice.
        guard current.isEmpty, candidates.count == 1 else { return current }
        return candidates[0].path
    }

    static func selectedCrossPointModel(saved: String, status: BridgeStatus) -> String {
        if !saved.isEmpty { return saved }
        if status.xteink.paired { return status.xteink.model ?? BridgeStatus.SupportedDevice.legacyX4Pro.id }
        if status.localProgress?.xteinkPaired == true { return status.localProgress?.xteinkModel ?? BridgeStatus.SupportedDevice.legacyX4Pro.id }
        return status.xteink.model ?? status.crossPointDevices.first?.id ?? ""
    }

    static func installationURL(_ value: String?) -> URL {
        if let value, let url = URL(string: value), url.scheme == "https", url.host == "crosspointreader.com" { return url }
        return URL(string: "https://crosspointreader.com/#flash-tools")!
    }

    static func firmwareConfirmationReference(_ status: BridgeStatus) -> String {
        let connection = "\(status.service.port)|\(status.endpoint)|\(status.xteink.url)"
        guard let model = status.xteink.model, model != BridgeStatus.SupportedDevice.legacyX4Pro.id else { return connection }
        return "\(connection)|\(model)"
    }
}
