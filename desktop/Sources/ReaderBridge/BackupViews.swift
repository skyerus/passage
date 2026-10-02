import AppKit
import SwiftUI

struct CloudBackupView: View {
    @EnvironmentObject var model: AppModel
    let status: BridgeStatus
    @State private var provider = "icloud"
    private var backup: BridgeStatus.CloudBackup? { status.cloudBackup }

    var body: some View {
        Card(title: "Backup") {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: "icloud").font(.system(size: 27, weight: .light)).foregroundStyle(teal)
                Text(backup?.enabled == true ? status.backupSummary : "Automatic backup")
                    .font(.headline)
            }
            if backup?.enabled == true {
                if let backup {
                    if !backup.savedAt.isEmpty {
                        Text("Saved \(HighlightPresentation.date(backup.savedAt))")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if !backup.error.isEmpty { Text(backup.error).font(.callout).foregroundStyle(.orange) }
                    HStack {
                        Button("Back up now") { Task { await model.perform("backup_now", activity: "Saving backup…", success: "Backup saved.") } }
                        BackupFinderButton(backup: backup)
                        Menu("More") {
                            Button("Use iCloud Drive…") { provider = "icloud"; chooseDestination() }
                            Button("Use another folder…") { provider = "folder"; chooseDestination() }
                            Button("Turn off automatic backup") { Task { await model.perform("disable_cloud_backup", activity: "Stopping backups…", success: "Automatic backup is off. Existing snapshots are kept.") } }
                        }
                    }
                }
            } else {
                Picker("Save backups to", selection: $provider) {
                    Text("iCloud Drive").tag("icloud")
                    Text("Another folder").tag("folder")
                }.pickerStyle(.menu).frame(maxWidth: 360, alignment: .leading)
                Button(provider == "icloud" ? "Turn on iCloud backup" : "Choose backup folder…", action: enableBackup)
                    .buttonStyle(.borderedProminent).tint(teal).disabled(!status.service.installed)
            }
            Divider()
            Button("Restore a backup…", action: restore).disabled(!status.service.healthy)
                .help("Adds missing highlights; keeps your current edits and deletions.")
        }
        .disabled(model.busy)
        .onAppear { provider = backup?.provider ?? "icloud" }
    }

    private func enableBackup() {
        let cloud = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs")
        if provider == "icloud", FileManager.default.fileExists(atPath: cloud.path) {
            Task { await model.perform("configure_cloud_backup", ["provider": "icloud", "folder": cloud.path], activity: "Setting up iCloud backup…", success: "iCloud backup is on. Your first snapshot is saved.") }
        } else { chooseDestination() }
    }

    private func chooseDestination() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
        panel.prompt = "Use for backups"
        panel.message = provider == "icloud" ? "Choose iCloud Drive or a folder inside it." : "Choose a folder, external drive, or cloud-synced folder."
        if provider == "icloud" {
            panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs")
        }
        if panel.runModal() == .OK, let url = panel.url {
            Task { await model.perform("configure_cloud_backup", ["provider": provider, "folder": url.path], activity: "Setting up backup…", success: "Automatic backup is on. Your first snapshot is saved.") }
        }
    }

    private func restore() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.canChooseFiles = true; panel.allowsMultipleSelection = false
        panel.prompt = "Restore highlights"
        panel.message = "Choose a .readerbridge backup. Missing highlights are restored; current edits and deletions are kept."
        if let folder = backup?.folder, !folder.isEmpty { panel.directoryURL = URL(fileURLWithPath: folder) }
        if panel.runModal() == .OK, let url = panel.url {
            Task { await model.perform("restore_backup", ["path": url.path], activity: "Restoring archive…", success: "Backup restored. Your current edits and deletions were kept.") }
        }
    }
}

/// Reveal the actual saved archive when available, otherwise open its destination.
struct BackupFinderButton: View {
    @EnvironmentObject var model: AppModel
    let backup: BridgeStatus.CloudBackup
    var body: some View {
        Button { reveal() } label: { Label("Show in Finder", systemImage: "folder") }
            .disabled(backup.folder.isEmpty)
            .help(backup.provider == "icloud" ? "Show the latest backup and its iCloud upload status" : "Show the latest backup")
    }
    private func reveal() {
        if let path = backup.snapshotPath, !path.isEmpty, FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
        } else if FileManager.default.fileExists(atPath: backup.folder) {
            if !NSWorkspace.shared.open(URL(fileURLWithPath: backup.folder)) {
                model.error = "Finder could not open your backup folder. Check that it is available."
            }
        } else {
            model.error = "Your backup folder is unavailable. Check iCloud Drive or reconnect the drive."
        }
    }
}
