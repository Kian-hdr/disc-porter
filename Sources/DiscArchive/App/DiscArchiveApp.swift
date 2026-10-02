import SwiftUI
import AppKit

@main struct DiscArchiveApp: App {
    @NSApplicationDelegateAdaptor(ArchiveAppDelegate.self) private var delegate
    @State private var store = ArchiveStore.shared
    var body: some Scene {
        Window("Disc Porter", id: "main") {
            ContentView(store: store).frame(minWidth: 920, minHeight: 620)
                .preferredColorScheme(store.status?.settings.appearance == "dark" ? .dark : store.status?.settings.appearance == "light" ? .light : nil)
        }
        .defaultSize(width: 1180, height: 780)
        .commands { WorkspaceCommands(store: store) }
    }
}

@MainActor final class ArchiveAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let store = ArchiveStore.shared
        store.notifier.openJob = { [weak store] id in store?.selectedJobID = id; store?.destination = .queue; NSApp.activate(ignoringOtherApps: true) }
        store.startWatching()
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) { ArchiveStore.shared.stopWatching() }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let store = ArchiveStore.shared
        guard store.jobs.contains(where: \.isActive) else { return .terminateNow }
        let alert = NSAlert(); alert.messageText = "Archiving is in progress"
        alert.informativeText = "The local engine can continue in the background. Keep the source, archive drive and power connected."
        alert.addButton(withTitle: "Stay in app"); alert.addButton(withTitle: "Continue in background"); alert.addButton(withTitle: "Pause at checkpoint and quit")
        switch alert.runModal() {
        case .alertSecondButtonReturn: return .terminateNow
        case .alertThirdButtonReturn:
            Task {
                await store.prepareToDisconnect()
                while !store.safe {
                    try? await Task.sleep(for: .seconds(1)); await store.refresh()
                    if !store.connected || store.error != nil { sender.reply(toApplicationShouldTerminate: false); return }
                }
                sender.reply(toApplicationShouldTerminate: true)
            }
            return .terminateLater
        default: return .terminateCancel
        }
    }
}
