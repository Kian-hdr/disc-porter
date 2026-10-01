import SwiftUI
import AppKit

@main
struct DiscArchiveApp: App {
    @NSApplicationDelegateAdaptor(ArchiveAppDelegate.self) private var delegate
    @State private var store = ArchiveStore.shared

    var body: some Scene {
        WindowGroup("Disc Porter", id: "main") {
            ContentView(store: store)
                .frame(minWidth: 900, minHeight: 640)
                .task { await store.watch() }
        }
        .defaultSize(width: 1120, height: 780)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("Archive") {
                Button("Scan for discs") { Task { await store.scan() } }
                    .keyboardShortcut("r").disabled(store.scanning || !store.connected)
                Button("Prepare to disconnect") { Task { await store.prepareToDisconnect() } }
                    .keyboardShortcut("p", modifiers: [.command, .shift]).disabled(!store.connected || store.busy)
            }
        }
        Settings { ArchiveSettingsView(store: store) }
    }
}

@MainActor
final class ArchiveAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let store = ArchiveStore.shared
        guard store.jobs.contains(where: \.isActive) else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "Archiving is still in progress"
        alert.informativeText = "You can keep the processing engine running after closing the app, or finish the current checkpoint before quitting. Keep the archive drive and power connected while work is active."
        alert.addButton(withTitle: "Stay in app")
        alert.addButton(withTitle: "Continue in background")
        alert.addButton(withTitle: "Pause at checkpoint and quit")
        switch alert.runModal() {
        case .alertSecondButtonReturn: return .terminateNow
        case .alertThirdButtonReturn:
            Task {
                await store.prepareToDisconnect()
                while !store.safe {
                    try? await Task.sleep(for: .seconds(1))
                    await store.refresh()
                    if !store.connected {
                        sender.reply(toApplicationShouldTerminate: false)
                        return
                    }
                }
                sender.reply(toApplicationShouldTerminate: true)
            }
            return .terminateLater
        default: return .terminateCancel
        }
    }
}
