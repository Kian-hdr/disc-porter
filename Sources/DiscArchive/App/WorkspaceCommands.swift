import SwiftUI

struct WorkspaceCommands: Commands {
    let store: ArchiveStore
    @Environment(\.openWindow) private var openWindow
    var body: some Commands {
        CommandGroup(replacing: .newItem) {}
        CommandGroup(replacing: .appSettings) {
            Button("Settings…") { store.destination = .settings; openWindow(id: "main") }.keyboardShortcut(",")
        }
        CommandMenu("Archive") {
            Button("Scan for discs") { Task { await store.scan() } }.keyboardShortcut("r").disabled(store.scanning || !store.connected)
            Button("Prepare to disconnect") { Task { await store.prepareToDisconnect() } }.keyboardShortcut("p", modifiers: [.command, .shift]).disabled(!store.connected || store.busy)
            Button("Resume archiving") { Task { await store.queue("resume_archiving") } }.disabled(!store.connected || store.busy)
        }
    }
}
