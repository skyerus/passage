import Foundation
import SwiftUI

struct BridgeStatus: Decodable {
    struct Service: Decodable { var installed: Bool; var healthy: Bool; var port: Int; var mode: String; var archive: String; var pendingBackup: Int }
    struct Kindle: Decodable { var paired: Bool; var connected: Bool; var mount: String }
    struct Xteink: Decodable { var paired: Bool; var firmwareStaged: Bool; var url: String }
    struct Mount: Decodable, Identifiable { var name: String; var path: String; var kind: String; var id: String { path } }
    struct Library: Decodable { var installed: Bool; var port: Int; var books: String }
    struct ExistingSetup: Decodable { var available: Bool; var connected: Bool; var healthy: Bool; var port: Int; var archive: String }
    var service: Service; var kindle: Kindle; var xteink: Xteink
    var mounts: [Mount]; var highlights: [Highlight]; var highlightCount: Int
    var progressVerified: Bool; var endpoint: String; var addresses: [String]; var warnings: [String]; var library: Library
    var highlightsLimit: Int?; var highlightsMatches: Int?
    var existingSetup: ExistingSetup?
    var usesExistingSetup: Bool { existingSetup?.connected == true }
    var offersExistingSetup: Bool { existingSetup?.available == true && !usesExistingSetup }
    var setupStep: Int { !service.healthy ? 1 : !kindle.paired ? 2 : !xteink.paired ? 3 : !progressVerified ? 4 : 5 }
}
struct Highlight: Decodable, Identifiable {
    var id: String; var title: String; var author: String; var text: String; var source: String; var createdAt: String
    func matches(_ query: String) -> Bool { query.isEmpty || [title, author, text].contains { $0.localizedCaseInsensitiveContains(query) } }
}
struct BridgeResponse: Decodable { var ok: Bool; var data: BridgeStatus?; var error: String? }
enum BridgeFailure: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { return value }; return nil }
}
final class DataBox: @unchecked Sendable { var value = Data() }
enum Backend {
    static func decode(_ data: Data) throws -> BridgeStatus {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(BridgeResponse.self, from: data)
        guard response.ok, let status = response.data else { throw BridgeFailure.message(response.error ?? "The operation could not be completed.") }
        return status
    }
    static func run(command: String, parameters: [String: Any]) throws -> BridgeStatus {
        let env = ProcessInfo.processInfo.environment
        let resources = Bundle.main.resourceURL ?? Bundle.main.bundleURL
        let python = env["READER_BRIDGE_PYTHON"] ?? resources.appendingPathComponent("runtime/bin/python3").path
        let script = env["READER_BRIDGE_BACKEND"] ?? resources.appendingPathComponent("bridge/desktop.py").path
        guard FileManager.default.isExecutableFile(atPath: python), FileManager.default.fileExists(atPath: script) else {
            throw BridgeFailure.message("Reader Bridge’s bundled runtime is missing. Reinstall the app, or set the documented developer runtime paths.")
        }
        var request = parameters; request["command"] = command
        let input = try JSONSerialization.data(withJSONObject: request)
        let process = Process(); process.executableURL = URL(fileURLWithPath: python)
        process.environment = env.merging(["PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONDONTWRITEBYTECODE": "1"]) { _, trusted in trusted }
        process.arguments = ["-E", "-s", "-B", script]
        if let directory = env["READER_BRIDGE_APP_DIR"] { process.arguments! += ["--app-dir", directory] }
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.standardInput = stdin; process.standardOutput = stdout; process.standardError = stderr
        try process.run()
        let group = DispatchGroup(); let output = DataBox()
        group.enter(); DispatchQueue.global().async { output.value = stdout.fileHandleForReading.readDataToEndOfFile(); group.leave() }
        // Drain stderr concurrently, but never display it: diagnostics may contain credentials.
        group.enter(); DispatchQueue.global().async { _ = stderr.fileHandleForReading.readDataToEndOfFile(); group.leave() }
        try stdin.fileHandleForWriting.write(contentsOf: input); try stdin.fileHandleForWriting.close()
        process.waitUntilExit(); group.wait()
        do { return try decode(output.value) }
        catch let error as BridgeFailure { throw error }
        catch { throw BridgeFailure.message("The helper returned an unreadable response. Restart the app and try again.") }
    }
}
@MainActor final class AppModel: ObservableObject {
    @Published var status: BridgeStatus?
    @Published var busy = false
    @Published private(set) var refreshing = false
    @Published var activity = ""
    @Published var error: String?
    @Published var notice: String?
    @Published var lastUpdated: Date?
    @Published var highlightQuery = ""
    @Published var selection: Section = .overview
    private var requestGeneration = 0
    private let runBackend: (String, [String: Any]) async throws -> BridgeStatus
    init(runBackend: @escaping (String, [String: Any]) async throws -> BridgeStatus = { command, parameters in
        try await Task.detached(priority: .userInitiated) { try Backend.run(command: command, parameters: parameters) }.value
    }) { self.runBackend = runBackend }
    enum Section: String, CaseIterable, Identifiable { case overview = "Overview", setup = "Setup", highlights = "Highlights", settings = "Settings"; var id: String { rawValue }
        var icon: String { switch self { case .overview: return "square.grid.2x2"; case .setup: return "link"; case .highlights: return "text.quote"; case .settings: return "slider.horizontal.3" } }
    }
    var serviceLabel: String { guard error == nil else { return "Status needs attention" }; guard let status else { return "Checking collector…" }; return status.service.healthy ? "Collector online" : "Collector offline" }
    func perform(_ command: String, _ parameters: [String: Any] = [:], activity: String = "Checking status…", success: String? = nil) async {
        if command == "status" { await refreshStatus(interactive: true); return }
        guard !busy else { return }
        requestGeneration += 1
        busy = true; self.activity = activity
        defer { busy = false; self.activity = "" }
        do {
            let newStatus = try await runBackend(command, parameters)
            status = newStatus; lastUpdated = Date(); error = nil
            if let success { notice = success }
        } catch { self.error = error.localizedDescription }
    }
    func refreshStatus(interactive: Bool = false) async {
        guard !busy, !refreshing else { return }
        let generation = requestGeneration
        let query = highlightQuery
        let firstLoad = status == nil
        refreshing = true
        if firstLoad { busy = true; activity = "Opening your bridge…" }
        defer {
            refreshing = false
            if firstLoad { busy = false; activity = "" }
        }
        do {
            let newStatus = try await runBackend("status", ["query": query])
            // A background read must never undo a user action or newer search.
            guard generation == requestGeneration, query == highlightQuery else { return }
            status = newStatus; lastUpdated = Date()
            if interactive { error = nil }
        } catch {
            guard generation == requestGeneration else { return }
            if interactive || self.error == nil { self.error = error.localizedDescription }
        }
    }
    private var pollingTask: Task<Void, Never>?
    private var searchTask: Task<Void, Never>?
    func searchHighlights() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            while (busy || refreshing) && !Task.isCancelled { try? await Task.sleep(nanoseconds: 100_000_000) }
            guard !Task.isCancelled else { return }
            await perform("status")
        }
    }
    func startPolling() { guard pollingTask == nil else { return }; pollingTask = Task { await poll() } }
    func poll() async { while !Task.isCancelled { await refreshStatus(); try? await Task.sleep(nanoseconds: 15_000_000_000) } }
}
