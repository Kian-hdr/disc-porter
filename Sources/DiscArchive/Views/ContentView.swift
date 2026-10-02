import SwiftUI

struct ContentView: View {
    @Bindable var store: ArchiveStore
    @Environment(\.openWindow) private var openWindow
    @State private var localSource: String?
    var body: some View {
        NavigationSplitView {
            List(WorkspaceDestination.allCases, selection: $store.destination) { destination in
                Label(destination.title, systemImage: destination.icon).tag(destination)
            }.listStyle(.sidebar).navigationSplitViewColumnWidth(min: 165, ideal: 190, max: 240)
        } detail: {
            VStack(spacing: 0) {
                WorkspaceStatusView(store: store)
                if let error = store.error { InlineErrorView(message: error) { store.error = nil } }
                Divider()
                switch store.destination {
                case .discs: DiscWorkspaceView(store: store, localSource: $localSource) { store.selectedJobID = $0; store.destination = .queue }
                case .queue: QueueView(store: store)
                case .library: LibraryView(store: store)
                case .profiles: ProfilesView(store: store)
                case .settings: ArchiveSettingsView(store: store)
                }
            }.navigationTitle(store.destination.title)
                .toolbar {
                    ToolbarItemGroup {
                        Button { Task { await store.scan() } } label: { Label("Scan", systemImage: "arrow.clockwise") }.disabled(store.scanning || !store.connected)
                        Button { store.destination = .settings } label: { Label("Settings", systemImage: "gearshape") }
                    }
                }
        }
        .onAppear {
            let controller = store
            let open = openWindow
            controller.notifier.openJob = { [weak controller] id in
                controller?.selectedJobID = id; controller?.destination = .queue; open(id: "main")
            }
        }
        .onChange(of: store.destination) { _, _ in Task { await store.refresh() } }

    }
}

struct WorkspaceStatusView: View {
    let store: ArchiveStore
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: store.safe ? "checkmark.shield" : "externaldrive").foregroundStyle(store.safe ? Color.green : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(!store.connected ? "Engine unavailable" : store.status?.disconnectFenced == true ? "Prepared to disconnect" : store.safe ? "Disc Porter has no active writes" : "Keep the archive drive connected").font(.callout.weight(.medium))
                Text(store.safe ? "Eject in Finder before unplugging." : store.scanning ? "Reading disc information…" : "Processing continues locally when the app closes.").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if let free = store.status?.storage?["free_bytes"].number {
                Text("\(ByteCountFormatter.string(fromByteCount: Int64(free), countStyle: .file)) free").font(.caption).foregroundStyle(.secondary)
            }
            if !store.connected { Button("Reconnect") { Task { await store.reconnect() } }.disabled(store.busy) }
            else if store.status?.disconnectFenced == true { Button("Resume archiving") { Task { await store.queue("resume_archiving") } }.disabled(store.busy) }
            else { Button("Prepare to disconnect") { Task { await store.prepareToDisconnect() } }.disabled(store.busy) }
        }.padding(.horizontal, 20).padding(.vertical, 10)
    }
}

private struct InlineErrorView: View {
    let message: String
    let dismiss: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange)
            Text(message).font(.callout).textSelection(.enabled)
            Spacer()
            Button(action: dismiss) { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Dismiss error")
        }.padding(12).background(.quaternary)
    }
}
