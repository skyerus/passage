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
            Image(nsImage: model.error == nil && model.status?.service.healthy == true ? BrandMenuIcon.ready : BrandMenuIcon.offline)
                .accessibilityLabel("Reader Bridge: \(model.serviceLabel)")
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
        if let status = model.status { Text("\(status.highlightCount) highlights") }
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
                    BridgeEmptyState(symbol: "books.vertical", title: model.busy ? "Loading highlights…" : "Highlights are unavailable", detail: model.busy ? "" : "Refresh to try again.")
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
            Text(model.selection.rawValue).font(.system(size: 30, weight: .medium, design: .serif))
            Spacer()
            Button { Task { await model.perform("status") } } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 14, weight: .medium)).frame(width: 36, height: 36)
            }
            .buttonStyle(.plain).bridgeGlass(cornerRadius: 18, interactive: true)
            .disabled(model.busy).help("Refresh status (⌘R)").accessibilityLabel("Refresh status")
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
                BrandMark().frame(width: 48, height: 29)
                Text("Reader Bridge").font(.system(size: 22, weight: .medium, design: .serif))
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
                if let status = model.status {
                    Button(status.backupSummary) { model.selection = .settings }
                        .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                        .help("Backup settings")
                }
            }.padding(.horizontal, 15).padding(.bottom, 20)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .bridgeGlass(cornerRadius: 22).padding(10)
    }
}

func chooseFolder() -> String? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
    return panel.runModal() == .OK ? panel.url?.path : nil
}
