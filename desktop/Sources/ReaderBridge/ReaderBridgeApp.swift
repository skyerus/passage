import SwiftUI
import AppKit
import ServiceManagement

let ink = Color(red: 0.16, green: 0.20, blue: 0.19)
let teal = Color(red: 0.12, green: 0.43, blue: 0.39)
let paper = Color(red: 0.97, green: 0.96, blue: 0.93)

@main struct ReaderBridgeApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("Reader Bridge", id: "main") { ContentView().environmentObject(model).frame(minWidth: 850, minHeight: 650).task { model.startPolling() } }
            .defaultSize(width: 1080, height: 780)
        MenuBarExtra { MenuContent().environmentObject(model) } label: { Image(systemName: model.error == nil && model.status?.service.healthy == true ? "book.closed.fill" : "book.closed") }
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
            VStack(alignment: .leading, spacing: 28) {
                VStack(alignment: .leading, spacing: 8) { Image(systemName: "books.vertical").font(.system(size: 30)).foregroundStyle(teal); Text("Reader\nBridge").font(.system(size: 29, weight: .semibold, design: .serif)); Text("A home for your reading.").font(.caption).foregroundStyle(.secondary) }
                VStack(spacing: 6) { ForEach(AppModel.Section.allCases) { section in
                    Button { model.selection = section } label: { Label(section.rawValue, systemImage: section.icon).frame(maxWidth: .infinity, alignment: .leading).padding(11).background(model.selection == section ? teal.opacity(0.12) : .clear).clipShape(RoundedRectangle(cornerRadius: 9)) }.buttonStyle(.plain).foregroundStyle(model.selection == section ? teal : ink)
                } }
                Spacer()
                Label(model.serviceLabel, systemImage: model.error == nil && model.status?.service.healthy == true ? "circle.fill" : "circle").font(.caption).foregroundStyle(.secondary)
                Text("Your Mac hosts the bridge.\nKeep it awake to sync.").font(.caption2).foregroundStyle(.secondary)
            }.padding(24).frame(width: 225).background(Color.white.opacity(0.55))
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack { Text(model.selection.rawValue).font(.system(size: 34, weight: .medium, design: .serif)); Spacer(); Button { Task { await model.perform("status") } } label: { Image(systemName: "arrow.clockwise") }.help("Refresh status").disabled(model.busy) }
                    if model.busy { HStack(spacing: 10) { ProgressView().controlSize(.small); Text(model.activity).font(.callout) }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(teal.opacity(0.08)).cornerRadius(8) }
                    if let error = model.error { banner(error, symbol: "exclamationmark.triangle", color: .orange) }
                    if let notice = model.notice { HStack { banner(notice, symbol: "checkmark.circle", color: teal); Button { model.notice = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain) } }
                    if let status = model.status {
                        switch model.selection { case .overview: OverviewView(status: status); case .setup: SetupView(status: status); case .highlights: HighlightsView(status: status); case .settings: SettingsView(status: status) }
                    } else if !model.busy { Text("Status is unavailable. Refresh to reconnect to the local helper.").foregroundStyle(.secondary) }
                    if let updated = model.lastUpdated { Text("Last checked \(updated.formatted(date: .omitted, time: .standard))").font(.caption2).foregroundStyle(.secondary) }
                }.padding(32).frame(maxWidth: 1000, alignment: .leading)
            }
        }.background(paper).foregroundStyle(ink).tint(teal).preferredColorScheme(.light)
    }
    func banner(_ message: String, symbol: String, color: Color) -> some View { Label(message, systemImage: symbol).font(.callout).foregroundStyle(color).textSelection(.enabled).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(color.opacity(0.08)).cornerRadius(8) }
}
struct Card<Content: View>: View {
    let title: String; @ViewBuilder var content: Content
    var body: some View { VStack(alignment: .leading, spacing: 14) { Text(title).font(.system(size: 21, weight: .medium, design: .serif)); content }.padding(22).frame(maxWidth: .infinity, alignment: .leading).background(.white.opacity(0.8)).clipShape(RoundedRectangle(cornerRadius: 14)).overlay(RoundedRectangle(cornerRadius: 14).stroke(ink.opacity(0.07))) }
}
struct OverviewView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    var body: some View {
        Text("Pick up the thread, on either reader.").font(.title3).foregroundStyle(.secondary)
        HStack(spacing: 14) {
            metric("\(status.highlightCount)", "Archived highlights", "text.quote")
            metric(status.service.healthy ? "Online" : "Offline", "Local collector", "network")
        }
        if status.usesExistingSetup || status.offersExistingSetup {
            ExistingSetupView(status: status)
        } else {
        Card(title: status.setupStep == 5 ? "Your readers are paired" : "Let’s connect your readers") {
            Text(status.setupStep == 5 ? "Your reading-position roundtrip has been confirmed. Highlights are collected in one local archive; they are not recreated as underlines in the other reader’s book." : "Connect the local collector, pair your readers, then confirm a reading-position roundtrip.")
            Button(status.setupStep == 5 ? "Review setup" : "Continue setup · step \(status.setupStep) of 4") { model.selection = .setup }.buttonStyle(.borderedProminent)
        }
        }
        Card(title: "At a glance") {
            LabeledContent("Kindle", value: status.usesExistingSetup ? (status.kindle.paired ? "Highlights received" : "No uploads recorded yet") : status.kindle.paired ? (status.kindle.connected ? "Paired · USB connected" : "Paired") : "Not paired")
            LabeledContent("X4 Pro", value: status.usesExistingSetup ? (status.xteink.paired ? "Highlights received" : "No uploads recorded yet") : status.xteink.paired ? "Paired" : "Not paired")
            LabeledContent("Archive", value: status.service.mode == "github" ? "Local + GitHub backup" : "On this Mac")
            if status.service.pendingBackup > 0 { Text("\(status.service.pendingBackup) highlights awaiting backup").foregroundStyle(.secondary) }
            if !status.endpoint.isEmpty { Text(status.endpoint).font(.system(.callout, design: .monospaced)).textSelection(.enabled) }
        }
        ForEach(status.warnings, id: \.self) { Label($0, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary) }
    }
    func metric(_ value: String, _ label: String, _ symbol: String) -> some View { Card(title: value) { Label(label, systemImage: symbol).foregroundStyle(.secondary) } }
}
func chooseFolder() -> String? { let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false; return panel.runModal() == .OK ? panel.url?.path : nil }
