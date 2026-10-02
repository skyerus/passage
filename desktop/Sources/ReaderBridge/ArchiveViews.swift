import SwiftUI
import AppKit
import ServiceManagement
import UniformTypeIdentifiers

struct HighlightsView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @AppStorage("archive.layout") private var layout = "books"
    @AppStorage("setup.devices") private var savedDeviceChoice = ""
    @AppStorage("setup.positions") private var savedPositionChoice = ""
    @AppStorage("setup.crosspointModel") private var savedCrossPointModel = ""
    @AppStorage("setup.firmwareConfirmedReference") private var firmwareConfirmedReference = ""
    private var setupReadiness: SetupReadiness {
        SetupReadiness(status: status, firmwareConfirmedByUser: !firmwareConfirmedReference.isEmpty && firmwareConfirmedReference == SetupInput.firmwareConfirmationReference(status), deviceChoice: SetupDeviceChoice.resolved(saved: savedDeviceChoice, status: status), positionChoice: SetupPositionChoice(rawValue: savedPositionChoice) ?? .undecided, crosspointModel: savedCrossPointModel.isEmpty ? nil : savedCrossPointModel)
    }
    @AppStorage("archive.bookSort") private var bookSort = BookSort.recent
    @State private var selectedID: String?
    @FocusState private var searchFocused: Bool
    private var query: String { model.highlightQuery }
    private var filtered: [Highlight] { status.highlights.filter { $0.matches(query) && (model.highlightBookID.isEmpty || $0.bookId == model.highlightBookID) } }
    private var books: [BookSummary] { bookSort.sorted((status.books ?? []).filter { $0.matches(query) }) }
    private var selectedBook: BookSummary? { status.books?.first { $0.id == model.highlightBookID } }
    private var selectedHighlight: Highlight? { filtered.first { $0.id == selectedID } }
    private var showingBooks: Bool { layout == "books" && model.highlightBookID.isEmpty }
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            archiveToolbar
            if let backup = status.cloudBackup, !backup.folder.isEmpty {
                HStack {
                    Label(status.backupSummary, systemImage: backup.provider == "icloud" ? "icloud" : "folder")
                        .foregroundStyle(backup.error.isEmpty ? Color.secondary : .orange)
                    Spacer()
                    BackupFinderButton(backup: backup)
                }.font(.caption).padding(.horizontal, 4)
            }
            if let book = selectedBook {
                HStack(spacing: 8) {
                    Button { showAllBooks() } label: { Label("All books", systemImage: "chevron.left") }.buttonStyle(.plain).foregroundStyle(teal)
                    Text("/").foregroundStyle(.tertiary)
                    Text(book.title).lineLimit(1)
                    Spacer()
                    Text("\(book.count) \(book.count == 1 ? "highlight" : "highlights")").foregroundStyle(.secondary).monospacedDigit()
                }.font(.system(size: 12)).padding(.horizontal, 4)
            }
            if status.highlightCount == 0 {
                VStack(spacing: 0) {
                    BridgeEmptyState(symbol: "books.vertical", title: "No highlights yet", detail: setupReadiness.readerPairingComplete ? "Save a highlight on your reader with Wi-Fi connected, or import Kindle highlights." : "Connect your reader to bring your highlights here.")
                    HStack {
                        if !setupReadiness.readerPairingComplete && !status.usesExistingSetup {
                            Button("Set up your reader") { model.selection = .setup }.buttonStyle(.borderedProminent)
                        }
                        Button("Import highlights…", action: importHighlights).buttonStyle(.bordered).disabled(model.busy || !status.service.healthy)
                    }.padding(.bottom, 40)
                }.bridgeSurface()
            } else if showingBooks {
                bookLibrary
            } else if filtered.isEmpty {
                VStack(spacing: 0) {
                    BridgeEmptyState(symbol: "magnifyingglass", title: model.refreshing ? "Opening highlights…" : "No matching highlights", detail: model.refreshing ? "" : "Try another book, author, or phrase.")
                    if !query.isEmpty {
                        Button("Clear search") { model.highlightQuery = ""; model.searchHighlights() }.buttonStyle(.bordered).padding(.bottom, 30)
                    }
                }.bridgeSurface()
            } else {
                GeometryReader { geometry in
                    HStack(spacing: 16) {
                        archiveList.frame(width: geometry.size.width < 740 ? 225 : 275)
                        if let highlight = selectedHighlight {
                            HighlightReadingView(highlight: highlight).frame(maxWidth: .infinity, maxHeight: .infinity)
                        }
                    }
                }
            }
        }
        .onAppear { reconcileSelection() }
        .onChange(of: filtered.map(\.id)) { _ in reconcileSelection() }
        .onChange(of: status.books?.map(\.id)) { _ in
            if !model.highlightBookID.isEmpty, selectedBook == nil { showAllBooks() }
        }
        .onChange(of: layout) { _ in
            if !model.highlightBookID.isEmpty { model.highlightBookID = ""; model.searchHighlights() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .bridgeFindHighlights)) { _ in
            layout = "quotes"; model.highlightBookID = ""; model.searchHighlights(); searchFocused = true
        }
    }
    private var archiveToolbar: some View {
        HStack(spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary).accessibilityHidden(true)
                TextField("Search", text: $model.highlightQuery, prompt: Text(showingBooks ? "Search books or authors" : "Search highlights").foregroundColor(.secondary))
                    .textFieldStyle(.plain).foregroundStyle(.primary).focused($searchFocused)
                    .onChange(of: model.highlightQuery) { _ in model.searchHighlights() }
                    .accessibilityLabel(showingBooks ? "Search books or authors" : "Search highlights")
                if !query.isEmpty {
                    Button { model.highlightQuery = ""; model.searchHighlights() } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
                        .buttonStyle(.plain).accessibilityLabel("Clear search")
                }
            }.font(.system(size: 13)).padding(.horizontal, 14).padding(.vertical, 11).bridgeGlass(cornerRadius: 14)
            Picker("Archive view", selection: $layout) {
                Image(systemName: "books.vertical").tag("books").help("Books")
                Image(systemName: "text.quote").tag("quotes").help("All highlights")
            }.pickerStyle(.segmented).labelsHidden().frame(width: 80).accessibilityLabel("Archive view: books or highlights")
            Menu {
                Button("Import highlights…", action: importHighlights).disabled(model.busy || !status.service.healthy)
                Button("Download missing covers") { Task { await model.perform("cache_covers", activity: "Downloading covers…") } }.disabled(model.busy || status.highlightCount == 0)
                Divider()
                Button("Export highlights & covers…", action: exportArchive).disabled(model.busy || status.highlightCount == 0)
            } label: { Image(systemName: "ellipsis").font(.system(size: 17, weight: .medium)).frame(width: 26, height: 30) }
                .menuStyle(.borderlessButton).fixedSize().padding(.horizontal, 7).padding(.vertical, 3)
                .bridgeGlass(cornerRadius: 14, interactive: true).help("Import highlights, download covers, or export archive").accessibilityLabel("Archive actions")
        }
    }
    private var bookLibrary: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(query.isEmpty ? "YOUR BOOKS" : "MATCHING BOOKS").font(.system(size: 10, weight: .semibold)).tracking(1.2)
                Spacer()
                Text("\(books.count) books").font(.system(size: 11))
                Menu {
                    Picker("Sort books", selection: $bookSort) {
                        ForEach(BookSort.allCases) { order in Text(order.label).tag(order) }
                    }.pickerStyle(.inline)
                } label: {
                    Label(bookSort.label, systemImage: "arrow.up.arrow.down").font(.system(size: 11))
                }
                .menuStyle(.borderlessButton).fixedSize().padding(.leading, 10)
                .accessibilityLabel("Sort books: \(bookSort.label)")
                .help(bookSort == .recent ? "Sort by latest highlight; books without dates appear last" : "Sort books")
            }.foregroundStyle(.secondary).padding(.horizontal, 6)
            if books.isEmpty {
                BridgeEmptyState(symbol: "magnifyingglass", title: "No matching books", detail: "Try another title or author, or switch to highlights to search inside quotes.").bridgeSurface()
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 148, maximum: 205), spacing: 16, alignment: .top)], alignment: .leading, spacing: 18) {
                        ForEach(books) { book in
                            Button { openBook(book) } label: {
                                VStack(alignment: .leading, spacing: 12) {
                                    BookCoverView(title: book.title, path: book.coverPath, width: 96, height: 144)
                                        .frame(maxWidth: .infinity).padding(.top, 7).padding(.bottom, 5)
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(book.title).font(.system(size: 15, weight: .medium, design: .serif)).lineLimit(2).frame(height: 38, alignment: .top)
                                        Text(book.author.isEmpty ? "Unknown author" : book.author).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
                                        Text("\(book.count) \(book.count == 1 ? "highlight" : "highlights")").font(.system(size: 10, weight: .medium)).foregroundStyle(teal).padding(.top, 3)
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                }.padding(15).frame(maxWidth: .infinity, alignment: .leading).bridgeSurface(cornerRadius: 17).contentShape(RoundedRectangle(cornerRadius: 17))
                            }.buttonStyle(.plain)
                                .accessibilityLabel("\(book.title), \(book.author), \(book.count) \(book.count == 1 ? "highlight" : "highlights")")
                                .contextMenu { Button("Change cover…") { chooseBookCover(title: book.title, author: book.author, model: model) }.disabled(model.busy) }
                        }
                    }.padding(3)
                }
            }
        }
    }
    private var archiveList: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("HIGHLIGHTS").font(.system(size: 9, weight: .semibold)).tracking(1)
                Spacer()
                Text(filtered.count.formatted()).font(.system(size: 10)).monospacedDigit()
            }.foregroundStyle(.secondary).padding(.horizontal, 16).padding(.top, 18).padding(.bottom, 10)
            if let order = HighlightPresentation.orderDescription(status.highlightsOrder, undated: status.highlightsUndated) {
                Text(order).font(.system(size: 10)).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.bottom, 8)
            }
            List(selection: $selectedID) {
                ForEach(filtered) { highlight in
                    HighlightArchiveRow(highlight: highlight).tag(highlight.id)
                        .listRowSeparator(.hidden).listRowInsets(EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 12))
                }
            }.listStyle(.plain).scrollContentBackground(.hidden)
            if let matches = status.highlightsMatches, matches > status.highlights.count {
                Text("Showing \(status.highlights.count) of \(matches). Search covers the full archive.").font(.system(size: 10)).foregroundStyle(.secondary).padding(12)
            }
        }.bridgeSurface().clipShape(RoundedRectangle(cornerRadius: 20))
    }
    private func openBook(_ book: BookSummary) {
        model.highlightBookID = book.id; model.highlightQuery = ""; selectedID = nil; model.searchHighlights()
    }
    private func showAllBooks() { model.highlightBookID = ""; model.highlightQuery = ""; layout = "books"; model.searchHighlights() }
    private func reconcileSelection() { selectedID = HighlightPresentation.selection(current: selectedID, visibleIDs: filtered.map(\.id)) }
    private func importHighlights() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.canChooseFiles = true; panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.plainText, .json]
        panel.message = "Choose My Clippings.txt, a Kindle highlights JSON archive, or a Passage export. Covers in JSON are imported too."
        panel.prompt = "Import"
        if panel.runModal() == .OK, let url = panel.url {
            let command = url.pathExtension.lowercased() == "json" ? "import_archive" : "import_clippings"
            Task { await model.perform(command, ["path": url.path], activity: "Importing highlights and covers…", success: "Clippings saved on this Mac. Covers can be added from the book’s menu.") }
        }
    }
    private func exportArchive() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "reader-bridge-highlights.json"; panel.allowedContentTypes = [.json]; panel.prompt = "Export"
        if panel.runModal() == .OK, let path = panel.url?.path {
            Task { await model.perform("export", ["path": path], activity: "Exporting highlights and covers…", success: "Highlights and cached covers exported together.") }
        }
    }
}

struct HighlightArchiveRow: View {
    let highlight: Highlight
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            BookCoverView(title: highlight.title, path: highlight.coverPath, width: 32, height: 48).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(highlight.title.isEmpty ? "Untitled book" : highlight.title).font(.system(size: 14, weight: .medium, design: .serif)).lineLimit(2)
                Text(highlight.text).font(.system(size: 12)).foregroundStyle(.secondary).lineSpacing(2).lineLimit(3)
                Text(highlight.createdAt.isEmpty ? "Date not recorded" : HighlightPresentation.date(highlight.createdAt)).font(.system(size: 9)).foregroundStyle(.secondary)
            }
        }.padding(.vertical, 2).frame(maxWidth: .infinity, alignment: .leading).accessibilityElement(children: .combine)
            .contextMenu { HighlightCopyActions(highlight: highlight) }
    }
}

struct HighlightReadingView: View {
    @EnvironmentObject var model: AppModel
    let highlight: Highlight
    @State private var copiedID: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(HighlightPresentation.source(highlight.source)).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Menu {
                    HighlightCopyActions(highlight: highlight) { copiedID = highlight.id }
                } label: {
                    Label(copiedID == highlight.id ? "Copied" : "Copy", systemImage: copiedID == highlight.id ? "checkmark" : "doc.on.doc")
                }.menuStyle(.borderlessButton).fixedSize().controlSize(.small)
                    .help("Copy the quote alone or with its book and author")
            }.padding(.horizontal, 24).padding(.top, 20).padding(.bottom, 16)
            Divider().padding(.horizontal, 24)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .top, spacing: 20) {
                            cover
                            bookHeading.frame(minWidth: 180, maxWidth: .infinity, alignment: .leading)
                        }
                        VStack(alignment: .leading, spacing: 16) { cover; bookHeading }
                    }
                    Image(systemName: "quote.opening").font(.system(size: 24, weight: .light)).foregroundStyle(teal.opacity(0.7)).padding(.top, 28).padding(.bottom, 14).accessibilityHidden(true)
                    Text(highlight.text).font(.system(size: 20, design: .serif)).lineSpacing(8).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    Text(highlight.createdAt.isEmpty ? "Date not recorded" : HighlightPresentation.date(highlight.createdAt)).font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 27)
                }.padding(24).padding(.bottom, 20)
            }
        }.bridgeSurface().clipShape(RoundedRectangle(cornerRadius: 20)).onChange(of: highlight.id) { _ in copiedID = nil }
    }
    private var cover: some View { BookCoverView(title: highlight.title, path: highlight.coverPath, width: 80, height: 120) }
    private var bookHeading: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(highlight.title.isEmpty ? "Untitled book" : highlight.title).font(.system(size: 23, weight: .medium, design: .serif)).lineSpacing(3).textSelection(.enabled)
            if !highlight.author.isEmpty { Text(highlight.author).font(.system(size: 12)).foregroundStyle(.secondary).textSelection(.enabled) }
            Button(highlight.coverPath?.isEmpty != false ? "Add cover…" : "Change cover…") {
                chooseBookCover(title: highlight.title, author: highlight.author, model: model)
            }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(teal).disabled(model.busy).padding(.top, 3)
        }
    }
}

struct HighlightCopyActions: View {
    let highlight: Highlight
    var onCopy: () -> Void = {}
    var body: some View {
        Button("Copy quote only") { copyHighlight(highlight); onCopy() }
        Button("Copy quote with book & author") { copyHighlight(highlight, includeAttribution: true); onCopy() }
    }
}

func copyHighlight(_ highlight: Highlight, includeAttribution: Bool = false) {
    var text = highlight.text
    if includeAttribution {
        let attribution = [highlight.author, highlight.title]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: ", ")
        if !attribution.isEmpty { text += "\n\n— \(attribution)" }
    }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
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
        // Kindle exports and KOReader record wall time without a timezone.
        // Format that calendar date without shifting it to the Mac's timezone.
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
            let reader = DateFormatter()
            reader.locale = Locale(identifier: "en_US_POSIX")
            reader.calendar = Calendar(identifier: .gregorian)
            reader.timeZone = TimeZone(secondsFromGMT: 0)
            reader.dateFormat = format
            reader.isLenient = false
            if let parsed = reader.date(from: raw), reader.string(from: parsed) == raw {
                let display = DateFormatter()
                display.timeZone = reader.timeZone
                display.dateStyle = .medium
                return display.string(from: parsed)
            }
        }
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
    @State private var progressAddress = ""
    @State private var loginEnabled = SMAppService.mainApp.status == .enabled
    @State private var loginError: String?
    @State private var loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            CloudBackupView(status: status)
            Card(title: "Everyday") {
                BridgeSettingRow(title: "Open at login") {
                    Toggle("Open at login", isOn: Binding(get: { loginEnabled }, set: updateLogin)).labelsHidden().toggleStyle(.switch)
                }
                Divider()
                BridgeSettingRow(title: "Highlight sync") {
                    BridgeStatusBadge(title: model.error != nil ? "Unable to check" : status.service.healthy ? "Ready" : "Paused", healthy: model.error == nil && status.service.healthy)
                }
                if loginNeedsApproval {
                    Text("Approve Passage in System Settings → General → Login Items.").font(.caption).foregroundStyle(.secondary)
                    Button("Open Login Items") { SMAppService.openSystemSettingsLoginItems() }
                }
                if let loginError { Text(loginError).foregroundStyle(.orange).font(.caption) }
            }
            ReadingProgressView(status: status)
            Card(title: "Advanced") {
                DisclosureGroup("Connection details & optional services") {
                    VStack(alignment: .leading, spacing: 14) {
                        LabeledContent("Server address", value: status.endpoint).textSelection(.enabled)
                        LabeledContent("Port", value: String(status.service.port))
                        if let progress = status.localProgress, progress.enabled {
                            TextField("Position sync Mac address", text: $progressAddress).textFieldStyle(.roundedBorder)
                            Button("Update position sync address") {
                                Task { await model.perform("start_progress", ["endpoint": progressAddress, "port": progress.port], activity: "Updating position sync address…", success: "Address saved. Reconnect your selected readers in Setup if the address changed.") }
                            }.disabled(model.busy || !SetupInput.validLANAddress(progressAddress))
                            Text("Changing this address requires reconnecting each reader.").font(.caption).foregroundStyle(.secondary)
                        }
                        if status.usesExistingSetup {
                            Text("Your original Reading Highlights installation manages this service.").font(.caption).foregroundStyle(.secondary)
                            LabeledContent("Additional GitHub backup", value: status.service.mode == "github" ? "Enabled" : "Off")
                            if !status.service.archive.isEmpty {
                                Text(status.service.archive).textSelection(.enabled).font(.caption).foregroundStyle(.secondary)
                            }
                        } else {
                            DisclosureGroup("GitHub backup") { backupSettings.padding(.top, 10) }
                            DisclosureGroup("Book library") { librarySettings.padding(.top, 10) }
                            Button(status.service.healthy ? "Pause highlight sync" : "Start highlight sync") {
                                Task { await model.perform(status.service.healthy ? "stop_collector" : "start_collector", ["port": status.service.port]) }
                            }.disabled(model.busy)
                        }
                        if status.service.mode == "github", status.service.pendingBackup > 0 {
                            Text("\(status.service.pendingBackup) highlights waiting for GitHub backup.").font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(status.warnings, id: \.self) { warning in
                            Text(warning).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
                        }
                    }.font(.callout).padding(.top, 14)
                }
            }
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "books.vertical").foregroundStyle(teal)
                    Text("Passage \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "")").font(.system(size: 14, weight: .medium, design: .serif))
                    Spacer()
                    Link("Documentation & source ↗", destination: URL(string: "https://github.com/skyerus/reader-bridge")!).font(.system(size: 12))
                }
            }.padding(.horizontal, 4).padding(.top, 5)
        }
        .onChange(of: status.localProgress?.endpoint) { progressAddress = $0 ?? "" }
        .onAppear { archive = status.service.archive; books = status.library.books; libraryPort = String(status.library.port); progressAddress = status.localProgress?.endpoint ?? "" }
    }
    private var backupSettings: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sign in with the GitHub CLI, then choose a repository.").font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField("Repository · OWNER/REPO", text: $archive).textFieldStyle(.roundedBorder).accessibilityLabel("GitHub archive repository")
            Toggle("Create a private repository if it is missing", isOn: $createPrivate).font(.callout)
            HStack {
                Button(status.service.mode == "github" ? "Update backup" : "Enable backup") {
                    Task { await model.perform("configure_backup", ["archive": archive.trimmingCharacters(in: .whitespacesAndNewlines), "create": createPrivate], activity: "Configuring GitHub backup…", success: "GitHub backup configured.") }
                }.disabled(model.busy || !validArchive)
                if status.service.mode == "github" {
                    Button("Turn off GitHub backup") { Task { await model.perform("disable_backup", activity: "Disabling GitHub backup…") } }.disabled(model.busy)
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
