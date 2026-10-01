import SwiftUI
import AppKit

@main struct ReaderBridgeApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("Reader Bridge", id: "main") {
            ContentView().environmentObject(model)
                .frame(minWidth: 850, minHeight: 650)
                .task { model.startPolling() }
        }
        .defaultSize(width: 1180, height: 790)
        .windowToolbarStyle(.unifiedCompact)
        .commands { BridgeCommands(model: model) }
        MenuBarExtra {
            MenuContent().environmentObject(model)
        } label: {
            Image(systemName: model.error == nil && model.status?.service.healthy == true ? "book.closed.fill" : "book.closed")
        }
    }
}

struct BridgeCommands: Commands {
    @ObservedObject var model: AppModel
    var body: some Commands {
        CommandMenu("Go") {
            ForEach(Array(AppModel.Section.allCases.enumerated()), id: \.element.id) { index, section in
                Button(section.rawValue) { model.selection = section }
                    .keyboardShortcut(KeyEquivalent(Character(String(index + 1))), modifiers: .command)
            }
            Divider()
            Button("Find Highlights") {
                model.selection = .highlights
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    NotificationCenter.default.post(name: .bridgeFindHighlights, object: nil)
                }
            }.keyboardShortcut("f", modifiers: .command)
            Button("Refresh Status") { Task { await model.perform("status") } }
                .keyboardShortcut("r", modifiers: .command).disabled(model.busy)
        }
    }
}

struct MenuContent: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) var openWindow
    var body: some View {
        Text(model.serviceLabel)
        if let status = model.status { Text("\(status.highlightCount) archived highlights") }
        if model.busy { Text(model.activity) }
        Divider()
        Button("Open Reader Bridge") { openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        Button("Refresh status") { Task { await model.perform("status") } }.disabled(model.busy)
        Divider()
        Button("Quit Reader Bridge") { NSApp.terminate(nil) }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        HStack(spacing: 0) {
            BridgeSidebar().frame(width: 196)
            VStack(alignment: .leading, spacing: 20) {
                pageHeader
                if let error = model.error { message(error, symbol: "exclamationmark.triangle.fill", color: .orange) }
                if let notice = model.notice {
                    message(notice, symbol: "checkmark.circle.fill", color: teal) { model.notice = nil }
                }
                if let status = model.status {
                    if model.selection == .highlights {
                        HighlightsView(status: status)
                    } else {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 20) {
                                switch model.selection {
                                case .overview: OverviewView(status: status)
                                case .setup: SetupView(status: status)
                                case .settings: SettingsView(status: status)
                                case .highlights: EmptyView()
                                }
                            }.frame(maxWidth: 920, alignment: .leading)
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.bottom, 24)
                        }
                    }
                } else {
                    BridgeEmptyState(symbol: "books.vertical", title: model.busy ? "Opening your bridge" : "The bridge is unavailable", detail: model.busy ? "Checking the local collector and archive…" : "Refresh to reconnect to the local helper.")
                }
            }
            .padding(.horizontal, 28).padding(.top, 25).padding(.bottom, 24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(BridgeCanvas()).foregroundStyle(ink).tint(teal)
        .overlay(alignment: .bottomTrailing) {
            if model.busy, model.status != nil {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text(model.activity).font(.callout).lineLimit(2)
                }.padding(.horizontal, 17).padding(.vertical, 12)
                    .frame(maxWidth: 420, alignment: .leading).bridgeGlass(cornerRadius: 16)
                    .padding(24).accessibilityElement(children: .combine)
            }
        }
    }

    private var pageHeader: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 5) {
                Text(model.selection.rawValue).font(.system(size: 30, weight: .medium, design: .serif))
                Text(subtitle).font(.system(size: 13)).foregroundStyle(.secondary)
            }
            Spacer()
            Button { Task { await model.perform("status") } } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 14, weight: .medium)).frame(width: 36, height: 36)
            }
            .buttonStyle(.plain).bridgeGlass(cornerRadius: 18, interactive: true)
            .disabled(model.busy).help("Refresh status (⌘R)").accessibilityLabel("Refresh status")
        }
    }
    private var subtitle: String {
        switch model.selection {
        case .overview: return "A home for the lines you keep."
        case .setup: return "Connect once. Keep your reading close."
        case .highlights: return "Your quotes, gathered on this Mac."
        case .settings: return "A few preferences. Everything in its place."
        }
    }
    private func message(_ text: String, symbol: String, color: Color, dismiss: (() -> Void)? = nil) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(color).padding(.top, 1)
            Text(text).font(.callout).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if let dismiss {
                Button(action: dismiss) { Image(systemName: "xmark").font(.system(size: 11, weight: .medium)) }
                    .buttonStyle(.plain).foregroundStyle(.secondary).help("Dismiss message").accessibilityLabel("Dismiss message")
            }
        }.padding(13).background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }
}

struct BridgeSidebar: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 13) {
                Image(systemName: "books.vertical").font(.system(size: 27, weight: .light)).foregroundStyle(teal)
                    .accessibilityHidden(true)
                Text("Reader Bridge").font(.system(size: 22, weight: .medium, design: .serif))
                Text("YOUR READING, TOGETHER").font(.system(size: 8, weight: .semibold)).tracking(1.1).foregroundStyle(.secondary)
            }.padding(.horizontal, 15).padding(.top, 25).padding(.bottom, 32)
            VStack(spacing: 5) {
                ForEach(AppModel.Section.allCases) { section in
                    Button { model.selection = section } label: {
                        HStack(spacing: 0) {
                            HStack(spacing: 8) {
                                Image(systemName: section.icon).font(.system(size: 15, weight: .medium)).frame(width: 19)
                                Text(section.rawValue).font(.system(size: 13, weight: model.selection == section ? .semibold : .medium))
                                    .lineLimit(1).fixedSize(horizontal: true, vertical: false)
                            }
                            Spacer(minLength: 8)
                            if section == .highlights, let count = model.status?.highlightCount, count > 0 {
                                Text(count.formatted(.number.notation(.compactName)))
                                    .font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary)
                                    .lineLimit(1).minimumScaleFactor(0.8)
                                    .help("\(count.formatted()) highlights").accessibilityLabel(count.formatted())
                            }
                        }.padding(.horizontal, 12).padding(.vertical, 11)
                            .background(model.selection == section ? teal.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 11))
                            .contentShape(RoundedRectangle(cornerRadius: 11))
                    }
                    .buttonStyle(.plain).foregroundStyle(model.selection == section ? teal : Color.primary)
                    .accessibilityAddTraits(model.selection == section ? .isSelected : [])
                    .help("\(section.rawValue) (⌘\((AppModel.Section.allCases.firstIndex(of: section) ?? 0) + 1))")
                }
            }.padding(.horizontal, 8)
            Spacer(minLength: 28)
            VStack(alignment: .leading, spacing: 9) {
                Divider().padding(.bottom, 5)
                BridgeStatusBadge(title: model.serviceLabel, healthy: model.error == nil && model.status?.service.healthy == true)
                if let checked = model.lastUpdated {
                    Text("Checked \(checked.formatted(date: .omitted, time: .shortened))").font(.system(size: 10)).foregroundStyle(.tertiary)
                }
                Text("Receives uploads while\nyour Mac is awake.").font(.system(size: 11)).lineSpacing(3).foregroundStyle(.secondary)
            }.padding(.horizontal, 15).padding(.bottom, 20)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .bridgeGlass(cornerRadius: 22).padding(10)
    }
}

struct OverviewView: View {
    @EnvironmentObject var model: AppModel
    @AppStorage("setup.firmwareConfirmedReference") private var firmwareConfirmedReference = ""
    let status: BridgeStatus
    private var readiness: SetupReadiness {
        SetupReadiness(status: status, firmwareConfirmedByUser: !firmwareConfirmedReference.isEmpty && firmwareConfirmedReference == SetupInput.firmwareConfirmationReference(status))
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            archiveSummary
            if status.usesExistingSetup || status.offersExistingSetup {
                ExistingSetupView(status: status)
            } else if readiness.recommendedStep != .complete {
                HStack(alignment: .center, spacing: 18) {
                    Image(systemName: "link").font(.system(size: 23, weight: .light)).foregroundStyle(teal).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(nextStepTitle).font(.system(size: 16, weight: .semibold))
                        Text(nextStepDetail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                    Button("Continue setup") { model.selection = .setup }.buttonStyle(.borderedProminent)
                }.padding(21).bridgeSurface()
            }
            Card(title: "Your bridge") {
                connectionRow("Local collector", symbol: "network", value: model.error != nil ? "Unable to check" : status.service.healthy ? "Online" : "Offline", detail: model.error != nil ? "The last status could not be refreshed" : status.service.healthy ? "Accepting highlight uploads" : "Readers can keep highlights queued", confirmed: model.error == nil && status.service.healthy)
                Divider()
                connectionRow("Kindle", symbol: "book.closed", value: kindleState, detail: status.usesExistingSetup ? "Based on recorded highlight uploads" : "KOReader · saved pairing", confirmed: status.kindle.paired)
                Divider()
                connectionRow("Xteink X4 Pro", symbol: "rectangle.portrait", value: xteinkState, detail: status.usesExistingSetup ? "Based on recorded highlight uploads" : "CrossPoint · saved pairing", confirmed: status.xteink.paired)
                Divider()
                HStack {
                    Label("Reading position", systemImage: "bookmark").font(.callout)
                    Spacer()
                    Text(status.usesExistingSetup ? "Managed on your readers" : status.progressVerified ? "Round trip confirmed by you" : "Not confirmed in this app").font(.callout).foregroundStyle(.secondary)
                }.padding(.vertical, 3)
            }
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: "info.circle").padding(.top, 1)
                Text("Highlights are kept in this archive. Reading positions sync through your readers’ own settings.").lineSpacing(3)
            }.font(.system(size: 12)).foregroundStyle(.secondary).padding(.horizontal, 3)
            if !status.warnings.isEmpty {
                DisclosureGroup("\(status.warnings.count) \(status.warnings.count == 1 ? "detail" : "details") to check") {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(status.warnings, id: \.self) { warning in
                            Label(warning, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }.padding(.top, 12)
                }.font(.callout).padding(18).bridgeSurface(cornerRadius: 16)
            }
        }
    }
    private var archiveSummary: some View {
        HStack(alignment: .center, spacing: 24) {
            VStack(alignment: .leading, spacing: 12) {
                Text("YOUR HIGHLIGHT ARCHIVE").font(.system(size: 10, weight: .semibold)).tracking(1.5).foregroundStyle(.secondary)
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(status.highlightCount.formatted()).font(.system(size: 50, weight: .regular, design: .serif)).monospacedDigit()
                    Text(status.highlightCount == 1 ? "line worth keeping" : "lines worth keeping").font(.system(size: 16, design: .serif)).foregroundStyle(.secondary)
                }
                Label(status.service.mode == "github" ? "On this Mac · GitHub backup enabled" : "Stored on this Mac", systemImage: "internaldrive").font(.system(size: 12)).foregroundStyle(.secondary)
                if status.service.pendingBackup > 0, status.service.mode == "github" {
                    Text("\(status.service.pendingBackup) awaiting backup").font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            Button { model.selection = .highlights } label: {
                HStack(spacing: 7) { Text("Open archive"); Image(systemName: "arrow.up.right") }
            }.buttonStyle(.bordered).controlSize(.large)
        }.padding(26).frame(maxWidth: .infinity, alignment: .leading).bridgeSurface(cornerRadius: 24)
    }
    private var kindleState: String {
        if status.usesExistingSetup { return status.kindle.paired ? "Uploads recorded" : "No uploads yet" }
        return status.kindle.paired ? (status.kindle.connected ? "Paired · USB connected" : "Paired") : "Not paired"
    }
    private var xteinkState: String {
        if status.usesExistingSetup { return status.xteink.paired ? "Uploads recorded" : "No uploads yet" }
        return status.xteink.paired ? "Paired" : "Not paired"
    }
    private var nextStepTitle: String {
        switch readiness.recommendedStep {
        case .bridge: return "Start your local collector"
        case .kindle: return "Connect your Kindle"
        case .xteink: return readiness.firmwareNeedsConfirmation ? "Finish your X4 Pro setup" : "Connect your X4 Pro"
        default: return "Check reading-position sync"
        }
    }
    private var nextStepDetail: String {
        switch readiness.recommendedStep {
        case .bridge: return "Your Mac collects highlights while it is awake."
        case .kindle: return "Install the KOReader plugin over USB."
        case .xteink: return readiness.firmwareNeedsConfirmation ? "Confirm Reader Bridge firmware is installed on your reader." : "Pair CrossPoint using its SD card or local network."
        default: return "Test the same EPUB in both directions."
        }
    }
    private func connectionRow(_ title: String, symbol: String, value: String, detail: String, confirmed: Bool) -> some View {
        HStack(spacing: 13) {
            Image(systemName: symbol).font(.system(size: 18, weight: .light)).foregroundStyle(teal).frame(width: 25).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 14, weight: .medium))
                Text(detail).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer()
            BridgeStatusBadge(title: value, healthy: confirmed)
        }.padding(.vertical, 5)
    }
}

func chooseFolder() -> String? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
    return panel.runModal() == .OK ? panel.url?.path : nil
}
