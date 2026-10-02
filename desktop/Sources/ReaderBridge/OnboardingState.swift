import Foundation

enum SetupStep: Int, CaseIterable, Identifiable {
    case bridge, kindle, xteink, progress, complete
    var id: Int { rawValue }
    static var visibleSteps: [Self] { [.bridge, .kindle, .xteink, .progress] }
    var title: String {
        switch self {
        case .bridge: return "Mac"
        case .kindle: return "Kindle"
        case .xteink: return "X4 Pro"
        case .progress: return "Positions"
        case .complete: return "Done"
        }
    }
}

/// Backend facts stay separate from the user's firmware acknowledgement.
/// Neither a pairing file nor a staged binary proves the reader is reachable.
struct SetupReadiness: Equatable {
    var collectorOnline: Bool
    var kindlePaired: Bool
    var xteinkPaired: Bool
    var firmwareStaged: Bool
    var firmwareConfirmedByUser: Bool
    var progressConfigured: Bool

    init(status: BridgeStatus, firmwareConfirmedByUser: Bool) {
        collectorOnline = status.service.healthy
        kindlePaired = status.kindle.paired
        xteinkPaired = status.xteink.paired
        firmwareStaged = status.xteink.firmwareStaged
        self.firmwareConfirmedByUser = firmwareConfirmedByUser
        progressConfigured = status.localProgress?.isConfigured == true
    }

    var firmwareNeedsConfirmation: Bool { xteinkPaired && !firmwareConfirmedByUser }
    var recommendedStep: SetupStep {
        if !collectorOnline { return .bridge }
        if !kindlePaired { return .kindle }
        if !xteinkPaired || firmwareNeedsConfirmation { return .xteink }
        if !progressConfigured { return .progress }
        return .complete
    }

    func canVisit(_ step: SetupStep) -> Bool {
        switch step {
        case .bridge: return true
        case .kindle: return collectorOnline
        case .xteink: return collectorOnline && kindlePaired
        case .progress: return collectorOnline && kindlePaired && xteinkPaired && !firmwareNeedsConfirmation
        case .complete: return recommendedStep == .complete
        }
    }

    func isComplete(_ step: SetupStep) -> Bool {
        switch step {
        case .bridge: return collectorOnline
        case .kindle: return kindlePaired
        case .xteink: return xteinkPaired && !firmwareNeedsConfirmation
        case .progress, .complete: return progressConfigured
        }
    }
}

struct SetupNavigation {
    private(set) var step = SetupStep.bridge
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
        guard readiness.isComplete(step), let next = SetupStep(rawValue: step.rawValue + 1) else { return }
        visit(next, readiness: readiness)
    }

    mutating func back(_ readiness: SetupReadiness) {
        if let previous = SetupStep(rawValue: step.rawValue - 1) {
            visit(previous, readiness: readiness)
        }
    }
}

enum SetupInput {
    static func existingCollectorOnline(_ status: BridgeStatus) -> Bool {
        status.offersExistingSetup ? status.existingSetup?.healthy == true : status.service.healthy
    }

    static func canPairXteink(collectorOnline: Bool, endpoint: String, connectionValid: Bool, modelConfirmed: Bool, stageFirmware: Bool, installedFirmwareConfirmed: Bool) -> Bool {
        collectorOnline && validLANAddress(endpoint) && connectionValid && modelConfirmed && (stageFirmware || installedFirmwareConfirmed)
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

    static func firmwareConfirmationReference(_ status: BridgeStatus) -> String {
        "\(status.service.port)|\(status.endpoint)|\(status.xteink.url)"
    }
}
