import SwiftUI
import AppKit
import ServiceManagement
import UniformTypeIdentifiers

struct HighlightsView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @State private var selectedID: String?
    @FocusState private var searchFocused: Bool
    private var query: String { model.highlightQuery }
    private var filtered: [Highlight] { status.highlights.filter { $0.matches(query) } }
    private var selectedHighlight: Highlight? { filtered.first { $0.id == selectedID } }
    var body: some View {
        VStack(alignment: .leading, spacing: 17) {
            archiveToolbar
            if filtered.isEmpty {
                VStack(spacing: 0) {
                    BridgeEmptyState(symbol: query.isEmpty ? "text.quote" : "magnifyingglass", title: query.isEmpty ? "A good line stays with you" : "No matching highlights", detail: query.isEmpty ? "Save a highlight on either reader, or import your Kindle clippings to begin." : "Try another book, author, or phrase.")
                    Button(query.isEmpty ? "Connect your readers" : "Clear search") {
                        if query.isEmpty { model.selection = .setup } else { model.highlightQuery = ""; model.searchHighlights() }
                    }.buttonStyle(.bordered).padding(.bottom, 40)
                }.frame(maxWidth: .infinity, maxHeight: .infinity).bridgeSurface()
            } else {
                GeometryReader { geometry in
                    HStack(spacing: 16) {
                        archiveList.frame(width: geometry.size.width < 740 ? 210 : 260)
                        if let highlight = selectedHighlight {
                            HighlightReadingView(highlight: highlight).frame(maxWidth: .infinity, maxHeight: .infinity)
                        } else {
                            BridgeEmptyState(symbol: "text.quote", title: "Choose a highlight", detail: "Select a line from your archive to read it here.").bridgeSurface()
                        }
                    }
                }
            }
            Text("Quotes are shared here. Underlines stay in their original book.").font(.system(size: 11)).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
        }
        .onAppear { reconcileSelection() }
        .onChange(of: filtered.map(\.id)) { _ in reconcileSelection() }
        .onReceive(NotificationCenter.default.publisher(for: .bridgeFindHighlights)) { _ in searchFocused = true }
    }

    private var archiveToolbar: some View {
        HStack(spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").font(.system(size: 13)).foregroundStyle(.secondary).accessibilityHidden(true)
                TextField("Search highlights", text: $model.highlightQuery, prompt: Text("Search books, authors, or words").foregroundColor(.secondary))
                    .textFieldStyle(.plain).foregroundStyle(.primary).font(.system(size: 13)).focused($searchFocused)
                    .onChange(of: model.highlightQuery) { _ in model.searchHighlights() }
                    .accessibilityLabel("Search highlights")
                if !query.isEmpty {
                    Button { model.highlightQuery = ""; model.searchHighlights(); searchFocused = true } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }.buttonStyle(.plain).help("Clear search").accessibilityLabel("Clear search")
                }
            }.padding(.horizontal, 15).padding(.vertical, 12).bridgeGlass(cornerRadius: 15)
            Menu {
                Button("Import Kindle clippings…", action: importClippings).disabled(model.busy || !status.service.healthy)
                Button("Export archive as JSON…", action: exportArchive).disabled(model.busy || status.highlightCount == 0)
            } label: {
                Image(systemName: "ellipsis").font(.system(size: 17, weight: .medium)).frame(width: 26, height: 30)
            }.menuStyle(.borderlessButton).fixedSize().padding(.horizontal, 9).padding(.vertical, 3)
                .bridgeGlass(cornerRadius: 15, interactive: true).help("Import and export your archive").accessibilityLabel("Archive actions")
        }
    }
    private var archiveList: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(query.isEmpty ? "HIGHLIGHTS" : "SEARCH RESULTS").font(.system(size: 9, weight: .semibold)).tracking(1)
                Spacer()
                Text(filtered.count.formatted()).font(.system(size: 10)).monospacedDigit()
            }.foregroundStyle(.secondary).padding(.horizontal, 17).padding(.top, 18).padding(.bottom, 12)
            if let order = HighlightPresentation.orderDescription(status.highlightsOrder, undated: status.highlightsUndated) {
                Text(order).font(.system(size: 10)).foregroundStyle(.secondary)
                    .padding(.horizontal, 17).padding(.bottom, 8)
                    .help("Recorded dates sort newest first. Highlights without a recorded date follow, ordered by book and author. Importing a highlight does not give it a new creation date.")
            }
            List(selection: $selectedID) {
                ForEach(filtered) { highlight in
                    HighlightArchiveRow(highlight: highlight).tag(highlight.id)
                        .listRowSeparator(.hidden).listRowInsets(EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 12))
                }
            }.listStyle(.plain).scrollContentBackground(.hidden)
            if let matches = status.highlightsMatches, matches > status.highlights.count {
                Text("Showing \(status.highlights.count) of \(matches). Search covers the full archive.")
                    .font(.system(size: 10)).foregroundStyle(.secondary).lineSpacing(3)
                    .padding(.horizontal, 16).padding(.vertical, 12)
            }
        }.bridgeSurface().clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
    private func reconcileSelection() { selectedID = HighlightPresentation.selection(current: selectedID, visibleIDs: filtered.map(\.id)) }
    private func importClippings() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.canChooseFiles = true; panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.plainText]
        panel.message = "Choose My Clippings.txt from your Kindle."
        panel.prompt = "Import clippings"
        if panel.runModal() == .OK, let path = panel.url?.path {
            Task { await model.perform("import_clippings", ["path": path], activity: "Importing clippings…", success: "Clippings imported into your archive.") }
        }
    }
    private func exportArchive() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "reader-bridge-highlights.json"; panel.allowedContentTypes = [.json]
        panel.prompt = "Export archive"
        if panel.runModal() == .OK, let path = panel.url?.path {
            Task { await model.perform("export", ["path": path], activity: "Exporting highlights…", success: "Your highlight archive was exported.") }
        }
    }
}

struct HighlightArchiveRow: View {
    let highlight: Highlight
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(highlight.title.isEmpty ? "Untitled book" : highlight.title).font(.system(size: 15, weight: .medium, design: .serif)).lineLimit(2)
            if !highlight.author.isEmpty { Text(highlight.author).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1) }
            Text(highlight.text).font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(2).lineLimit(3)
            Text(HighlightPresentation.source(highlight.source)).font(.system(size: 9, weight: .medium)).foregroundStyle(.secondary).padding(.top, 2)
        }.padding(.vertical, 2).frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
            .contextMenu { Button("Copy highlight") { copyHighlight(highlight) } }
    }
}

struct HighlightReadingView: View {
    let highlight: Highlight
    @State private var copiedID: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label(HighlightPresentation.source(highlight.source), systemImage: "book.closed").font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Button {
                    copyHighlight(highlight); copiedID = highlight.id
                } label: {
                    Label(copiedID == highlight.id ? "Copied" : "Copy", systemImage: copiedID == highlight.id ? "checkmark" : "doc.on.doc")
                }.buttonStyle(.bordered).controlSize(.small).help("Copy this highlight")
            }.padding(.horizontal, 25).padding(.top, 21).padding(.bottom, 16)
            Divider().padding(.horizontal, 25)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(highlight.title.isEmpty ? "Untitled book" : highlight.title)
                        .font(.system(size: 27, weight: .medium, design: .serif)).lineSpacing(3).textSelection(.enabled)
                    if !highlight.author.isEmpty {
                        Text(highlight.author).font(.system(size: 13)).foregroundStyle(.secondary).padding(.top, 9).textSelection(.enabled)
                    }
                    Image(systemName: "quote.opening").font(.system(size: 24, weight: .light)).foregroundStyle(teal.opacity(0.7)).padding(.top, 30).padding(.bottom, 14).accessibilityHidden(true)
                    Text(highlight.text).font(.system(size: 20, weight: .regular, design: .serif)).lineSpacing(8)
                        .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    Text(highlight.createdAt.isEmpty ? "Date not recorded" : HighlightPresentation.date(highlight.createdAt))
                        .font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 27)
                }.padding(25).padding(.bottom, 20)
            }
        }.bridgeSurface().clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .onChange(of: highlight.id) { _ in copiedID = nil }
    }
}

func copyHighlight(_ highlight: Highlight) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(highlight.text, forType: .string)
}

enum HighlightPresentation {
    static func orderDescription(_ order: String?, undated: Int?) -> String? {
        switch order {
        case "book_title": return "By book · dates unavailable"
        case "newest_first": return (undated ?? 0) > 0 ? "Newest first · undated by book" : "Newest first"
        default: return nil
        }
    }
    static func selection(current: String?, visibleIDs: [String]) -> String? {
        if let current, visibleIDs.contains(current) { return current }
        return visibleIDs.first
    }
    static func source(_ raw: String) -> String {
        switch raw.lowercased() {
        case "koreader", "kindle": return "Kindle · KOReader"
        case "crosspoint", "xteink": return "Xteink X4 Pro"
        case "": return "Source not recorded"
        default: return raw
        }
    }
    static func date(_ raw: String) -> String {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fractional = iso.date(from: raw)
        iso.formatOptions = [.withInternetDateTime]
        if let parsed = fractional ?? iso.date(from: raw) {
            return parsed.formatted(date: .abbreviated, time: .omitted)
        }
        // Preserve unknown source date formats instead of guessing a save date.
        return raw
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
        VStack(alignment: .leading, spacing: 20) {
            Card(title: "Everyday") {
                BridgeSettingRow(title: "Open at login", detail: "Show this app when you sign in to your Mac.") {
                    Toggle("Open at login", isOn: Binding(get: { loginEnabled }, set: updateLogin)).labelsHidden().toggleStyle(.switch)
                }
                Divider()
                BridgeSettingRow(title: "Background collector", detail: status.usesExistingSetup ? "Managed by your existing Reading Highlights service." : "Keeps running when you close or quit this app.") {
                    BridgeStatusBadge(title: model.error != nil ? "Unable to check" : status.service.healthy ? "Online" : "Offline", healthy: model.error == nil && status.service.healthy)
                }
                if loginNeedsApproval {
                    Text("Approve Reader Bridge in System Settings → General → Login Items.").font(.caption).foregroundStyle(.secondary)
                    Button("Open Login Items") { SMAppService.openSystemSettingsLoginItems() }
                }
                if let loginError { Text(loginError).foregroundStyle(.orange).font(.caption) }
            }
            if status.usesExistingSetup {
                Card(title: "Your existing bridge") {
                    Text("Your original installation manages startup, backup, and reader settings.").font(.callout).foregroundStyle(.secondary)
                    LabeledContent("Collector port", value: String(status.service.port)).font(.callout)
                    LabeledContent("Archive backup", value: status.service.archive.isEmpty ? "Local only" : status.service.archive).font(.callout).textSelection(.enabled)
                }
            } else {
                Card(title: "Optional extras") {
                    DisclosureGroup {
                        backupSettings.padding(.top, 14).padding(.bottom, 9)
                    } label: {
                        settingsLabel("GitHub backup", detail: status.service.mode == "github" ? "Enabled · \(status.service.archive)" : "Keep an additional copy of your archive", symbol: "externaldrive")
                    }
                    Divider()
                    DisclosureGroup {
                        librarySettings.padding(.top, 14).padding(.bottom, 9)
                    } label: {
                        settingsLabel("Book library", detail: status.library.installed ? "Installed · port \(status.library.port)" : "Serve your Calibre books to your readers", symbol: "books.vertical")
                    }
                }
            }
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "books.vertical").foregroundStyle(teal)
                    Text("Reader Bridge").font(.system(size: 14, weight: .medium, design: .serif))
                    Spacer()
                    Link("Documentation & source ↗", destination: URL(string: "https://github.com/skyerus/reader-bridge")!).font(.system(size: 12))
                }
                Text("Highlights stay local by default. The bridge receives uploads while your Mac is awake.")
                    .font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(3)
            }.padding(.horizontal, 4).padding(.top, 5)
        }
        .onAppear { archive = status.service.archive; books = status.library.books; libraryPort = String(status.library.port) }
    }
    private var backupSettings: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sign in through the GitHub CLI first, then choose a repository for your reading archive.").font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField("Repository · OWNER/REPO", text: $archive).textFieldStyle(.roundedBorder).accessibilityLabel("GitHub archive repository")
            Toggle("Create a private repository if it is missing", isOn: $createPrivate).font(.callout)
            HStack {
                Button(status.service.mode == "github" ? "Update backup" : "Enable backup") {
                    Task { await model.perform("configure_backup", ["archive": archive.trimmingCharacters(in: .whitespacesAndNewlines), "create": createPrivate], activity: "Configuring GitHub backup…", success: "GitHub backup configured.") }
                }.disabled(model.busy || !validArchive)
                if status.service.mode == "github" {
                    Button("Use local archive only") { Task { await model.perform("disable_backup", activity: "Disabling GitHub backup…") } }.disabled(model.busy)
                }
            }
            if status.service.pendingBackup > 0, status.service.mode == "github" {
                Text("\(status.service.pendingBackup) highlights awaiting backup.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    private var librarySettings: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Choose a Calibre folder containing metadata.db. This installs Calibre-Web and downloads its dependencies.").font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                TextField("Calibre library folder", text: $books).textFieldStyle(.roundedBorder)
                Button("Choose…") { if let path = chooseFolder() { books = path } }
            }
            HStack {
                Text("Library port").font(.callout)
                TextField("8083", text: $libraryPort).textFieldStyle(.roundedBorder).frame(width: 85).accessibilityLabel("Library port")
                Text("1024–65535").font(.caption).foregroundStyle(.secondary)
            }
            Button(status.library.installed ? "Update library" : "Install book library") {
                Task { await model.perform("install_library", ["books": books, "port": Int(libraryPort) ?? 0], activity: "Installing book library…", success: "Library installed. Follow the guide to sign in and add its catalog on both readers.") }
            }.disabled(model.busy || books.isEmpty || !(1024...65535).contains(Int(libraryPort) ?? 0))
            Link("Library sign-in and reader setup ↗", destination: URL(string: "https://github.com/skyerus/reader-bridge/blob/main/docs/SETUP.md#5-add-the-home-book-library")!).font(.caption)
        }
    }
    private func settingsLabel(_ title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.system(size: 18, weight: .light)).foregroundStyle(teal).frame(width: 25).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 14, weight: .medium)).foregroundStyle(.primary)
                Text(detail).font(.system(size: 12)).foregroundStyle(.secondary)
            }
        }.padding(.vertical, 5)
    }
    private func updateLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
            loginEnabled = SMAppService.mainApp.status == .enabled || loginNeedsApproval
            loginError = nil
        } catch {
            loginEnabled = SMAppService.mainApp.status == .enabled
            loginError = "Could not update login settings. Check System Settings → General → Login Items."
        }
    }
    private var validArchive: Bool {
        let parts = archive.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "/", omittingEmptySubsequences: false)
        return parts.count == 2 && parts.allSatisfy { !$0.isEmpty && $0.allSatisfy { $0.isLetter || $0.isNumber || "-_.".contains($0) } }
    }
}
