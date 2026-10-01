import SwiftUI
import AppKit
import ServiceManagement

struct HighlightsView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    var query: String { model.highlightQuery }
    var filtered: [Highlight] { status.highlights.filter { $0.matches(query) } }
    var body: some View {
        Text("A shared archive of quotes, saved on this Mac. Highlights do not become mirrored underlines on your other reader.").foregroundStyle(.secondary)
        HStack {
            TextField("Search books, authors or words…", text: $model.highlightQuery).textFieldStyle(.roundedBorder)
                .onChange(of: model.highlightQuery) { _ in model.searchHighlights() }
            Button("Import clippings…") {
                let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false; panel.message = "Choose My Clippings.txt from your Kindle."
                if panel.runModal() == .OK, let path = panel.url?.path { Task { await model.perform("import_clippings", ["path": path], activity: "Importing clippings…", success: "Clippings imported into your local archive.") } }
            }.disabled(model.busy || !status.service.healthy)
            Button("Export JSON…") {
                let panel = NSSavePanel(); panel.nameFieldStringValue = "reader-bridge-highlights.json"
                if panel.runModal() == .OK, let path = panel.url?.path { Task { await model.perform("export", ["path": path], activity: "Exporting highlights…", success: "Your highlight archive was exported.") } }
            }.disabled(model.busy || status.highlightCount == 0)
        }
        if let matches = status.highlightsMatches, matches > status.highlights.count {
            Text("Showing the newest \(status.highlights.count) of \(matches) matches. Search covers the full archive; JSON export includes every highlight.").font(.caption).foregroundStyle(.secondary)
        }
        if filtered.isEmpty {
            Card(title: query.isEmpty ? "Your next good line belongs here" : "No matching highlights") {
                Image(systemName: "text.quote").font(.system(size: 35)).foregroundStyle(.secondary)
                Text(query.isEmpty ? "Pair your readers and sync a highlight, or import My Clippings.txt from a Kindle to start your archive." : "Try a different title, author or phrase.").foregroundStyle(.secondary)
            }
        } else {
            Text("\(filtered.count) \(filtered.count == 1 ? "highlight" : "highlights")").font(.caption).foregroundStyle(.secondary)
            LazyVStack(alignment: .leading, spacing: 14) {
                ForEach(filtered) { highlight in
                    Card(title: highlight.title.isEmpty ? "Untitled book" : highlight.title) {
                        if !highlight.author.isEmpty { Text(highlight.author).font(.callout).foregroundStyle(.secondary) }
                        Text(highlight.text).font(.system(size: 17, design: .serif)).lineSpacing(5).textSelection(.enabled)
                        HStack { Text(highlight.source); Spacer(); Text(highlight.createdAt) }.font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}
struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @State private var archive = ""
    @State private var createPrivate = false
    @State private var books = ""
    @State private var libraryPort = "8083"
    @State private var loginEnabled = SMAppService.mainApp.status == .enabled
    @State private var loginError: String?
    @State private var loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
    var body: some View {
        Group {
        Card(title: "Open with your Mac") {
            Toggle("Start Reader Bridge at login", isOn: Binding(get: { loginEnabled }, set: { enabled in
                do {
                    if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                    loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
                    loginEnabled = SMAppService.mainApp.status == .enabled || loginNeedsApproval
                    loginError = nil
                } catch {
                    loginEnabled = SMAppService.mainApp.status == .enabled
                    loginError = "Could not update login settings. Check System Settings → General → Login Items."
                }
            }))
            if loginNeedsApproval { Text("Approve Reader Bridge in System Settings → General → Login Items to finish enabling startup.").font(.caption); Button("Open Login Items") { SMAppService.openSystemSettingsLoginItems() } }
            if let loginError { Text(loginError).foregroundStyle(.orange).font(.caption) }
        }
        Card(title: "GitHub backup · optional") {
            Text("The archive works locally without GitHub. Connect an authenticated GitHub account through the GitHub CLI before enabling backup. Only configure a repository you intend to use for your reading archive.").foregroundStyle(.secondary)
            TextField("OWNER/REPO", text: $archive).textFieldStyle(.roundedBorder)
            Toggle("Create this repository as private if it does not exist", isOn: $createPrivate)
            HStack {
                Button("Enable backup") { Task { await model.perform("configure_backup", ["archive": archive.trimmingCharacters(in: .whitespacesAndNewlines), "create": createPrivate], activity: "Configuring GitHub backup…", success: "GitHub backup configured.") } }.disabled(model.busy || !validArchive)
                if status.service.mode == "github" { Button("Use local archive only") { Task { await model.perform("disable_backup", activity: "Disabling GitHub backup…") } }.disabled(model.busy) }
            }
            if status.service.mode == "github" { Text("Connected: \(status.service.archive)").font(.caption).textSelection(.enabled) }
        }
        Card(title: "Book library · optional") {
            Text("Choose an existing Calibre library containing metadata.db. The app installs Calibre-Web and serves your EPUBs while this Mac is awake.").foregroundStyle(.secondary)
            HStack { TextField("Calibre library folder", text: $books).textFieldStyle(.roundedBorder); Button("Choose…") { if let path = chooseFolder() { books = path } } }
            HStack { Text("Library port"); TextField("8083", text: $libraryPort).textFieldStyle(.roundedBorder).frame(width: 100) }
            Button(status.library.installed ? "Update library" : "Install local library") { Task { await model.perform("install_library", ["books": books, "port": Int(libraryPort) ?? 0], activity: "Installing book library…", success: "Library installed. Follow the library guide to sign in and add its catalog on both readers.") } }.disabled(model.busy || books.isEmpty || !(1024...65535).contains(Int(libraryPort) ?? 0))
            if status.library.installed { Text("Installed on port \(status.library.port)").font(.caption).foregroundStyle(.secondary) }
            Link("Library sign-in and reader setup", destination: URL(string: "https://github.com/skyerus/reader-bridge/blob/main/docs/SETUP.md#5-add-the-home-book-library")!)
        }
        Card(title: "About Reader Bridge") {
            Text("Reading positions and highlight quotes, between KOReader and Xteink X4 Pro. Local storage is the default; GitHub is an optional archive backup.").foregroundStyle(.secondary)
            Link("Documentation & source", destination: URL(string: "https://github.com/skyerus/reader-bridge")!)
        }
        }
        .onAppear { archive = status.service.archive; books = status.library.books; libraryPort = String(status.library.port) }
    }
    var validArchive: Bool { let parts = archive.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "/", omittingEmptySubsequences: false); return parts.count == 2 && parts.allSatisfy { !$0.isEmpty && $0.allSatisfy { $0.isLetter || $0.isNumber || "-_.".contains($0) } } }
}
